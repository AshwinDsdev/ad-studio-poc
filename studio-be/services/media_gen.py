import os
import uuid
import asyncio
import logging
import urllib.parse
import httpx
import edge_tts

logger = logging.getLogger(__name__)

FAL_API_KEY = os.getenv("FAL_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")

AUDIO_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "audio_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)


def save_audio_file(file_bytes: bytes) -> str:
    """
    Saves audio bytes to the local audio_cache directory and returns
    the public URL for Creatomate to fetch.
    """
    filename = f"{uuid.uuid4().hex}.mp3"
    filepath = os.path.join(AUDIO_CACHE_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(file_bytes)
    return f"{BACKEND_BASE_URL}/api/audio/{filename}"



async def generate_voice(script: str) -> dict:
    """
    Generates voice audio using Microsoft Edge TTS and captures
    word-level timestamps from WordBoundary events.
    """
    voice = "en-US-JennyNeural"

    try:
        communicate = edge_tts.Communicate(script, voice, boundary="WordBoundary")
        words: list[dict] = []
        audio_chunks: list[bytes] = []

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start_sec = chunk["offset"] / 10_000_000
                duration_sec = chunk["duration"] / 10_000_000
                words.append({
                    "word": chunk["text"],
                    "start": round(start_sec, 3),
                    "duration": round(duration_sec, 3),
                })

        audio_bytes = b"".join(audio_chunks)
        if not audio_bytes:
            raise ValueError("Edge TTS returned no audio data")

        audio_url = save_audio_file(audio_bytes)
        return {"audio_url": audio_url, "words": words}

    except Exception as e:
        logger.error(f"Edge TTS voice generation failed: {e}")
        # Fallback: save without word boundaries
        try:
            communicate = edge_tts.Communicate(script, voice)
            temp_filename = f"temp_voice_{uuid.uuid4().hex}.mp3"
            await communicate.save(temp_filename)
            with open(temp_filename, "rb") as f:
                audio_bytes = f.read()
            os.remove(temp_filename)
            audio_url = save_audio_file(audio_bytes)
            return {"audio_url": audio_url, "words": []}
        except Exception as e2:
            logger.error(f"Edge TTS fallback also failed: {e2}")
            return {"audio_url": "", "words": []}


async def generate_image_fal(prompt: str) -> str:
    """Generate image via Fal.ai FLUX Schnell."""
    url = "https://fal.run/fal-ai/flux/schnell"
    headers = {
        "Authorization": f"Key {FAL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "num_images": 1,
        "image_size": "landscape_16_9",
        "enable_safety_checker": False,
    }

    async with httpx.AsyncClient(timeout=90.0, verify=False) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        images = data.get("images", [])
        if images and images[0].get("url"):
            return images[0]["url"]
        raise ValueError("Fal.ai returned no image URL")


async def generate_image_hf(prompt: str) -> str:
    """Generate image via Hugging Face Serverless Inference API."""
    url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"inputs": prompt}

    async with httpx.AsyncClient(timeout=45.0, verify=False) as client:
        response = await client.post(url, json=payload, headers=headers)
        
        # Check if the model is loading and wait if necessary
        if "application/json" in response.headers.get("content-type", ""):
            try:
                res_data = response.json()
                if "error" in res_data and "loading" in res_data["error"].lower():
                    wait_time = min(float(res_data.get("estimated_time", 10.0)), 15.0)
                    logger.info(f"Hugging Face model is loading. Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                    response = await client.post(url, json=payload, headers=headers)
            except Exception as parse_err:
                logger.warning(f"Failed to check loading state from HF JSON response: {parse_err}")

        response.raise_for_status()
        # Save image to local cache so Creatomate gets a proper HTTP URL
        img_filename = f"{uuid.uuid4().hex}.jpg"
        img_filepath = os.path.join(AUDIO_CACHE_DIR, img_filename)
        with open(img_filepath, "wb") as f:
            f.write(response.content)
        return f"{BACKEND_BASE_URL}/api/audio/{img_filename}"


async def generate_image_pollinations(prompt: str) -> str:
    """
    Downloads image from Pollinations.ai then re-uploads it to uguu.se.
    Returns a stable public URL that Creatomate's cloud servers can download.
    """
    encoded_prompt = urllib.parse.quote(prompt)
    poll_url = (
        f"https://image.pollinations.ai/p/{encoded_prompt}"
        f"?width=1280&height=720&nologo=true&enhance=true"
    )
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            # Step 1: Download from Pollinations (we control rate, no 429)
            r = await client.get(poll_url)
            if r.status_code != 200 or not r.content:
                logger.warning(f"Pollinations returned {r.status_code}")
                return ""
            img_bytes = r.content
            logger.info(f"Pollinations downloaded: {len(img_bytes)//1024}KB")

            # Step 2: Re-upload to uguu.se (free, public, no auth required)
            r2 = await client.post(
                "https://uguu.se/upload.php",
                files={"files[]": ("scene.jpg", img_bytes, "image/jpeg")},
            )
            if r2.status_code == 200:
                data = r2.json()
                if data.get("success") and data.get("files"):
                    url = data["files"][0].get("url", "")
                    if url:
                        logger.info(f"Image uploaded to uguu.se: {url}")
                        return url
            logger.warning(f"uguu.se upload failed: {r2.status_code} {r2.text[:100]}")
    except Exception as e:
        logger.error(f"Pollinations/uguu pipeline failed: {e}")
    return ""


async def generate_image(prompt: str, hero_image_hint: str = "") -> str:
    """
    Generates a public image URL for Creatomate to download.
    Pipeline: Pollinations.ai → uguu.se → HF → Fal.ai → hero hint → placeholder
    """
    img = await generate_image_pollinations(prompt)
    if img:
        return img

    if HF_API_KEY:
        try:
            return await generate_image_hf(prompt)
        except Exception as e:
            logger.error(f"Hugging Face image generation failed: {e}")

    if FAL_API_KEY:
        try:
            return await generate_image_fal(prompt)
        except Exception as e:
            logger.error(f"Fal.ai image generation failed: {e}")

    if hero_image_hint:
        logger.info("Using scraped hero image as fallback.")
        return hero_image_hint

    logger.warning("No image API available. Using placeholder.")
    return "https://placehold.co/1920x1080/1a1a2e/6366f1?text=Ad+Scene"


async def process_scene(scene: dict, brand_kit: dict | None = None) -> dict:
    """Runs voice and image generation for a single scene in parallel."""
    brand_kit = brand_kit or {}
    hero_images = brand_kit.get("hero_images", [])

    hero_hint = hero_images[0] if hero_images and scene.get("scene_number") == 1 else ""
    if not hero_hint and hero_images:
        hero_hint = hero_images[min(scene.get("scene_number", 1) - 1, len(hero_images) - 1)]

    voice_coro = generate_voice(scene["voiceover_script"])
    image_coro = generate_image(scene["visual_image_prompt"], hero_hint)

    voice_res, img_url = await asyncio.gather(voice_coro, image_coro)

    return {
        "scene_number": scene["scene_number"],
        "image_url": img_url,
        "voice_data": voice_res,
        "text_overlay": scene["text_overlay_headline"],
        "duration_seconds": scene.get("duration_seconds", 5),
    }
