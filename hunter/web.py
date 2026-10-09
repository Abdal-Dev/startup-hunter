"""Polite web access: fetching pages, reading them as text, finding emails."""

from __future__ import annotations

import re
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "StartupHunter/1.0 (personal job search; contact: see profile)"

# Sites that are never a startup's own homepage.
BLOCKED_DOMAINS = {
    "linkedin.com", "xing.com", "facebook.com", "instagram.com", "twitter.com",
    "x.com", "youtube.com", "tiktok.com", "wikipedia.org", "crunchbase.com",
    "northdata.de", "northdata.com", "kununu.com", "indeed.com", "indeed.de",
    "stepstone.de", "glassdoor.de", "glassdoor.com", "google.com", "arbeitnow.com",
    "github.com", "medium.com", "t3n.de", "handelsblatt.com", "sueddeutsche.de",
    "spiegel.de", "zeit.de", "faz.net", "welt.de", "mdr.de", "saechsische.de",
    "dnn.de", "dresden.de", "tu-dresden.de", "startbase.de", "startupdetector.de",
    "deutsche-startups.de", "gruenderszene.de", "businessinsider.de", "bing.com",
    "duckduckgo.com", "yelp.de", "gelbeseiten.de", "dasoertliche.de",
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


def is_blocked(domain: str) -> bool:
    """True if the domain (or a parent domain) is on the block list."""
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
    """Links on the page whose text or address contains one of the keywords."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        label = (a.get_text(" ") + " " + a["href"]).lower()
        if any(k in label for k in keywords):
            link = urljoin(base_url, a["href"])
            if link.startswith("http") and link not in found:
                found.append(link)
    return found


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


class Http:
    """Fetches pages with a delay between requests and respects robots.txt."""

    def __init__(self, delay_seconds: float = 1.5, timeout: int = 15):
        self.delay = delay_seconds
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_request = 0.0

    def _wait(self):
        pause = self.delay - (time.time() - self._last_request)
        if pause > 0:
            time.sleep(pause)
        self._last_request = time.time()

    def allowed(self, url: str) -> bool:
        """Check the site's robots.txt (if it has none, we may read it)."""
        root = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if root not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                self._wait()
                r = self.session.get(root + "/robots.txt", timeout=self.timeout)
                parser.parse(r.text.splitlines() if r.ok else [])
                self._robots[root] = parser
            except requests.RequestException:
                self._robots[root] = None
        parser = self._robots[root]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> str | None:
        """Return the page's HTML, or None if it fails or isn't allowed."""
        if not self.allowed(url):
            return None
        try:
            self._wait()
            r = self.session.get(url, timeout=self.timeout)
            if r.ok and "html" in r.headers.get("Content-Type", "html"):
                return r.text
        except requests.RequestException:
            pass
        return None

    def get_json(self, url: str) -> dict | None:
        try:
            self._wait()
            r = self.session.get(url, timeout=self.timeout)
            return r.json() if r.ok else None
        except (requests.RequestException, ValueError):
            return None


def web_search(query: str, max_results: int = 8) -> list[dict]:
    """Search DuckDuckGo. Returns [{'title', 'href', 'body'}, ...]."""
    from ddgs import DDGS  # imported here so tests run without the package

    try:
        return list(DDGS().text(query, region="de-de", max_results=max_results))
    except Exception as error:  # search can fail or rate-limit; don't crash the run
        print(f"  ! search failed for '{query}': {error}")
        return []
