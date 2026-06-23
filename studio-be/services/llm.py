import os
import json
import logging
from google import genai
from models import AdStoryboardSchema
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def generate_storyboard(scraped_data: dict) -> dict:
    """
    Uses Gemini 2.5 Flash to generate 3 distinct, scored ad variants
    from scraped site content and extracted brand kit.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in .env")

    client = genai.Client(api_key=api_key)

    text = scraped_data.get("text", "")
    brand_kit = scraped_data.get("brand_kit", {})
    hero_images = brand_kit.get("hero_images", [])
    primary_color = brand_kit.get("primary_color", "#5e6ad2")

    prompt = f"""
You are a world-class performance-marketing creative director specializing in high-converting video ads.

Analyze the website content below and produce exactly 3 DISTINCT video ad storyboards — each with a 
completely different creative angle and hook strategy. Diversity between variants is critical.

Required variant angles (use these labels exactly):
1. "Pain Point Hook" — Open by agitating the viewer's core problem/frustration
2. "Social Proof Hook" — Open with credibility signals (results, numbers, testimonials)  
3. "Dream Outcome Hook" — Open with the aspirational end-state the product delivers

For each variant, assign a Creative Score (0-100) based on:
- Hook strength (stops the scroll in 2 seconds): 40 pts
- CTA clarity and urgency: 30 pts
- Message-market fit given the brand: 30 pts

Rules:
- Each ad is 15-30 seconds total across 3-5 scenes
- Voiceover scripts: short, punchy, conversational — no corporate speak
- Visual image prompts: ultra-detailed, cinematic, describe lighting, mood, subject, style
- Scores MUST be different across variants (reflect genuine quality differences)
- The best variant should score 75-90; worst should score 55-70
- primary_color for this brand is: {primary_color}
- If hero images are available, reference them in scene 1 visual prompts: {', '.join(hero_images[:2]) if hero_images else 'none'}

Website Content:
{text[:8000]}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": AdStoryboardSchema,
            "temperature": 0.8,
        },
    )

    try:
        return json.loads(response.text)
    except Exception:
        cleaned = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
