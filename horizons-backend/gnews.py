import urllib.parse
from utils.scraper_utils import scrapeArticleWithUrl, scrapeArticleWithHtml
from utils.text_utils import buildQuery
from utils.constant_utils import BASE_URL, SUPPORTED_NEWS_SOURCES, REQUEST_HEADER
import feedparser
import ssl
import base64
import functools
import re
import aiohttp
import asyncio

ssl._create_default_https_context = ssl._create_unverified_context
cookies = {'CONSENT': 'YES+cb.20210720-07-p0.en+FX+410'}

class GNewsEntry:
    def __init__(self, title, link, date_published, source):
        self.title = title
        self.link = link
        self.date_published = date_published
        self.source = source

class NewsEntry:
    def __init__(self, title, article, link, date_published, source):
        self.title = title
        self.article = article
        self.link = link
        self.date_published = date_published
        self.source = source

    def export(self):
        return {
            "title": self.title,
            "source": self.source.name,
            "url": self.link,
        }


def getSimilarArticles(url):
    source, title, article = scrapeArticleWithUrl(url)
    original_article = NewsEntry(title, article, url, "", source)
    if (source == None or title == None or article == None):
      return []
    query = buildQuery(title, article)
    articles = scrapeGNews(query, source)
    return original_article, articles


def scrapeGNews(query, source):
    query = urllib.parse.quote(query)
    url = BASE_URL + "?q=" + query + "&hl=en-SG&gl=SG&ceid=SG%3Aen"

    feed = feedparser.parse(url)
    entries = parseGNewsRSS(feed)

    return entries

def parseGNewsRSS(feed):
    entries = list(filter(lambda item: item is not None, map(parseGNewsEntry, feed['entries'])))
    entries = parseNewsEntries(entries)
    return entries

def parseGNewsEntry(entry):
    title = entry['title']
    date_published = entry['published']
    source = entry['source']['title']
    if (source.strip() in SUPPORTED_NEWS_SOURCES):
        url = decode_google_news_url(entry['link'])
        return GNewsEntry(title, url, date_published, source)
    else:
       return None

def parseNewsEntries(entries):
    newsEntries = list(filter(lambda x: x!= None, asyncio.run(asyncParseNewsEntries(entries))))
    return newsEntries

async def asyncParseNewsEntries(entries):
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        tasks = [
        parseEntry(e, session)
            for e in entries
        ]
        return await asyncio.gather(*tasks)

async def parseEntry(e, session):
    async with session.get(e.link, headers=REQUEST_HEADER) as response:
        html = await response.text()
        source, header, article = scrapeArticleWithHtml(e.link, html)
        if (article != None):
            return NewsEntry(header, article, e.link, e.date_published, source)
        return None

# TODO: refactor google news URL parsing to utils
_ENCODED_URL_PREFIX = "https://news.google.com/rss/articles/"
_ENCODED_URL_RE = re.compile(fr"^{re.escape(_ENCODED_URL_PREFIX)}(?P<encoded_url>[^?]+)")
_DECODED_URL_RE = re.compile(rb'^\x08\x13".+?(?P<primary_url>http[^\xd2]+)\xd2\x01')

@functools.lru_cache(2048)
def _decode_google_news_url(url: str) -> str:
    match = _ENCODED_URL_RE.match(url)
    encoded_text = match.groupdict()["encoded_url"]  # type: ignore
    encoded_text += "==="  # Fix incorrect padding. Ref: https://stackoverflow.com/a/49459036/
    decoded_text = base64.urlsafe_b64decode(encoded_text)

    match = _DECODED_URL_RE.match(decoded_text)
    primary_url = match.groupdict()["primary_url"]  # type: ignore
    primary_url = primary_url.decode()
    return primary_url


def decode_google_news_url(url: str) -> str:  # Not cached because not all Google News URLs are encoded.
    """Return Google News entry URLs after decoding their encoding as applicable."""
    return _decode_google_news_url(url) if url.startswith(_ENCODED_URL_PREFIX) else url


