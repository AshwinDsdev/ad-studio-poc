import asyncio
from services.scraper import scrape_url

async def main():
    for url in ["https://www.apple.com", "http://apple.com", "apple.com"]:
        data = await scrape_url(url)
        print(f"Scraped {url} -> hero_images: {data.get('brand_kit', {}).get('hero_images', [])}")

if __name__ == "__main__":
    asyncio.run(main())
