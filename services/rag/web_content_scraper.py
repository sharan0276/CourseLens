"""
Web Content Scraper — fetches supplementary C++ content from external
educational websites (GeeksForGeeks, W3Schools, LearnCpp) and returns
LangChain Document objects for injection into RAG context.

Design principles:
  • Each site is a self-contained scraper strategy — easy to add more later
  • In-memory LRU cache avoids re-fetching the same topic within a session
  • 5-second timeout per request; failures degrade silently
  • Content is truncated to ~1500 chars per article to protect the context window
  • Returns Document objects with source_type="web" metadata for downstream formatting
"""

import re
import time
import requests
from typing import List, Dict, Optional, Callable
from functools import lru_cache
from urllib.parse import quote_plus
from langchain_core.documents import Document

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # graceful degradation if bs4 not installed


# ── Constants ────────────────────────────────────────────────────────────────

_REQUEST_TIMEOUT = 5  # seconds
_MAX_CONTENT_LENGTH = 1500  # chars per article
_MAX_ARTICLES_PER_SITE = 2
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _USER_AGENT}
_NOISE_TITLES = {"index", "latest changes", "search", "category", "tag", "archive", "log in", "sign up", "site map"}


# ── Site Scrapers ────────────────────────────────────────────────────────────

def _scrape_geeksforgeeks(topic: str) -> List[Document]:
    """
    Searches GeeksForGeeks for C++ articles on the given topic.
    Uses their internal search API endpoint to find relevant pages,
    then scrapes article content from top results.
    """
    docs = []
    search_url = f"https://www.geeksforgeeks.org/search/{quote_plus(topic + ' C++')}/"

    try:
        resp = requests.get(search_url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # GFG search results are typically in article cards with links
        article_links = []
        for a_tag in soup.find_all("a", href=True):
            # FIX: Ensure it's a search result link by checking for nested headings or gs-title
            is_result_link = bool(a_tag.find(["h2", "h3"]) or a_tag.find(class_="gs-title") or "gs-title" in a_tag.get("class", []))
            if not is_result_link:
                continue

            href = a_tag["href"]
            # Sometimes Custom Search wraps the URL
            if "/url?q=" in href:
                href = href.split("/url?q=")[1].split("&")[0]

            if (
                "geeksforgeeks.org" in href
                and "/search/" not in href
                and href.count("/") >= 3
                and not href.endswith(("#", "/"))
                and "login" not in href
                and "auth" not in href
            ):
                if href not in article_links:
                    article_links.append(href)
            if len(article_links) >= _MAX_ARTICLES_PER_SITE:
                break

        for link in article_links[:_MAX_ARTICLES_PER_SITE]:
            doc = _fetch_gfg_article(link, topic)
            if doc:
                docs.append(doc)

    except Exception as e:
        print(f"[WebScraper] GFG search failed for '{topic}': {e}")

    return docs


def _fetch_gfg_article(url: str, topic: str) -> Optional[Document]:
    """Fetches and parses a single GeeksForGeeks article."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # GFG articles are in <div class="article-body"> or <div class="text">
        article_div = (
            soup.find("div", class_="article-body")
            or soup.find("div", class_="text")
            or soup.find("article")
        )
        if not article_div:
            return None

        title = soup.find("title")
        title_text = title.get_text(strip=True) if title else topic

        # Extract text, preserving code blocks
        content = _extract_text_with_code(article_div)
        if len(content.strip()) < 50:
            return None

        content = _truncate(content)

        return Document(
            page_content=content,
            metadata={
                "source_type": "web",
                "source_site": "GeeksForGeeks",
                "source_file": url,
                "title": title_text,
                "topic": topic,
            }
        )
    except Exception as e:
        print(f"[WebScraper] GFG article fetch failed for {url}: {e}")
        return None


def _scrape_w3schools(topic: str) -> List[Document]:
    """
    Searches W3Schools for C++ content. W3Schools has predictable URL patterns
    for C++ topics — we try direct URL construction first, then fallback to
    Google site-search.
    """
    docs = []

    # Normalize topic for URL construction
    slug = _topic_to_slug(topic)
    candidate_urls = [
        f"https://www.w3schools.com/cpp/cpp_{slug}.asp",    # e.g., cpp_pointers.asp
        f"https://www.w3schools.com/cpp/cpp_ref_{slug}.asp", # FIX: Added reference path (e.g., cpp_ref_keywords.asp)
        f"https://www.w3schools.com/cpp/{slug}.asp",        # e.g., references.asp
    ]

    for url in candidate_urls:
        doc = _fetch_w3schools_page(url, topic)
        if doc:
            docs.append(doc)
            if len(docs) >= _MAX_ARTICLES_PER_SITE:
                break

    # If direct URLs didn't work, try Google site-search
    if not docs:
        docs = _google_site_search("w3schools.com/cpp", topic, "W3Schools")

    return docs[:_MAX_ARTICLES_PER_SITE]


def _fetch_w3schools_page(url: str, topic: str) -> Optional[Document]:
    """Fetches and parses a single W3Schools page."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # W3Schools content is in <div id="main"> or <div class="w3-main">
        main_div = (
            soup.find("div", id="main")
            or soup.find("div", class_="w3-main")
        )
        if not main_div:
            return None

        title = soup.find("title")
        title_text = title.get_text(strip=True) if title else topic

        content = _extract_text_with_code(main_div)
        if len(content.strip()) < 50:
            return None

        content = _truncate(content)

        return Document(
            page_content=content,
            metadata={
                "source_type": "web",
                "source_site": "W3Schools",
                "source_file": url,
                "title": title_text,
                "topic": topic,
            }
        )
    except Exception as e:
        print(f"[WebScraper] W3Schools fetch failed for {url}: {e}")
        return None


def _scrape_learncpp(topic: str) -> List[Document]:
    """
    Searches LearnCpp.com for relevant C++ tutorials.
    LearnCpp has a search endpoint we can leverage, or we use Google site-search.
    """
    docs = _google_site_search("learncpp.com", topic, "LearnCpp")
    
    if not docs:
        # Try the LearnCpp search page directly
        try:
            search_url = f"https://www.learncpp.com/?s={quote_plus(topic)}"
            resp = requests.get(search_url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            article_links = []
            for a_tag in soup.find_all("a", href=True):
                # FIX: LearnCpp uses Google Custom Search directly in its results page
                # We must prioritize links with the .gs-title class
                if "gs-title" not in a_tag.get("class", []):
                    # Also try finding it inside if it's nested
                    if not a_tag.find(class_="gs-title"):
                        continue
                
                href = a_tag["href"]
                # Sometimes Google Search wraps the URL
                if "/url?q=" in href:
                    href = href.split("/url?q=")[1].split("&")[0]

                if (
                    "learncpp.com" in href
                    and "?s=" not in href
                    and href.count("/") >= 3
                ):
                    if href not in article_links:
                        article_links.append(href)
                if len(article_links) >= _MAX_ARTICLES_PER_SITE:
                    break

            for link in article_links[:_MAX_ARTICLES_PER_SITE]:
                doc = _fetch_learncpp_article(link, topic)
                if doc:
                    docs.append(doc)

        except Exception as e:
            print(f"[WebScraper] LearnCpp search failed for '{topic}': {e}")

    return docs[:_MAX_ARTICLES_PER_SITE]


def _fetch_learncpp_article(url: str, topic: str) -> Optional[Document]:
    """Fetches and parses a single LearnCpp article."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # LearnCpp puts content in <div class="entry-content"> or <article>
        content_div = (
            soup.find("div", class_="entry-content")
            or soup.find("article")
            or soup.find("div", class_="post-content")
        )
        if not content_div:
            return None

        title = soup.find("title")
        title_text = title.get_text(strip=True) if title else topic

        content = _extract_text_with_code(content_div)
        if len(content.strip()) < 50:
            return None

        content = _truncate(content)

        return Document(
            page_content=content,
            metadata={
                "source_type": "web",
                "source_site": "LearnCpp",
                "source_file": url,
                "title": title_text,
                "topic": topic,
            }
        )
    except Exception as e:
        print(f"[WebScraper] LearnCpp article fetch failed for {url}: {e}")
        return None


# ── Google Site-Search Fallback ──────────────────────────────────────────────

def _google_site_search(site_domain: str, topic: str, site_label: str) -> List[Document]:
    """
    Uses a simple Google search to find pages on a specific site.
    Parses the Google results page for links, then fetches and scrapes them.
    """
    docs = []
    query = f"site:{site_domain} {topic} C++"
    google_url = f"https://www.google.com/search?q={quote_plus(query)}&num=3"

    try:
        resp = requests.get(google_url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            # Google wraps URLs in /url?q=<actual_url>&...
            if "/url?q=" in href:
                actual = href.split("/url?q=")[1].split("&")[0]
                if site_domain in actual and actual.startswith("http"):
                    links.append(actual)
            elif site_domain in href and href.startswith("http"):
                links.append(href)

        # deduplicate while preserving order
        seen = set()
        unique_links = []
        for link in links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)

        for link in unique_links[:_MAX_ARTICLES_PER_SITE]:
            doc = _fetch_generic_article(link, topic, site_label)
            if doc:
                docs.append(doc)

    except Exception as e:
        print(f"[WebScraper] Google site-search failed for '{site_domain}' / '{topic}': {e}")

    return docs


def _fetch_generic_article(url: str, topic: str, site_label: str) -> Optional[Document]:
    """Generic article fetcher for any site via Google site-search fallback."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try common content containers
        content_div = (
            soup.find("article")
            or soup.find("div", class_="entry-content")
            or soup.find("div", class_="article-body")
            or soup.find("div", id="main")
            or soup.find("main")
        )
        if not content_div:
            return None

        title = soup.find("title")
        title_text = title.get_text(strip=True) if title else topic

        content = _extract_text_with_code(content_div)
        if len(content.strip()) < 50:
            return None

        content = _truncate(content)

        return Document(
            page_content=content,
            metadata={
                "source_type": "web",
                "source_site": site_label,
                "source_file": url,
                "title": title_text,
                "topic": topic,
            }
        )
    except Exception as e:
        print(f"[WebScraper] Generic fetch failed for {url}: {e}")
        return None


# ── Text Extraction Utilities ────────────────────────────────────────────────

def _extract_text_with_code(element) -> str:
    """
    Extracts text from an HTML element, preserving code blocks as markdown.
    Skips navigation, ads, and other noise elements.
    """
    if BeautifulSoup is None:
        return ""

    # Remove noise elements
    for tag in element.find_all(["nav", "footer", "header", "script", "style", "aside"]):
        tag.decompose()

    # Remove ad containers and social sharing
    for div in element.find_all("div", class_=re.compile(r"(ad-|social|share|comment|related|sidebar)", re.I)):
        div.decompose()

    parts = []
    for child in element.descendants:
        if child.name in ["pre", "code"]:
            code_text = child.get_text()
            if code_text.strip():
                parts.append(f"\n```cpp\n{code_text.strip()}\n```\n")
            # Skip children of code blocks to avoid duplication
            continue
        elif child.name is None:  # NavigableString (text node)
            text = child.strip() if isinstance(child, str) else str(child).strip()
            if text and child.parent.name not in ["pre", "code", "script", "style"]:
                parts.append(text)

    return " ".join(parts)


def _truncate(content: str) -> str:
    """Truncates content to _MAX_CONTENT_LENGTH, breaking at sentence boundary."""
    if len(content) <= _MAX_CONTENT_LENGTH:
        return content

    truncated = content[:_MAX_CONTENT_LENGTH]
    # Try to break at a sentence boundary
    last_period = truncated.rfind(". ")
    if last_period > _MAX_CONTENT_LENGTH * 0.5:
        truncated = truncated[:last_period + 1]

    return truncated + " [...]"


def _topic_to_slug(topic: str) -> str:
    """Converts a topic string ('Pointers and References') to a URL slug ('pointers')."""
    # Take the first meaningful word
    words = topic.lower().replace("-", " ").split()
    # Remove common filler words
    stop_words = {"and", "or", "the", "a", "an", "in", "of", "for", "to", "with", "on"}
    meaningful = [w for w in words if w not in stop_words]
    if meaningful:
        return meaningful[0]
    return words[0] if words else topic.lower()


# ── Main Scraper Class ───────────────────────────────────────────────────────

class WebContentScraper:
    """
    Orchestrates web content fetching across multiple educational sites.

    Usage:
        scraper = WebContentScraper()
        docs = scraper.search_topics(["Pointers", "Dynamic Memory"])

    Features:
        • Searches GFG, W3Schools, and LearnCpp in parallel (per topic)
        • In-memory cache avoids redundant fetches for the same topic
        • Gracefully degrades — never raises; returns [] on any failure
        • distinguish_sources flag controls whether web content is visually
          distinguished in the response (default: False = blended)
    """

    def __init__(self, distinguish_sources: bool = False):
        self.distinguish_sources = distinguish_sources
        self._cache: Dict[str, List[Document]] = {}

        # ordered list of (site_label, scraper_fn) — easy to extend
        self._scrapers: List[tuple] = [
            ("GeeksForGeeks", _scrape_geeksforgeeks),
            ("W3Schools", _scrape_w3schools),
            ("LearnCpp", _scrape_learncpp),
        ]

    def search_topics(self, topics: List[str]) -> List[Document]:
        """
        Searches all configured sites for each topic.
        Returns deduplicated list of Document objects.
        """
        if BeautifulSoup is None:
            print("[WebScraper] beautifulsoup4 not installed — skipping web enrichment")
            return []

        all_docs = []

        for topic in topics:
            # check cache first
            cache_key = topic.lower().strip()
            if cache_key in self._cache:
                print(f"[WebScraper] Cache hit for '{topic}'")
                all_docs.extend(self._cache[cache_key])
                continue

            topic_docs = []
            for site_label, scraper_fn in self._scrapers:
                try:
                    print(f"[WebScraper] Searching {site_label} for '{topic}'...")
                    site_docs = scraper_fn(topic)
                    
                    # Filter noise (Site indexes, search pages, etc.)
                    filtered_site_docs = []
                    for doc in site_docs:
                        title = doc.metadata.get("title", "").lower()
                        if not any(noise in title for noise in _NOISE_TITLES):
                            filtered_site_docs.append(doc)
                        else:
                            print(f"[WebScraper] Filtering noise document: {doc.metadata.get('title')}")
                    
                    topic_docs.extend(filtered_site_docs)
                    if filtered_site_docs:
                        print(f"[WebScraper] Found {len(filtered_site_docs)} relevant article(s) from {site_label}")
                except Exception as e:
                    print(f"[WebScraper] {site_label} scraper failed for '{topic}': {e}")

            # cache for this topic
            self._cache[cache_key] = topic_docs
            all_docs.extend(topic_docs)

        # deduplicate by URL
        seen_urls = set()
        unique = []
        for doc in all_docs:
            url = doc.metadata.get("source_file", "")
            if url not in seen_urls:
                seen_urls.add(url)
                unique.append(doc)

        if unique:
            print(f"[WebScraper] Total web documents: {len(unique)}")
        else:
            print(f"[WebScraper] No web content found for topics: {topics}")

        return unique

    def format_web_docs(self, docs: List[Document]) -> str:
        """
        Formats web documents into a context string.
        When distinguish_sources=True, adds clear source labels.
        When False (default), blends naturally with course material formatting.
        """
        if not docs:
            return ""

        formatted = []
        for doc in docs:
            site = doc.metadata.get("source_site", "Web")
            title = doc.metadata.get("title", "")
            url = doc.metadata.get("source_file", "")

            if self.distinguish_sources:
                header = f"📚 External Reference ({site}): {title}\nURL: {url}"
            else:
                header = f"Supplementary Reference: {title} (Source: {site})"

            formatted.append(f"{header}\n{doc.page_content}")

        return "\n\n".join(formatted)
