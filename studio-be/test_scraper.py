import asyncio
from services.scraper import scrape_url

async def main():
    url = "https://www.apple.com"
    data = await scrape_url(url)
    print("Scraped Brand Kit:", data.get("brand_kit", {}))

if __name__ == "__main__":
    asyncio.run(main())
