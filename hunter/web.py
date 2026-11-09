"""Polite web access: fetching pages, reading them as text, finding emails.

The rules every request follows (see "Ground rules" in the README):
- Never touch social networks and job sites whose terms forbid bots
  (LinkedIn, X, Facebook, Instagram, Xing, Glassdoor, Indeed...).
- Obey robots.txt, including Crawl-delay. If robots.txt can't be read because the
  site has a server error, don't crawl that site (as RFC 9309 says).
- Wait between requests (a few seconds between any two requests, longer between
  pages of the same site), and stop visiting a site for the rest of the run if
  it answers "too many requests" (429) or "unavailable" (503).
- Say honestly who we are in the User-Agent.
"""

from __future__ import annotations

import re
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = ("StartupHunter/1.1 (personal job-search bot; "
              "+https://github.com/Abdal-Dev/startup-hunter)")

# Never fetched at all, in any country: their terms forbid scraping or bots.
# Matched by name, so linkedin.com, de.linkedin.com and indeed.fr are all covered.
NEVER_FETCH_NAMES = {
    "linkedin", "xing", "facebook", "instagram", "twitter", "tiktok", "threads",
    "glassdoor", "indeed", "crunchbase", "kununu", "stepstone", "pitchbook",
}
NEVER_FETCH_DOMAINS = {"x.com", "t.co", "lnkd.in", "fb.com"}

# Search engines' own links (ads, redirects): never worth reading.
SEARCH_ENGINE_DOMAINS = {"bing.com", "duckduckgo.com", "google.com", "yahoo.com"}

# May be read as articles, but never a startup's own homepage.
BLOCKED_DOMAINS = {
    "youtube.com", "wikipedia.org", "northdata.de", "northdata.com", "google.com",
    "arbeitnow.com", "github.com", "medium.com", "reddit.com", "bing.com",
    "duckduckgo.com", "wellfound.com", "angel.co", "f6s.com", "dealroom.co",
    "tracxn.com", "seedtable.com", "failory.com", "eu-startups.com", "sifted.eu",
    "techcrunch.com", "welcometothejungle.com", "startupsucht.com", "vcnews.de",
    "gruendungsindex.de", "t3n.de", "handelsblatt.com", "sueddeutsche.de",
    "spiegel.de", "zeit.de", "faz.net", "welt.de", "mdr.de", "saechsische.de",
    "dnn.de", "dresden.de", "tu-dresden.de", "startbase.de", "startupdetector.de",
    "deutsche-startups.de", "gruenderszene.de", "businessinsider.de", "yelp.de",
    "gelbeseiten.de", "dasoertliche.de",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
AT_RE = re.compile(r"\s*[\[(]\s*at\s*[\])]\s*", re.IGNORECASE)
DOT_RE = re.compile(r"\s*[\[(]\s*dot\s*[\])]\s*", re.IGNORECASE)
NOT_EMAIL_ENDINGS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")


def normalize_domain(url: str) -> str:
    """'https://www.Example.com/about' -> 'example.com'. Empty string if invalid."""
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host if "." in host else ""


def never_fetch(domain: str) -> bool:
    """True for social networks and job sites we must never request."""
    parts = domain.lower().split(".")
    if any(".".join(parts[i:]) in NEVER_FETCH_DOMAINS for i in range(len(parts) - 1)):
        return True
    return any(label in NEVER_FETCH_NAMES for label in parts[:-1])


def is_blocked(domain: str) -> bool:
    """True if the domain can't be a startup's homepage (or must never be fetched)."""
    if never_fetch(domain):
        return True
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        if ".".join(parts[i:]) in BLOCKED_DOMAINS:
            return True
    return False


def html_to_text(html: str, max_chars: int = 6000) -> str:
    """Strip scripts, menus and tags, and return readable text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    return text[:max_chars]


def find_links(html: str, base_url: str, keywords: list[str]) -> list[str]:
    """Links whose text or address contains a keyword, earlier keywords first."""
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        label = (a.get_text(" ") + " " + a["href"]).lower()
        ranks = [i for i, k in enumerate(keywords) if k in label]
        if ranks:
            link = urljoin(base_url, a["href"])
            if link.startswith("http") and link not in found:
                found[link] = ranks[0]
    return sorted(found, key=found.get)


def extract_emails(html_or_text: str) -> list[str]:
    """All email addresses on a page, without image file names and duplicates."""
    # Undo common anti-spam spellings like "info [at] startup [dot] de".
    text = AT_RE.sub("@", html_or_text)
    text = DOT_RE.sub(".", text)
    emails = []
    for match in EMAIL_RE.findall(text):
        email = match.strip(".").lower()
        if email.endswith(NOT_EMAIL_ENDINGS) or email in emails:
            continue
        emails.append(email)
    return emails


def site_root(url: str) -> str:
    return "{0.scheme}://{0.netloc}".format(urlparse(url))


class Http:
    """Fetches pages politely: robots.txt, delays, and backing off when asked."""

    BACK_OFF_CODES = (429, 503)   # "too many requests", "unavailable"
    MAX_CRAWL_DELAY = 30          # seconds; slower sites are skipped instead

    def __init__(self, delay_seconds: float = 3, site_delay_seconds: float = 5,
                 timeout: int = 15, log=print):
        self.delay = delay_seconds            # between any two requests
        self.site_delay = site_delay_seconds  # between two pages of the same site
        self.timeout = timeout
        self.log = log
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._site_delay: dict[str, float] = {}   # Crawl-delay from robots.txt
        self._site_last: dict[str, float] = {}
        self._backed_off: set[str] = set()
        self._last_request = 0.0

    def _wait(self, root: str):
        """Pause so we never go faster than our delays, or the site's Crawl-delay."""
        now = time.time()
        site_delay = max(self.site_delay, self._site_delay.get(root, 0))
        pause = max(self.delay - (now - self._last_request),
                    site_delay - (now - self._site_last.get(root, 0)))
        if pause > 0:
            time.sleep(pause)
        self._last_request = self._site_last[root] = time.time()

    def _request(self, url: str):
        root = site_root(url)
        self._wait(root)
        r = self.session.get(url, timeout=self.timeout)
        if r.status_code in self.BACK_OFF_CODES:
            self._backed_off.add(root)
            self.log(f"  ! {root} asked us to slow down ({r.status_code}), "
                     "skipping it for this run")
        return r

    def allowed(self, url: str) -> bool:
        """May we fetch this URL? Checks the never-fetch list and robots.txt."""
        root = site_root(url)
        if never_fetch(urlparse(url).hostname or "") or root in self._backed_off:
            return False
        if root not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                r = self._request(root + "/robots.txt")
                if r.ok:
                    parser.parse(r.text.splitlines())
                elif 400 <= r.status_code < 500 and r.status_code != 429:
                    parser.parse([])  # no robots.txt: everything is allowed
                else:
                    parser = None     # server error: assume we may not crawl
            except requests.RequestException:
                parser = None
            self._robots[root] = parser
            if parser is not None:
                crawl_delay = parser.crawl_delay(USER_AGENT)
                if crawl_delay and float(crawl_delay) > self.MAX_CRAWL_DELAY:
                    self._robots[root] = None   # too slow to visit politely
                elif crawl_delay:
                    self._site_delay[root] = float(crawl_delay)
        parser = self._robots[root]
        return parser is not None and parser.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> str | None:
        """Return the page's HTML, or None if it fails or isn't allowed."""
        if not self.allowed(url):
            return None
        try:
            r = self._request(url)
            if r.ok and "html" in r.headers.get("Content-Type", "html"):
                return r.text
        except requests.RequestException:
            pass
        return None

    def get_json(self, url: str) -> dict | None:
        """For public APIs that are meant to be called (the job board)."""
        if site_root(url) in self._backed_off:
            return None
        try:
            r = self._request(url)
            return r.json() if r.ok else None
        except (requests.RequestException, ValueError):
            return None


SEARCH_DELAY = 3.0          # seconds between searches
_search_state = {"last": 0.0, "rate_limited": False}


def web_search(query: str, max_results: int = 8, region: str = "wt-wt") -> list[dict]:
    """Search DuckDuckGo. Returns [{'title', 'href', 'body'}, ...].

    Searches are spaced out, and if the search engine rate-limits us we stop
    searching for the rest of the run instead of retrying.
    """
    from ddgs import DDGS  # imported here so tests run without the package

    if _search_state["rate_limited"]:
        return []
    pause = SEARCH_DELAY - (time.time() - _search_state["last"])
    if pause > 0:
        time.sleep(pause)
    _search_state["last"] = time.time()
    try:
        return list(DDGS().text(query, region=region, max_results=max_results))
    except Exception as error:  # search can fail or rate-limit; don't crash the run
        if "ratelimit" in type(error).__name__.lower():
            _search_state["rate_limited"] = True
            print("  ! search engine rate limit reached, no more searches this run")
        elif "no results" not in str(error).lower():
            print(f"  ! search failed for '{query}': {error}")
        return []
