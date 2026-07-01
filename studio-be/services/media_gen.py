import os
import uuid
import asyncio
import logging
import httpx
import edge_tts

logger = logging.getLogger(__name__)

FAL_API_KEY = os.getenv("FAL_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")
CLOUDFLARE_WORKER_API_KEY = os.getenv("CLOUDFLARE_WORKER_API_KEY")
CLOUDFLARE_WORKER_URL = "https://free-image-generation-ap.ashwindatasense.workers.dev/"

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")
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


async def upload_to_tmpfiles(file_bytes: bytes, filename: str) -> str:
    """Uploads bytes to a free temporary host so Creatomate can fetch them."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://tmpfiles.org/api/v1/upload",
                files={"file": (filename, file_bytes)},
            )
            data = r.json()
            if data.get("status") == "success":
                url = data["data"]["url"]
                return url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
    except Exception as e:
        logger.error(f"Upload to tmpfiles failed: {e}")
    return ""


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


async def generate_image_gemini(prompt: str) -> str:
    """
    Generate image via Google Gemini Imagen 3 (free tier).
    Uses the existing GEMINI_API_KEY, saves result locally and returns a backend URL.
    """
    import base64
    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_api_key:
        logger.warning("GEMINI_API_KEY not set, skipping Gemini Imagen.")
        return ""

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"imagen-3.0-generate-002:predict?key={gemini_api_key}"
    )
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "16:9",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.warning(f"Gemini Imagen returned {response.status_code}: {response.text[:200]}")
                return ""
            data = response.json()
            predictions = data.get("predictions", [])
            if not predictions:
                logger.warning("Gemini Imagen returned no predictions.")
                return ""
            b64_data = predictions[0].get("bytesBase64Encoded", "")
            if not b64_data:
                logger.warning("Gemini Imagen prediction had no image bytes.")
                return ""
            img_bytes = base64.b64decode(b64_data)
            img_filename = f"gemini_{uuid.uuid4().hex}.jpg"
            img_filepath = os.path.join(AUDIO_CACHE_DIR, img_filename)
            with open(img_filepath, "wb") as f:
                f.write(img_bytes)
            logger.info(f"Gemini Imagen generated image: {len(img_bytes)//1024}KB")
            return f"{BACKEND_BASE_URL}/api/audio/{img_filename}"
    except Exception as e:
        logger.error(f"Gemini Imagen generation failed: {e}")
    return ""


async def generate_image_cloudflare(prompt: str) -> str:
    """Generate image via custom Cloudflare worker."""
    headers = {"Authorization": f"Bearer {CLOUDFLARE_WORKER_API_KEY}"} if CLOUDFLARE_WORKER_API_KEY else {}
    payload = {"prompt": prompt}
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(CLOUDFLARE_WORKER_URL, json=payload, headers=headers)
        response.raise_for_status()
        
        # Save image to local cache instead of tmpfiles.org
        img_filename = f"cf_{uuid.uuid4().hex}.jpg"
        img_filepath = os.path.join(AUDIO_CACHE_DIR, img_filename)
        with open(img_filepath, "wb") as f:
            f.write(response.content)
            
        return f"{BACKEND_BASE_URL}/api/audio/{img_filename}"


async def generate_image(prompt: str, hero_image_hint: str = "") -> str:
    """
    Generates a locally-cached image and returns a backend-served URL.
    Pipeline: hero hint → Cloudflare Worker → Gemini Imagen 3 → HF → Fal.ai → placeholder
    """
    if hero_image_hint:
        logger.info("Using scraped hero image instead of AI generation.")
        return hero_image_hint

    # 1. Your custom Cloudflare Worker (free, fastest)
    try:
        img = await generate_image_cloudflare(prompt)
        if img:
            return img
    except Exception as e:
        logger.error(f"Cloudflare Worker image generation failed: {e}")

    # 2. Google Gemini Imagen 3 (free tier, high quality)
    img = await generate_image_gemini(prompt)
    if img:
        return img

    # 3. Hugging Face Serverless Inference (free tier)
    if HF_API_KEY:
        try:
            img = await generate_image_hf(prompt)
            if img:
                return img
        except Exception as e:
            logger.error(f"Hugging Face image generation failed: {e}")

    # 4. Fal.ai (requires key but free tier available)
    if FAL_API_KEY:
        try:
            img = await generate_image_fal(prompt)
            if img:
                return img
        except Exception as e:
            logger.error(f"Fal.ai image generation failed: {e}")

    logger.warning("All image generation sources exhausted. Using placeholder.")
    return "https://placehold.co/1920x1080/1a1a2e/6366f1?text=Ad+Scene"


async def process_scene(scene: dict, brand_kit: dict | None = None) -> dict:
    """Runs voice and image generation for a single scene in parallel."""
    brand_kit = brand_kit or {}
    hero_images = brand_kit.get("hero_images", [])

    # Use scraped hero images sequentially for scenes.
    # If the website has enough scraped images, scene 1 gets image 1, scene 2 gets image 2, etc.
    # If we run out of scraped images, it falls back to AI generation.
    scene_number = scene.get("scene_number", 1)
    idx = scene_number - 1
    hero_hint = hero_images[idx] if hero_images and idx >= 0 and idx < len(hero_images) else ""

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
