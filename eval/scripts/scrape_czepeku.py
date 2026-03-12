# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright", "playwright-stealth", "Pillow", "tqdm"]
# ///
"""Scrape Czepeku website for map/scene images and metadata.

Standalone evaluation data collection script. Uses Playwright with stealth
patches to handle JS-rendered Next.js pages. No authentication required —
Czepeku hosts low-res preview images publicly.

Usage:
    # First time: install browser
    playwright install chromium

    # Scrape everything (maps + scenes, fantasy + sci-fi)
    uv run eval/scripts/scrape_czepeku.py

    # Dry run — discover items without downloading
    uv run eval/scripts/scrape_czepeku.py --dry-run

    # Scrape only fantasy maps, limit to 5 items
    uv run eval/scripts/scrape_czepeku.py \\
        --genre fantasy --content-type maps --max-items 5

    # Debug with visible browser
    uv run eval/scripts/scrape_czepeku.py --no-headless --max-items 2
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import random
import re
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

logger = logging.getLogger("scrape_czepeku")

BASE_URL = "https://www.czepeku.com"
CDN_BASE = "https://content.encounterkit.com"

# Navigation slugs that appear as links but aren't actual maps/scenes
NAV_SLUGS = {"themes", "series", "search", "tokens", "about"}

# Listing pages to scrape: (genre, content_type, path)
LISTING_PAGES = [
    ("fantasy", "maps", "/fantasy/maps"),
    ("fantasy", "scenes", "/fantasy/scenes"),
    ("scifi", "maps", "/scifi/maps"),
    ("scifi", "scenes", "/scifi/scenes"),
]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CzepekuRecord:
    """Metadata for a single Czepeku map/scene variant image."""

    name: str
    variant_name: str
    slug: str
    variant_slug: str
    variant_index: int
    content_type_label: str  # "map" or "scene"
    genre: str  # "fantasy" or "scifi"
    description: str
    image_url: str
    local_path: str | None = None
    page_url: str = ""
    related_url: str = ""  # "" if no cross-link
    tags: list[str] = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    original_width: int | None = None  # Full-res dimensions from metadata
    original_height: int | None = None
    tile_size: int | None = None  # Grid tile size in pixels
    gridded_image_key: str = ""  # CDN key for gridded version (not publicly accessible)
    optimized_image_key: str = ""  # CDN key for optimized version (not publicly accessible)
    perspective: str = ""  # "MAP" or "SCENE" from metadata
    patreon_url: str = ""
    download_error: str | None = None
    scraped_at: str = ""


@dataclass
class DiscoveredItem:
    """An item found on a listing page."""

    slug: str
    name: str
    genre: str
    content_type: str  # "maps" or "scenes"
    url: str  # Full URL to the detail page


@dataclass
class CrawlState:
    """Tracks crawl progress for resumability."""

    completed_urls: set[str] = field(default_factory=set)
    failed_urls: dict[str, str] = field(default_factory=dict)
    consecutive_errors: int = 0

    def mark_completed(self, url: str) -> None:
        self.completed_urls.add(url)
        self.consecutive_errors = 0
        self.failed_urls.pop(url, None)

    def mark_failed(self, url: str, reason: str) -> None:
        self.failed_urls[url] = reason
        self.consecutive_errors += 1

    def is_completed(self, url: str) -> bool:
        return url in self.completed_urls

    def save(self, path: Path) -> None:
        data = {
            "completed_urls": sorted(self.completed_urls),
            "failed_urls": self.failed_urls,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> CrawlState:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        return cls(
            completed_urls=set(data.get("completed_urls", [])),
            failed_urls=data.get("failed_urls", {}),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def url_hash(url: str) -> str:
    """Return first 12 chars of SHA-256 hex digest of a URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def safe_filename(url: str) -> str:
    """Extract filename from URL and make filesystem-safe with hash prefix."""
    parsed = urlparse(url)
    raw_name = Path(parsed.path).name or "image"
    safe = re.sub(r"[^\w.\-]", "_", raw_name)
    return f"{url_hash(url)}_{safe}"


def derive_extension(url: str, content_type: str = "") -> str:
    """Derive file extension from URL path or Content-Type header."""
    # Try URL first
    parsed = urlparse(url)
    path = parsed.path
    if "." in Path(path).name:
        ext = Path(path).suffix.lower()
        if ext in {".webp", ".jpg", ".jpeg", ".png", ".gif", ".avif"}:
            return ext

    # Fall back to Content-Type
    ct_map = {
        "image/webp": ".webp",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/avif": ".avif",
    }
    for ct_prefix, ext in ct_map.items():
        if content_type.startswith(ct_prefix):
            return ext

    return ".webp"  # Default for Czepeku CDN


def _strip_cdn_proxy(url: str) -> str:
    """Strip the Cloudflare cdn-cgi/image proxy wrapper from a URL.

    Input:  https://content.encounterkit.com/cdn-cgi/image/width=1920,.../https://content.encounterkit.com/map/preview/abc.webp
    Output: https://content.encounterkit.com/map/preview/abc.webp
    """
    marker = "/cdn-cgi/image/"
    if marker in url:
        # The actual URL follows the last "/"+ "http" pattern after the transform params
        idx = url.find(marker)
        rest = url[idx + len(marker) :]
        # Find where the inner URL starts (after the transform params separated by /)
        inner_start = rest.find("/http")
        if inner_start >= 0:
            return rest[inner_start + 1 :]
    return url


def build_preview_url(image_id: str) -> str:
    """Build a direct CDN preview URL from an image ID.

    Uses the direct URL (not the cdn-cgi proxy) to avoid CORS issues
    when downloading via browser fetch.
    """
    return f"{CDN_BASE}/map/preview/{image_id}.webp"


def setup_logging(output_dir: Path) -> None:
    """Configure logging to both console and file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "scrape.log"

    formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def check_chromium_installed() -> bool:
    """Check if Playwright's chromium browser is installed."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Browser management
# ---------------------------------------------------------------------------


class BrowserManager:
    """Manages Playwright browser lifecycle with stealth."""

    def __init__(
        self,
        headless: bool = True,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        self.headless = headless
        self.user_agent = user_agent
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def start(self):
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth

        stealth = Stealth()
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1920, "height": 1080},
            java_script_enabled=True,
        )

        # Apply stealth to context so all pages inherit it
        stealth.apply_stealth_sync(self._context)

        self._page = self._context.new_page()
        return self

    @property
    def page(self):
        return self._page

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


def scroll_to_bottom(page, pause: float = 0.5) -> None:
    """Scroll page incrementally to trigger lazy-loaded content."""
    prev_height = 0
    for _ in range(50):  # safety limit
        current_height = page.evaluate("document.body.scrollHeight")
        if current_height == prev_height:
            break
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        time.sleep(pause)
        prev_height = current_height
    page.evaluate("window.scrollTo(0, 0)")


def detect_cloudflare_challenge(page) -> bool:
    """Check if the page is showing a Cloudflare challenge."""
    indicators = [
        "Verify you are human",
        "Just a moment",
        "Checking your browser",
        "cf-challenge",
        "Enable JavaScript and cookies to continue",
    ]
    content = page.content()
    return any(indicator.lower() in content.lower() for indicator in indicators)


def extract_detail_page_data(page) -> dict:
    """Extract all map/scene data from a Czepeku detail page via DOM.

    Returns a dict with: title, description, variants (list of dicts with
    variant_name, variant_slug, image_url), tags, related_url.
    """
    return page.evaluate(
        """() => {
        // Title from h1
        const h1 = document.querySelector('h1');
        const title = h1 ? h1.textContent.trim() : '';

        // Description - look in .prose container first, then fall back
        let description = '';
        const proseP = document.querySelector('.prose p');
        if (proseP) {
            description = proseP.textContent.trim();
        }
        if (!description) {
            // Fallback: look for .prose container with any content
            const proseDiv = document.querySelector('.prose');
            if (proseDiv) {
                description = proseDiv.textContent.trim();
            }
            // No further fallback — if no .prose exists, this map has no description
        }

        // Variant images - extract from img alt text containing "variant"
        const imgs = document.querySelectorAll('img[alt*="variant"]');
        const variants = [];
        const seenSlugs = new Set();
        for (let i = 0; i < imgs.length; i++) {
            const img = imgs[i];
            const alt = img.alt || '';
            const src = img.src || '';

            // Extract variant name from alt text patterns:
            //   "Map Name map, Variant Name variant"
            //   "Map Name map, Variant Name variant thumbnail"
            const match = alt.match(/,\\s*(.+?)\\s*variant/i);
            const variantName = match ? match[1].trim() : 'Variant ' + i;
            const variantSlug = variantName.toLowerCase()
                .replace(/[^a-z0-9]+/g, '-')
                .replace(/^-|-$/g, '');

            if (seenSlugs.has(variantSlug)) continue;
            seenSlugs.add(variantSlug);

            variants.push({
                variantName,
                variantSlug,
                src,
                index: i,
            });
        }

        // Tags from search links
        const tagLinks = document.querySelectorAll('a[href*="/search/"]');
        const tags = [];
        for (const t of tagLinks) {
            let text = t.textContent.trim();
            // Clean "Search for more X maps" -> "X"
            const tagMatch = text.match(/Search for more (.+?) (?:maps|scenes)/i);
            if (tagMatch) {
                tags.push(tagMatch[1].toLowerCase());
            } else if (text.length > 0 && text.length < 50) {
                tags.push(text.toLowerCase());
            }
        }

        // Related scene/map link
        let relatedUrl = '';
        const allLinks = document.querySelectorAll('a');
        for (const link of allLinks) {
            const text = link.textContent.trim().toLowerCase();
            if (text.includes('view the scene') || text.includes('view the map')) {
                relatedUrl = link.getAttribute('href') || '';
                break;
            }
        }

        return {title, description, variants, tags, relatedUrl};
    }"""
    )


# ---------------------------------------------------------------------------
# Image download
# ---------------------------------------------------------------------------


def download_image(
    page,
    image_url: str,
    output_path: Path,
) -> tuple[int | None, int | None, str]:
    """Download an image through the browser context.

    Returns (width, height, content_type).
    """
    response_data = page.evaluate(
        """async (url) => {
        try {
            const resp = await fetch(url, { signal: AbortSignal.timeout(30000) });
            if (!resp.ok) {
                return { error: `HTTP ${resp.status}`, data: null, contentType: '' };
            }
            const contentType = resp.headers.get('content-type') || '';
            const buffer = await resp.arrayBuffer();
            const bytes = Array.from(new Uint8Array(buffer));
            return { error: null, data: bytes, contentType };
        } catch (e) {
            return { error: e.message, data: null, contentType: '' };
        }
    }""",
        image_url,
    )

    if response_data.get("error"):
        raise RuntimeError(f"Download failed: {response_data['error']}")

    raw_bytes = bytes(response_data["data"])
    content_type = response_data.get("contentType", "")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(raw_bytes)

    width, height = None, None
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            width, height = img.size
    except Exception:
        pass

    return width, height, content_type


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


class CzepekuCrawler:
    """Crawl Czepeku website for maps and scenes."""

    def __init__(
        self,
        browser: BrowserManager,
        output_dir: Path,
        state: CrawlState,
        *,
        delay: float = 2.0,
        max_items: int | None = None,
        max_errors: int = 5,
        genre_filter: str = "all",
        content_type_filter: str = "all",
        dry_run: bool = False,
    ):
        self.browser = browser
        self.output_dir = output_dir
        self.state = state
        self.delay = delay
        self.max_items = max_items
        self.max_errors = max_errors
        self.genre_filter = genre_filter
        self.content_type_filter = content_type_filter
        self.dry_run = dry_run
        self.metadata_path = output_dir / "metadata.jsonl"
        self.progress_path = output_dir / "progress.json"

    def discover_items(self) -> list[DiscoveredItem]:
        """Discover all maps/scenes from listing pages."""
        all_items = []

        pages_to_scrape = [
            (genre, ct, path)
            for genre, ct, path in LISTING_PAGES
            if (self.genre_filter == "all" or self.genre_filter == genre)
            and (self.content_type_filter == "all" or self.content_type_filter == ct)
        ]

        for genre, content_type, path in pages_to_scrape:
            page = self.browser.page
            url = f"{BASE_URL}{path}"
            logger.info("Discovering %s %s from %s", genre, content_type, url)

            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(2)

            if detect_cloudflare_challenge(page):
                logger.warning("Cloudflare challenge on %s — try --no-headless", url)
                continue

            # Scroll to ensure all items are loaded
            scroll_to_bottom(page, pause=0.3)
            time.sleep(1)

            # Extract item links from the listing page
            genre_re = genre.replace("-", "\\-")
            items_data = page.evaluate(
                """(params) => {
                const results = [];
                const {genrePath, ctPath, genreRe} = params;
                const links = document.querySelectorAll(
                    `a[href*="/${genrePath}/${ctPath}/"]`
                );
                const seen = new Set();
                const pattern = new RegExp(
                    `^\\/${genreRe}\\/${ctPath}\\/([a-z0-9][a-z0-9\\-]*[a-z0-9])$`
                );
                for (const link of links) {
                    const href = link.getAttribute('href') || '';
                    const match = href.match(pattern);
                    if (match && !seen.has(match[1])) {
                        seen.add(match[1]);
                        const name = link.textContent.trim();
                        results.push({
                            slug: match[1],
                            name: name,
                            href: href,
                        });
                    }
                }
                return results;
            }""",
                {"genrePath": genre, "ctPath": content_type, "genreRe": genre_re},
            )

            for item in items_data:
                if item["slug"] in NAV_SLUGS:
                    continue
                all_items.append(
                    DiscoveredItem(
                        slug=item["slug"],
                        name=item["name"],
                        genre=genre,
                        content_type=content_type,
                        url=f"{BASE_URL}{item['href']}",
                    )
                )

            logger.info(
                "Found %d %s %s",
                len(items_data),
                genre,
                content_type,
            )
            self._rate_limit_delay()

        logger.info("Total items discovered: %d", len(all_items))
        return all_items

    def scrape_detail_page(self, item: DiscoveredItem) -> list[CzepekuRecord]:
        """Scrape a detail page and extract all variant metadata via DOM."""
        page = self.browser.page
        logger.info("Scraping: %s (%s %s)", item.name, item.genre, item.content_type)

        page.goto(item.url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        if detect_cloudflare_challenge(page):
            logger.warning("Cloudflare challenge: %s", item.url)
            return []

        # Scroll to load all variant thumbnails
        scroll_to_bottom(page, pause=0.3)
        time.sleep(1)

        data = extract_detail_page_data(page)
        now = datetime.now(UTC).isoformat()

        name = data.get("title") or item.name
        description = data.get("description", "")
        tags = data.get("tags", [])

        # Build related URL
        related_url = ""
        raw_related = data.get("relatedUrl", "")
        if raw_related:
            if raw_related.startswith("/"):
                related_url = f"{BASE_URL}{raw_related}"
            else:
                related_url = raw_related

        records = []
        for v in data.get("variants", []):
            image_url = v["src"]
            # Strip CDN proxy wrapper to get direct downloadable URL
            image_url = _strip_cdn_proxy(image_url)
            # Handle Next.js image proxy URLs
            if "/_next/image" in image_url and "url=" in image_url:
                query = parse_qs(urlparse(image_url).query)
                if "url" in query:
                    image_url = _strip_cdn_proxy(query["url"][0])

            record = CzepekuRecord(
                name=name,
                variant_name=v["variantName"],
                slug=item.slug,
                variant_slug=v["variantSlug"],
                variant_index=v["index"],
                content_type_label="map" if item.content_type == "maps" else "scene",
                genre=item.genre,
                description=description,
                image_url=image_url,
                page_url=f"{item.url}/{v['variantSlug']}",
                related_url=related_url,
                tags=tags,
                scraped_at=now,
            )
            records.append(record)

        logger.info("Extracted %d variants for %s", len(records), name)
        return records

    def download_variant_images(self, records: list[CzepekuRecord]) -> None:
        """Download images for all variant records."""
        page = self.browser.page

        for record in records:
            rel_dir = (
                Path("images") / record.genre / (record.content_type_label + "s") / record.slug
            )
            # Use variant_slug as filename, derive extension from URL
            ext = derive_extension(record.image_url)
            rel_path = rel_dir / f"{record.variant_slug}{ext}"
            abs_path = self.output_dir / rel_path

            if abs_path.exists():
                try:
                    with Image.open(abs_path) as img:
                        record.width, record.height = img.size
                except Exception:
                    pass
                record.local_path = str(rel_path)
                logger.debug("Already exists: %s", rel_path)
                continue

            try:
                w, h, ct = download_image(page, record.image_url, abs_path)
                record.width = w
                record.height = h
                record.local_path = str(rel_path)

                # If the actual content type differs, rename
                actual_ext = derive_extension(record.image_url, ct)
                if actual_ext != ext:
                    new_path = abs_path.with_suffix(actual_ext)
                    abs_path.rename(new_path)
                    rel_path = rel_dir / f"{record.variant_slug}{actual_ext}"
                    record.local_path = str(rel_path)

                logger.debug("Downloaded: %s", rel_path)
            except Exception as e:
                logger.warning("Failed to download %s: %s", record.image_url, e)
                record.download_error = str(e)
                record.local_path = None

    def crawl(self) -> int:
        """Run the full crawl. Returns total images scraped."""
        items = self.discover_items()

        if not items:
            logger.error("No items found. Check network and try --no-headless.")
            return 0

        if self.dry_run:
            # Count by genre and content type
            from collections import Counter

            counts = Counter((i.genre, i.content_type) for i in items)
            for (genre, ct), count in sorted(counts.items()):
                logger.info("[DRY RUN] %s %s: %d items", genre, ct, count)
            logger.info("[DRY RUN] Total: %d items", len(items))
            return 0

        # Apply max-items limit
        if self.max_items:
            items = items[: self.max_items]
            logger.info("Limited to %d items", len(items))

        total_images = 0
        items_crawled = 0

        from tqdm import tqdm

        for item in tqdm(items, desc="Scraping", unit="item"):
            # Check resumability key (genre/content_type/slug)
            resume_key = f"{item.genre}/{item.content_type}/{item.slug}"

            if self.state.is_completed(resume_key):
                logger.debug("Skipping completed: %s", resume_key)
                continue

            if self.state.consecutive_errors >= self.max_errors:
                logger.error(
                    "Aborting: %d consecutive errors (max: %d)",
                    self.state.consecutive_errors,
                    self.max_errors,
                )
                return total_images

            try:
                records = self.scrape_detail_page(item)
                if not records:
                    self.state.mark_failed(resume_key, "no_variants_found")
                    self.state.save(self.progress_path)
                    self._rate_limit_delay()
                    continue

                self.download_variant_images(records)
                self._append_metadata(records)

                self.state.mark_completed(resume_key)
                self.state.save(self.progress_path)

                total_images += len(records)
                items_crawled += 1
                logger.info(
                    "Completed %s: %d variants (%d/%d items)",
                    item.name,
                    len(records),
                    items_crawled,
                    len(items),
                )
            except Exception as e:
                logger.error("Error scraping %s: %s", item.slug, e)
                self.state.mark_failed(resume_key, str(e))
                self.state.save(self.progress_path)

            self._rate_limit_delay()

        return total_images

    def _append_metadata(self, records: list[CzepekuRecord]) -> None:
        """Append records to metadata JSONL file."""
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.metadata_path, "a", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def _rate_limit_delay(self) -> None:
        """Sleep between page loads with jitter."""
        jitter = random.uniform(0, 1.0)
        time.sleep(self.delay + jitter)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Czepeku for map/scene images and metadata (evaluation data).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("eval/data/czepeku"),
        help="Output directory (default: eval/data/czepeku)",
    )
    parser.add_argument(
        "--content-type",
        choices=["maps", "scenes", "all"],
        default="all",
        help="Content type to scrape (default: all)",
    )
    parser.add_argument(
        "--genre",
        choices=["fantasy", "scifi", "all"],
        default="all",
        help="Genre to scrape (default: all)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay between page loads in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        help="Maximum number of maps/scenes to scrape",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=5,
        help="Abort after N consecutive errors (default: 5)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Run browser in headless mode (default: headful)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser in headful mode (default)",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume from previous progress (default: --resume)",
    )
    parser.add_argument(
        "--user-agent",
        type=str,
        default=DEFAULT_USER_AGENT,
        help="Browser user-agent string",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover items and print counts without downloading",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    headless = args.headless and not args.no_headless

    # Check chromium
    if not check_chromium_installed():
        print(
            "Chromium is not installed for Playwright.\n"
            "Run: playwright install chromium\n"
            "On Linux you may also need: playwright install --with-deps chromium",
            file=sys.stderr,
        )
        sys.exit(1)

    # Setup
    output_dir = args.output_dir.resolve()
    setup_logging(output_dir)
    logger.info("Starting Czepeku scraper (genre: %s, type: %s)", args.genre, args.content_type)

    # Load crawl state
    progress_path = output_dir / "progress.json"
    state = CrawlState.load(progress_path) if args.resume else CrawlState()
    if args.resume and state.completed_urls:
        logger.info("Resuming: %d items already completed", len(state.completed_urls))

    # Signal handler for graceful shutdown
    shutdown_requested = False

    def signal_handler(_signum, _frame):
        nonlocal shutdown_requested
        if shutdown_requested:
            logger.warning("Force shutdown")
            sys.exit(1)
        shutdown_requested = True
        logger.info("Shutdown requested — saving progress...")
        state.save(progress_path)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Launch browser
    browser = BrowserManager(headless=headless, user_agent=args.user_agent)
    browser.start()

    try:
        crawler = CzepekuCrawler(
            browser=browser,
            output_dir=output_dir,
            state=state,
            delay=args.delay,
            max_items=args.max_items,
            max_errors=args.max_errors,
            genre_filter=args.genre,
            content_type_filter=args.content_type,
            dry_run=args.dry_run,
        )

        total = crawler.crawl()
        logger.info("Done. Total variant images scraped: %d", total)

    finally:
        browser.close()
        state.save(progress_path)


if __name__ == "__main__":
    main()
