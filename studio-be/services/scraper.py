import httpx
import re
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _extract_brand_colors(soup: BeautifulSoup) -> list[str]:
    """Pull hex colors from inline styles and <meta theme-color>."""
    colors = []

    theme_color = soup.find("meta", attrs={"name": "theme-color"})
    if theme_color and theme_color.get("content"):
        colors.append(theme_color["content"].strip())

    # Scan style attributes for hex codes
    hex_pattern = re.compile(r'#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b')
    for tag in soup.find_all(style=True):
        found = hex_pattern.findall(tag["style"])
        for c in found:
            full = f"#{c}" if not c.startswith('#') else c
            if full not in colors:
                colors.append(f"#{c}")

    # Deduplicate, skip pure white/black noise
    noise = {"#ffffff", "#FFFFFF", "#000000", "#000", "#fff", "#FFF"}
    colors = [c for c in colors if c not in noise]
    return colors[:3]


def _extract_logo(soup: BeautifulSoup, base_url: str) -> str:
    """Find the most likely logo URL from common patterns."""
    # 1. <link rel="icon" / apple-touch-icon>
    for rel in ["apple-touch-icon", "shortcut icon", "icon"]:
        tag = soup.find("link", rel=lambda r: r and rel in r)
        if tag and tag.get("href"):
            return urljoin(base_url, tag["href"])

    # 2. <img> whose src/alt/class contains 'logo'
    for img in soup.find_all("img"):
        src = img.get("src", "")
        alt = img.get("alt", "").lower()
        cls = " ".join(img.get("class", [])).lower()
        if "logo" in src.lower() or "logo" in alt or "logo" in cls:
            return urljoin(base_url, src)

    # 3. OG image as fallback
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return urljoin(base_url, og["content"])

    return ""


def _extract_hero_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Return up to 3 prominent product/hero image URLs."""
    images = []

    # 1. Try OG image
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        images.append(urljoin(base_url, og["content"]))

    # 2. Try Twitter image
    tw = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
    if tw and tw.get("content"):
        images.append(urljoin(base_url, tw["content"]))

    # 3. Find large <img> tags by size attributes or class hints (including lazy-loaded data-src)
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        if not src or src.startswith("data:"):
            # try to parse srcset if src is a data URI
            srcset = img.get("srcset") or img.get("data-srcset") or ""
            if srcset:
                src = srcset.split(",")[0].split(" ")[0]
            else:
                continue

        full = urljoin(base_url, src.strip())
        if full in images:
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
        is_hero = (
            width >= 400
            or height >= 300
            or any(k in cls for k in ["hero", "banner", "feature", "product", "main"])
        )
        if is_hero or not images: # If we haven't found any images yet, just grab whatever looks like an image
            images.append(full)
            
        if len(images) >= 3:
            break

    # 4. Filter duplicates while preserving order
    unique_images = []
    for img in images:
        if img not in unique_images:
            unique_images.append(img)

    return unique_images[:3]


async def scrape_url(url: str) -> dict:
    """
    Scrapes the target URL and returns structured content:
    {
        "text": str,          # clean page text, max 10 000 chars
        "brand_kit": {
            "logo_url": str,
            "primary_color": str,
            "secondary_color": str,
            "hero_images": [str, ...]
        }
    }
    """
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            response = await client.get(url, headers=headers)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        # --- text ---
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.extract()
        text = soup.get_text(separator=" ", strip=True)[:10000]

        # --- brand kit ---
        colors = _extract_brand_colors(soup)
        primary_color = colors[0] if colors else "#5e6ad2"
        secondary_color = colors[1] if len(colors) > 1 else "#FFFFFF"
        logo_url = _extract_logo(soup, base_url)
        hero_images = _extract_hero_images(soup, base_url)

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
        logger.error(f"Error scraping {url}: {e}")
        return {
            "text": f"Failed to extract content from {url}. Ensure it is a valid, accessible website.",
            "brand_kit": {
                "logo_url": "",
                "primary_color": "#5e6ad2",
                "secondary_color": "#FFFFFF",
                "hero_images": [],
            },
        }
