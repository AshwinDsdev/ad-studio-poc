import os
import sys
import uuid
import asyncio
import httpx
import re
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AUDIO_CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "audio_cache"))
try:
    os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
    test_file = os.path.join(AUDIO_CACHE_DIR, f".test_write_{os.getpid()}")
    with open(test_file, "w") as f:
        f.write("")
    os.remove(test_file)
except Exception:
    AUDIO_CACHE_DIR = "/tmp/audio_cache"
    os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")


# ---------------------------------------------------------------------------
# Brand color extraction
# ---------------------------------------------------------------------------

def _extract_brand_colors(soup: BeautifulSoup) -> list[str]:
    colors = []
    theme_color = soup.find("meta", attrs={"name": "theme-color"})
    if theme_color and theme_color.get("content"):
        colors.append(theme_color["content"].strip())
    hex_pattern = re.compile(r'#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b')
    for tag in soup.find_all(style=True):
        for c in hex_pattern.findall(tag["style"]):
            full = f"#{c}"
            if full not in colors:
                colors.append(full)
    noise = {"#ffffff", "#FFFFFF", "#000000", "#000", "#fff", "#FFF"}
    return [c for c in colors if c not in noise][:3]


def _extract_logo(soup: BeautifulSoup, base_url: str) -> str:
    for rel in ["apple-touch-icon", "shortcut icon", "icon"]:
        tag = soup.find("link", rel=lambda r: r and rel in r)
        if tag and tag.get("href"):
            return urljoin(base_url, tag["href"])
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "")
        alt = img.get("alt", "").lower()
        cls = " ".join(img.get("class", [])).lower()
        if "logo" in src.lower() or "logo" in alt or "logo" in cls:
            return urljoin(base_url, src)
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return urljoin(base_url, og["content"])
    return ""


# ---------------------------------------------------------------------------
# Image URL extraction from parsed HTML
# ---------------------------------------------------------------------------

_LAZY_ATTRS = ["src", "data-src", "data-lazy-src", "data-lazy", "data-original", "data-image"]
_SKIP_HINTS = ["icon", "logo", "pixel", "tracker", "1x1", "blank", "spacer", "svg"]


def _resolve_src(raw: str, base_url: str) -> str:
    if not raw:
        return ""
    first = raw.strip().split(",")[0].strip().split()[0]
    return urljoin(base_url, first)


def _extract_hero_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    seen: set[str] = set()
    images: list[str] = []

    def _add(url: str):
        url = url.strip()
        if not url or url.startswith("data:") or url in seen:
            return
        if any(s in url.lower() for s in _SKIP_HINTS):
            return
        seen.add(url)
        images.append(url)

    # 1. OG / Twitter card
    for attr_name, attr_val in [
        ("property", "og:image"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
    ]:
        tag = soup.find("meta", attrs={attr_name: attr_val})
        if tag and tag.get("content"):
            _add(urljoin(base_url, tag["content"]))

    # 2. All <img> tags including lazy-loaded ones
    for img in soup.find_all("img"):
        candidates = [_resolve_src(img.get(a, ""), base_url) for a in _LAZY_ATTRS if img.get(a)]
        srcset = img.get("srcset", "")
        if srcset:
            candidates.append(_resolve_src(srcset, base_url))

        for full in candidates:
            if not full or full in seen or full.startswith("data:"):
                continue
            if any(s in full.lower() for s in _SKIP_HINTS):
                continue
            try:
                width = int(str(img.get("width", 0)).replace("px", "").replace("%", "").strip() or 0)
            except ValueError:
                width = 0
            try:
                height = int(str(img.get("height", 0)).replace("px", "").replace("%", "").strip() or 0)
            except ValueError:
                height = 0
            cls = " ".join(img.get("class", [])).lower()
            alt = img.get("alt", "").lower()
            is_hero = (
                width >= 300 or height >= 200
                or any(k in cls for k in ["hero", "banner", "feature", "product", "main", "cover", "carousel", "slide", "thumb"])
                or any(k in alt for k in ["product", "hero", "banner", "main"])
            )
            if is_hero:
                _add(full)
                if len(images) >= 5:
                    break
        if len(images) >= 5:
            break

    # 3. Last resort — any <img> URL
    if not images:
        for img in soup.find_all("img"):
            for attr in _LAZY_ATTRS:
                val = img.get(attr, "")
                if val:
                    full = _resolve_src(val, base_url)
                    if full and not full.startswith("data:") and full not in seen:
                        _add(full)
                        break
            if len(images) >= 3:
                break

    logger.info("Hero images extracted from HTML (%s): %s", len(images), images)
    return images[:5]


# ---------------------------------------------------------------------------
# Playwright — runs in a background thread with its own event loop
# ---------------------------------------------------------------------------

def _playwright_sync(url: str) -> tuple[str, str]:
    """
    Synchronous Playwright wrapper that MUST be called via asyncio.to_thread.

    Root cause of the Windows NotImplementedError:
      uvicorn uses WindowsSelectorEventLoop, which cannot spawn subprocesses.
      Playwright needs subprocess_exec to launch Chromium → crash.

    Fix: run the entire Playwright session inside a brand-new thread.
    The thread creates a ProactorEventLoop (Windows) or default loop (Linux/mac)
    which CAN spawn subprocesses, completely isolated from uvicorn's loop.
    """
    async def _inner() -> tuple[str, str]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
            return "", ""

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900},
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                )
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = await context.new_page()
                await page.route("**/*.{woff,woff2,ttf,otf}", lambda r: r.abort())

                logger.info("Playwright navigating to %s ...", url)
                await page.goto(url, wait_until="networkidle", timeout=25000)

                # Scroll to trigger lazy-loaded images
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await page.wait_for_timeout(1500)
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(500)

                # Take viewport screenshot — works regardless of bot-protection/lazy-loading
                screenshot_filename = f"screenshot_{uuid.uuid4().hex}.jpg"
                screenshot_path = os.path.join(AUDIO_CACHE_DIR, screenshot_filename)
                await page.screenshot(path=screenshot_path, full_page=False, type="jpeg", quality=90)
                screenshot_url = f"{BACKEND_BASE_URL}/api/audio/{screenshot_filename}"
                logger.info("Playwright screenshot saved: %s", screenshot_url)

                html = await page.content()
                logger.info("Playwright rendered HTML: %d bytes", len(html))

                await browser.close()
                return screenshot_url, html

        except Exception as e:
            logger.error("Playwright inner error for %s: %s", url, e)
            return "", ""

    # Create a fresh event loop in this thread
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()

    try:
        return loop.run_until_complete(_inner())
    finally:
        loop.close()


async def _run_playwright(url: str) -> tuple[str, str]:
    """Async entry point — delegates to _playwright_sync via a background thread."""
    return await asyncio.to_thread(_playwright_sync, url)


async def _screenshot_via_api(url: str) -> str:
    """
    Serverless fallback: fetch a screenshot from a free public API.
    No API key required. Used on Vercel / any env without Playwright.

    Pipeline:
      1. thum.io  — free, no key, returns JPEG directly
      2. microlink.io — free tier, returns JSON with screenshot URL
    """
    import urllib.parse
    encoded = urllib.parse.quote(url, safe="")

    apis = [
        # thum.io: returns raw JPEG, completely free, no signup
        f"https://image.thum.io/get/width/1280/crop/900/noanimate/{url}",
        # microlink: returns JSON {data: {screenshot: {url: ...}}}
        f"https://api.microlink.io?url={encoded}&screenshot=true&meta=false&embed=screenshot.url",
    ]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
        # --- 1. thum.io ---
        try:
            logger.info("Trying thum.io screenshot for %s", url)
            r = await client.get(apis[0])
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                filename = f"screenshot_{uuid.uuid4().hex}.jpg"
                filepath = os.path.join(AUDIO_CACHE_DIR, filename)
                with open(filepath, "wb") as f:
                    f.write(r.content)
                screenshot_url = f"{BACKEND_BASE_URL}/api/audio/{filename}"
                logger.info("thum.io screenshot saved (%dKB): %s", len(r.content) // 1024, screenshot_url)
                return screenshot_url
            else:
                logger.warning("thum.io returned %s / content-type=%s", r.status_code, r.headers.get("content-type"))
        except Exception as e:
            logger.warning("thum.io failed: %s", e)

        # --- 2. microlink.io ---
        try:
            logger.info("Trying microlink.io screenshot for %s", url)
            r = await client.get(apis[1])
            if r.status_code == 200:
                data = r.json()
                img_url = (
                    data.get("data", {}).get("screenshot", {}).get("url", "")
                    or data.get("data", {}).get("image", {}).get("url", "")
                )
                if img_url:
                    # Download and re-serve via our backend
                    img_r = await client.get(img_url)
                    if img_r.status_code == 200:
                        filename = f"screenshot_{uuid.uuid4().hex}.jpg"
                        filepath = os.path.join(AUDIO_CACHE_DIR, filename)
                        with open(filepath, "wb") as f:
                            f.write(img_r.content)
                        screenshot_url = f"{BACKEND_BASE_URL}/api/audio/{filename}"
                        logger.info("microlink screenshot saved (%dKB): %s", len(img_r.content) // 1024, screenshot_url)
                        return screenshot_url
            logger.warning("microlink returned %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            logger.warning("microlink.io failed: %s", e)

    logger.error("All screenshot APIs failed for %s", url)
    return ""


# ---------------------------------------------------------------------------
# httpx fallback
# ---------------------------------------------------------------------------

async def _scrape_with_httpx(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


# ---------------------------------------------------------------------------
# Public scrape_url
# ---------------------------------------------------------------------------

async def scrape_url(url: str) -> dict:
    """
    Scrapes the target URL and returns structured content:
    {
        "text": str,
        "brand_kit": {
            "logo_url": str,
            "primary_color": str,
            "secondary_color": str,
            "hero_images": [str, ...]
        }
    }

    Strategy:
      1. Playwright (background thread with ProactorEventLoop) renders the page,
         takes a screenshot, and returns the full DOM HTML.
      2. httpx fallback if Playwright is unavailable.
    """
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    try:
        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        # --- Primary: Playwright in background thread ---
        screenshot_url, html = await _run_playwright(url)

        # --- Serverless fallback: free screenshot API (thum.io / microlink) ---
        if not screenshot_url:
            logger.warning("Playwright unavailable (serverless env?) — using screenshot API fallback.")
            screenshot_url = await _screenshot_via_api(url)

        # --- Last resort HTML: plain httpx ---
        if not html:
            logger.warning("Playwright failed — falling back to httpx.")
            try:
                html = await _scrape_with_httpx(url)
            except Exception as e:
                logger.error("httpx scrape also failed: %s", e)
                html = ""

        soup = BeautifulSoup(html, "html.parser") if html else BeautifulSoup("", "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.extract()
        text = soup.get_text(separator=" ", strip=True)[:10000]

        colors = _extract_brand_colors(soup)
        primary_color = colors[0] if colors else "#5e6ad2"
        secondary_color = colors[1] if len(colors) > 1 else "#FFFFFF"
        logo_url = _extract_logo(soup, base_url)
        html_images = _extract_hero_images(soup, base_url)

        # Screenshot is always first (guaranteed real site visual)
        hero_images: list[str] = []
        if screenshot_url:
            hero_images.append(screenshot_url)
        for img_url in html_images:
            if img_url not in hero_images:
                hero_images.append(img_url)
            if len(hero_images) >= 5:
                break

        logger.info(
            "Scrape complete for %s — %d hero image(s), screenshot=%s",
            url, len(hero_images), bool(screenshot_url),
        )

        return {
            "text": text,
            "brand_kit": {
                "logo_url": logo_url,
                "primary_color": primary_color,
                "secondary_color": secondary_color,
                "hero_images": hero_images,
            },
        }

    except Exception as e:
        logger.error("Error scraping %s: %s", url, e)
        return {
            "text": f"Failed to extract content from {url}.",
            "brand_kit": {
                "logo_url": "",
                "primary_color": "#5e6ad2",
                "secondary_color": "#FFFFFF",
                "hero_images": [],
            },
        }
