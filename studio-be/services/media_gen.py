import os
import uuid
import asyncio
import logging
import httpx
import edge_tts

logger = logging.getLogger(__name__)

FAL_API_KEY = os.getenv("FAL_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")


async def upload_to_tmpfiles(file_bytes: bytes, filename: str) -> str:
    """Uploads bytes to a free temporary host so Creatomate can fetch them via URL."""
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

        audio_url = await upload_to_tmpfiles(audio_bytes, "voice.mp3")
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
            audio_url = await upload_to_tmpfiles(audio_bytes, "voice.mp3")
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

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        images = data.get("images", [])
        if images and images[0].get("url"):
            return images[0]["url"]
        raise ValueError("Fal.ai returned no image URL")


async def generate_image_hf(prompt: str) -> str:
    """Generate image via Hugging Face (may require paid credits)."""
    url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"inputs": prompt, "parameters": {"num_inference_steps": 4}}

    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        image_url = await upload_to_tmpfiles(response.content, "image.jpg")
        return image_url


async def generate_image(prompt: str, hero_image_hint: str = "") -> str:
    """
    Generates a scene image. Tries Fal.ai first, then HF, then hero/placeholder.
    """
    if FAL_API_KEY:
        try:
            return await generate_image_fal(prompt)
        except Exception as e:
            logger.error(f"Fal.ai image generation failed: {e}")

    if HF_API_KEY:
        try:
            return await generate_image_hf(prompt)
        except Exception as e:
            logger.error(f"HuggingFace image generation failed: {e}")

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
