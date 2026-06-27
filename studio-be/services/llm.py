import os
import json
import logging
import httpx
from models import AdStoryboardSchema
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def generate_storyboard(scraped_data: dict) -> dict:
    """
    Uses Groq or OpenRouter to generate 3 distinct, scored ad variants
    from scraped site content and extracted brand kit.
    """
    api_key = os.getenv("GROQ_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY or OPENROUTER_API_KEY is not set in .env")

    # Determine base URL and model based on which key is available
    if os.getenv("GROQ_API_KEY"):
        base_url = "https://api.groq.com/openai/v1/chat/completions"
        model = "llama-3.3-70b-versatile"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    else:
        base_url = "https://openrouter.ai/api/v1/chat/completions"
        model = "meta-llama/llama-3.3-70b-instruct:free"
        headers = {
            "Authorization": f"Bearer {api_key}", 
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Ad Studio"
        }

    text = scraped_data.get("text", "")
    brand_kit = scraped_data.get("brand_kit", {})
    hero_images = brand_kit.get("hero_images", [])
    primary_color = brand_kit.get("primary_color", "#5e6ad2")

    schema_json = AdStoryboardSchema.schema_json(indent=2)

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

IMPORTANT: You MUST respond in pure JSON format that precisely matches this JSON Schema:
{schema_json}

Website Content:
{text[:8000]}
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that ALWAYS outputs valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7
    }

    response = httpx.post(base_url, headers=headers, json=payload, timeout=60.0)
    
    if response.status_code != 200:
        raise ValueError(f"LLM API Error: {response.text}")
        
    response_data = response.json()
    content = response_data["choices"][0]["message"]["content"]

    try:
        return json.loads(content)
    except Exception:
        cleaned = content.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
