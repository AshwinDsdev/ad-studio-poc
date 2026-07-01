"""
Standalone test script for the scraper image extraction.
Run from the studio-be directory:

    python test_scraper.py
    python test_scraper.py https://some-other-url.com
"""
import asyncio
import sys
import os

# Make sure the services module is importable
sys.path.insert(0, os.path.dirname(__file__))

TEST_URL = sys.argv[1] if len(sys.argv) > 1 else "https://boodmo.com/"


async def test_playwright_screenshot():
    print("\n" + "="*60)
    print("STEP 1: Testing Playwright import")
    print("="*60)
    try:
        from playwright.async_api import async_playwright
        print("✅ Playwright imported OK")
    except ImportError as e:
        print(f"❌ Playwright import failed: {e}")
        print("   Run: pip install playwright && python -m playwright install chromium")
        return False

    print("\n" + "="*60)
    print("STEP 2: Launching Playwright Chromium")
    print("="*60)
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
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
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await context.new_page()
            print(f"✅ Browser launched OK")

            print(f"\n{'='*60}")
            print(f"STEP 3: Navigating to {TEST_URL}")
            print("="*60)
            response = await page.goto(TEST_URL, wait_until="networkidle", timeout=25000)
            print(f"✅ Page loaded — HTTP status: {response.status if response else 'unknown'}")

            # Scroll to trigger lazy loading
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await page.wait_for_timeout(1500)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(500)

            print(f"\n{'='*60}")
            print("STEP 4: Taking screenshot")
            print("="*60)
            screenshot_path = "test_screenshot.jpg"
            await page.screenshot(path=screenshot_path, full_page=False, type="jpeg", quality=90)
            size_kb = os.path.getsize(screenshot_path) // 1024
            print(f"✅ Screenshot saved to: {os.path.abspath(screenshot_path)} ({size_kb} KB)")

            print(f"\n{'='*60}")
            print("STEP 5: Inspecting rendered DOM for images")
            print("="*60)
            html = await page.content()
            print(f"   Rendered HTML size: {len(html):,} bytes")

            # Count img tags
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            all_imgs = soup.find_all("img")
            print(f"   <img> tags found: {len(all_imgs)}")

            # Print what each img has
            LAZY_ATTRS = ["src", "data-src", "data-lazy-src", "data-lazy", "data-original", "data-image"]
            found_urls = []
            for i, img in enumerate(all_imgs[:20]):
                for attr in LAZY_ATTRS:
                    val = img.get(attr, "")
                    if val and not val.startswith("data:"):
                        found_urls.append(val)
                        print(f"   img[{i}] {attr}={val[:80]}")
                        break

            # Check OG/Twitter
            print(f"\n{'='*60}")
            print("STEP 6: Checking meta/OG image tags")
            print("="*60)
            og = soup.find("meta", attrs={"property": "og:image"})
            tw = soup.find("meta", attrs={"name": "twitter:image"})
            print(f"   og:image  → {og['content'] if og and og.get('content') else '(not found)'}")
            print(f"   twitter:image → {tw['content'] if tw and tw.get('content') else '(not found)'}")

            await browser.close()

            print(f"\n{'='*60}")
            print("RESULT")
            print("="*60)
            if os.path.exists(screenshot_path) and size_kb > 5:
                print(f"✅ SUCCESS — Screenshot extracted: {screenshot_path} ({size_kb} KB)")
                print(f"   Open the file to verify it shows the actual site.")
                return True
            else:
                print(f"❌ FAILED — Screenshot too small or missing (got {size_kb} KB)")
                return False

    except Exception as e:
        import traceback
        print(f"❌ Playwright test failed: {e}")
        traceback.print_exc()
        return False


async def test_full_scraper():
    print(f"\n{'='*60}")
    print("BONUS: Running full scraper pipeline")
    print("="*60)
    try:
        from services.scraper import scrape_url
        result = await scrape_url(TEST_URL)
        brand_kit = result.get("brand_kit", {})
        hero_images = brand_kit.get("hero_images", [])
        text_preview = result.get("text", "")[:200]

        print(f"   Text preview: {text_preview!r}")
        print(f"   Primary color: {brand_kit.get('primary_color')}")
        print(f"   Logo URL: {brand_kit.get('logo_url')}")
        print(f"   Hero images ({len(hero_images)}):")
        for i, img in enumerate(hero_images):
            print(f"     [{i}] {img}")

        if hero_images:
            print(f"\n✅ SCRAPER SUCCESS — {len(hero_images)} hero image(s) found")
            return True
        else:
            print(f"\n❌ SCRAPER FAILED — No hero images returned")
            return False
    except Exception as e:
        import traceback
        print(f"❌ Scraper pipeline error: {e}")
        traceback.print_exc()
        return False


async def main():
    print(f"\n🔍 Scraper Image Extraction Test")
    print(f"   Target URL: {TEST_URL}")

    step1_ok = await test_playwright_screenshot()
    step2_ok = await test_full_scraper()

    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print("="*60)
    print(f"   Screenshot test : {'✅ PASS' if step1_ok else '❌ FAIL'}")
    print(f"   Full scraper    : {'✅ PASS' if step2_ok else '❌ FAIL'}")

    if step1_ok:
        print("\n🎉 Core screenshot works — the video will use real site visuals.")
    else:
        print("\n💥 Screenshot failed — check Playwright/Chromium installation above.")

    sys.exit(0 if (step1_ok and step2_ok) else 1)


if __name__ == "__main__":
    asyncio.run(main())
