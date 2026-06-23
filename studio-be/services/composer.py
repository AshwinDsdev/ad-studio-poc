import os
import asyncio
import logging
import httpx

logger = logging.getLogger(__name__)

CREATOMATE_API_KEY = os.getenv("CREATOMATE_API_KEY")

# Output format → (width, height)
FORMAT_DIMENSIONS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


def _build_caption_elements(words: list[dict], scene_time_offset: float) -> list[dict]:
    """
    Groups word-level timestamps into short caption phrases (3-4 words)
    and returns Creatomate text elements timed to match the audio.
    """
    if not words:
        return []

    elements = []
    group: list[dict] = []

    for word in words:
        group.append(word)
        if len(group) >= 4 or word == words[-1]:
            phrase = " ".join(w["word"] for w in group)
            start = group[0]["start"] + scene_time_offset
            end = group[-1]["start"] + group[-1]["duration"] + scene_time_offset
            duration = max(round(end - start, 3), 0.3)

            elements.append({
                "type": "text",
                "text": phrase,
                "fill_color": "#FFFFFF",
                "stroke_color": "#000000",
                "stroke_width": "2 vmin",
                "font_size": "5 vmin",
                "font_weight": "700",
                "x_alignment": "50%",
                "y": "88%",
                "time": round(start, 3),
                "duration": duration,
                "animations": [
                    {"type": "fade", "duration": "0.1 s", "time": "start"},
                    {"type": "fade", "duration": "0.1 s", "time": "end"},
                ],
            })
            group = []

    return elements


def _build_logo_element(logo_url: str) -> dict | None:
    """Returns a small logo overlay element if a logo URL is available."""
    if not logo_url:
        return None
    return {
        "type": "image",
        "source": logo_url,
        "x": "5%",
        "y": "5%",
        "width": "15%",
        "height": "15%",
        "fit": "contain",
        "x_alignment": "0%",
        "y_alignment": "0%",
    }


async def render_video_ad(
    completed_scenes: list,
    storyboard: dict,
    brand_kit: dict | None = None,
    output_format: str = "16:9",
) -> str:
    """
    Builds a fully dynamic Creatomate composition and polls for the rendered MP4 URL.

    Args:
        completed_scenes: list of processed scene dicts from media_gen.process_scene()
        storyboard: the variant dict (brand_name, primary_color, call_to_action, scenes)
        brand_kit: extracted brand assets (logo_url, hero_images, etc.)
        output_format: "16:9" | "9:16" | "1:1"

    Returns:
        MP4 URL string
    """
    if not CREATOMATE_API_KEY:
        logger.warning("CREATOMATE_API_KEY not set. Returning mock video URL.")
        return "https://creatomate.com/files/assets/demo.mp4"

    brand_kit = brand_kit or {}
    width, height = FORMAT_DIMENSIONS.get(output_format, (1920, 1080))
    primary_color = storyboard.get("primary_color", brand_kit.get("primary_color", "#5e6ad2"))
    logo_url = brand_kit.get("logo_url", "")

    track_elements = []
    running_time = 0.0  # tracks current timeline position for caption offsets

    for scene in completed_scenes:
        voice_data = scene.get("voice_data", {})
        audio_url = voice_data.get("audio_url", "")
        words = voice_data.get("words", [])
        scene_duration = scene.get("duration_seconds", 5.0)

        # --- Caption elements for this scene ---
        caption_elements = _build_caption_elements(words, running_time)

        # --- Scene image element ---
        image_element = {
            "type": "image",
            "source": scene["image_url"],
            "time": 0,
            "duration": "100%",
            "animations": [{"type": "pan", "easing": "linear", "scope": "element"}],
        }

        # --- Headline text overlay ---
        headline_element = {
            "type": "text",
            "text": scene["text_overlay"],
            "fill_color": "#FFFFFF",
            "font_weight": "800",
            "font_size": "6 vmin",
            "stroke_color": "#000000",
            "stroke_width": "1.5 vmin",
            "y": "75%",
            "x_alignment": "50%",
            "animations": [
                {"type": "text-slide", "duration": "0.5 s", "time": "start"},
                {"type": "fade", "duration": "0.3 s", "time": "end"},
            ],
        }

        # --- Audio element ---
        audio_element = {"type": "audio", "source": audio_url, "time": 0} if audio_url else None

        scene_elements = [image_element, headline_element]
        if audio_element:
            scene_elements.append(audio_element)

        scene_group = {
            "type": "composition",
            "track": 1,
            "duration": f"{scene_duration} s",
            "elements": scene_elements,
        }
        track_elements.append(scene_group)
        running_time += scene_duration

        # Caption elements go on the master timeline (track 2), not inside the composition
        for cap in caption_elements:
            track_elements.append({**cap, "track": 2})

    # --- Logo overlay (track 3, spans entire video) ---
    logo_el = _build_logo_element(logo_url)
    if logo_el:
        track_elements.append({**logo_el, "track": 3})

    # --- CTA card (final 3-second scene) ---
    track_elements.append({
        "type": "composition",
        "track": 1,
        "duration": "3 s",
        "fill_color": primary_color,
        "elements": [
            {
                "type": "text",
                "text": storyboard.get("call_to_action", "Learn More"),
                "fill_color": "#FFFFFF",
                "font_weight": "900",
                "font_size": "8 vmin",
                "x_alignment": "50%",
                "y_alignment": "50%",
                "animations": [
                    {"type": "text-scale", "duration": "0.4 s", "time": "start"},
                ],
            }
        ],
    })

    payload = {
        "source": {
            "output_format": "mp4",
            "width": width,
            "height": height,
            "frame_rate": 30,
            "elements": track_elements,
        }
    }

    url = "https://api.creatomate.com/v1/renders"
    headers = {
        "Authorization": f"Bearer {CREATOMATE_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            render_id = data[0].get("id")
            initial_url = data[0].get("url", "")

            poll_url = f"https://api.creatomate.com/v1/renders/{render_id}"
            for _ in range(40):  # up to 80 seconds
                await asyncio.sleep(2)
                poll_res = await client.get(poll_url, headers=headers)
                poll_data = poll_res.json()
                status = poll_data.get("status")
                if status == "succeeded":
                    return poll_data.get("url", initial_url)
                elif status == "failed":
                    err = poll_data.get("error_message") or poll_data.get("error")
                    logger.error(f"Creatomate render failed: {err}")
                    return "https://creatomate.com/files/assets/fallback.mp4"

            logger.warning("Creatomate render polling timed out.")
            return initial_url

    except Exception as e:
        logger.error(f"Creatomate render exception: {e}")
        return "https://creatomate.com/files/assets/fallback.mp4"
