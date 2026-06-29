import uuid
import asyncio
import json
import os
import logging
import sys
from pathlib import Path
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
from models import AdGenerationRequest, EditRequest
from database import get_db_client
from services.scraper import scrape_url
from services.llm import generate_storyboard

AUDIO_CACHE_DIR = Path(__file__).parent / "audio_cache"
try:
    AUDIO_CACHE_DIR.mkdir(exist_ok=True)
    # Test writability
    test_file = AUDIO_CACHE_DIR / f".test_write_{os.getpid()}"
    test_file.write_text("")
    test_file.unlink()
except Exception:
    AUDIO_CACHE_DIR = Path("/tmp/audio_cache")
    AUDIO_CACHE_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="AdStudio API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    try:
        from database import init_db
        init_db()
    except Exception as e:
        import traceback
        print("DATABASE INIT ERROR ON STARTUP:")
        traceback.print_exc()

# In-memory SSE state per job_id
# shape: { job_id: { "progress": int, "status": str, "variants": [...] } }
progress_streams: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _push(job_id: str, progress: int, status: str, variants: list | None = None):
    """Update both SSE memory dict and persist to DB."""
    payload = {"progress": progress, "status": status}
    if variants is not None:
        payload["variants"] = variants  # type: ignore[assignment]
    progress_streams[job_id] = payload

    db = get_db_client()
    db.execute(
        "UPDATE ads SET current_progress = ?, status = ? WHERE id = ?",
        (progress, status, job_id),
    )


def _runtime_snapshot() -> dict:
    ffmpeg_path = os.getenv("IMAGEIO_FFMPEG_EXE", "")
    ffmpeg_exists = bool(ffmpeg_path) and Path(ffmpeg_path).exists()
    return {
        "service": "adstudio-backend",
        "version": app.version,
        "python_version": sys.version.split()[0],
        "backend_base_url": os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000"),
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "audio_cache_dir": str(AUDIO_CACHE_DIR),
        "audio_cache_exists": AUDIO_CACHE_DIR.exists(),
        "audio_cache_writable": os.access(AUDIO_CACHE_DIR, os.W_OK),
        "ffmpeg_env_path": ffmpeg_path,
        "ffmpeg_env_path_exists": ffmpeg_exists,
        "vercel_env": os.getenv("VERCEL_ENV", ""),
        "vercel_region": os.getenv("VERCEL_REGION", ""),
        "vercel_url": os.getenv("VERCEL_URL", ""),
        "git_commit_sha": os.getenv("VERCEL_GIT_COMMIT_SHA", ""),
        "git_commit_ref": os.getenv("VERCEL_GIT_COMMIT_REF", ""),
    }


# ---------------------------------------------------------------------------
# Generation pipeline
# ---------------------------------------------------------------------------

async def generate_ad_pipeline(job_id: str, url: str):
    """
    Full async pipeline:
      1. Scrape + brand kit
      2. LLM → 3 scored variants
      3. For each variant: parallel scene media generation
      4. Compose each variant → MP4 (16:9 default)
      5. Stream progress to frontend via SSE
    """
    try:
        logger.info("Starting ad generation pipeline for job %s and url %s", job_id, url)
        # Step 1: Scrape
        _push(job_id, 10, "Scraping website & extracting brand assets...")
        scraped_data = await scrape_url(url)
        brand_kit = scraped_data.get("brand_kit", {})

        # Step 2: LLM storyboard (1 variant)
        _push(job_id, 30, "Writing creative ad concept with AI...")
        storyboard = await asyncio.to_thread(generate_storyboard, scraped_data)

        variants_raw = storyboard.get("variants", [])
        brand_name = storyboard.get("brand_name", "Brand")
        primary_color = storyboard.get("primary_color", brand_kit.get("primary_color", "#5e6ad2"))

        # Inject primary_color into each variant so composer can access it
        for v in variants_raw:
            v["primary_color"] = primary_color
            v["brand_name"] = brand_name

        _push(job_id, 45, "Generating media assets for ad variant...")

        # Step 3: Process all scenes for all variants concurrently
        from services.media_gen import process_scene

        async def process_variant_scenes(variant: dict) -> list:
            results = []
            scenes_list = variant.get("scenes", [])
            for idx, scene in enumerate(scenes_list):
                res = await process_scene(scene, brand_kit)
                results.append(res)
                if idx < len(scenes_list) - 1:
                    await asyncio.sleep(2.0)
            return results

        all_variant_scenes = await asyncio.gather(
            *[process_variant_scenes(v) for v in variants_raw]
        )
        logger.info("Media generation complete for job %s with %s variant(s)", job_id, len(all_variant_scenes))

        # Step 4: Render each variant
        from services.composer import render_video_ad

        completed_variants = []
        for i, (variant, scenes) in enumerate(zip(variants_raw, all_variant_scenes)):
            pct = 65 + int((i / len(variants_raw)) * 25)
            if len(variants_raw) == 1:
                _push(job_id, pct, f"Rendering video: \"{variant.get('variant_label', '')}\"...")
            else:
                _push(job_id, pct, f"Rendering variant {i + 1}/{len(variants_raw)}: \"{variant.get('variant_label', '')}\"...")

            sorted_scenes = sorted(scenes, key=lambda s: s["scene_number"])
            render_result = await render_video_ad(sorted_scenes, variant, brand_kit, output_format="16:9")
            video_url = render_result.get("video_url", "")
            video_source = render_result.get("source", {})
            render_error = render_result.get("error", "")
            logger.info(
                "Render finished for job %s variant %s with video_url=%s",
                job_id,
                i,
                video_url,
            )
            if not video_url:
                raise RuntimeError(render_error or f"Final render returned no video URL for variant {i}")

            completed_variants.append({
                "variant_index": i,
                "variant_label": variant.get("variant_label", f"Variant {i+1}"),
                "hook": variant.get("hook", ""),
                "creative_score": variant.get("creative_score", 70),
                "score_rationale": variant.get("score_rationale", ""),
                "call_to_action": variant.get("call_to_action", "Learn More"),
                "video_url": video_url,
                "video_source": video_source,
                "render_error": render_error,
                "scenes": sorted_scenes,
                "brand_kit": brand_kit,
                "primary_color": primary_color,
                "brand_name": brand_name,
            })

        # Persist variants JSON to DB
        db = get_db_client()
        db.execute(
            "UPDATE ads SET video_url = ?, storyboard_json = ? WHERE id = ?",
            (
                completed_variants[0]["video_url"] if completed_variants else "",
                json.dumps(completed_variants),
                job_id,
            ),
        )

        _push(job_id, 100, "SUCCESS", variants=completed_variants)
        logger.info("Ad generation pipeline completed successfully for job %s", job_id)

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.exception("Ad generation pipeline failed for job %s", job_id)
        _push(job_id, 0, f"FAILED: {str(e)}")


@app.get("/api/debug/runtime")
async def debug_runtime():
    """
    Safe runtime diagnostics for verifying which deployment/config is live.
    Excludes secrets and focuses on resolved environment and filesystem state.
    """
    return _runtime_snapshot()


# ---------------------------------------------------------------------------
# Proxy for Frontend Video Editor (CORS bypass)
# ---------------------------------------------------------------------------

import mimetypes
from fastapi.responses import StreamingResponse

@app.get("/api/proxy")
async def proxy_media(url: str):
    """
    Proxies external images/audio to the frontend to bypass browser CORS blocks
    when loading the Creatomate Preview SDK.
    """
    import httpx
    try:
        # Determine content type
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            head_res = await client.head(url)
            content_type = head_res.headers.get("content-type", "")

        if not content_type or "octet-stream" in content_type:
            guessed, _ = mimetypes.guess_type(url)
            if guessed:
                content_type = guessed
            else:
                content_type = "application/octet-stream"

        async def stream_generator():
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    async for chunk in response.aiter_bytes():
                        yield chunk

        return StreamingResponse(
            stream_generator(),
            media_type=content_type,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=31536000"
            }
        )
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/ads")
async def create_ad(req: AdGenerationRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())

    db = get_db_client()
    db.execute(
        "INSERT INTO ads (id, tenant_id, status, video_url, current_progress) VALUES (?, ?, ?, ?, ?)",
        (job_id, req.tenant_id, "QUEUED", "", 0),
    )

    progress_streams[job_id] = {"progress": 0, "status": "QUEUED", "variants": []}
    background_tasks.add_task(generate_ad_pipeline, job_id, req.url)

    return {"job_id": job_id, "message": "Ad generation started"}


@app.get("/api/audio/{filename}")
async def serve_audio(filename: str, request: Request):
    """
    Serves generated audio (MP3) and video (MP4) files from the local audio_cache directory.
    Supports HTTP Range requests (206 Partial Content) — required for WebGL-based video
    players like Shotstack Canvas to correctly detect and render the video track.
    Without Range support the canvas falls back to an audio-only rendering context.
    """
    filepath = AUDIO_CACHE_DIR / filename
    if not filepath.exists() or not filepath.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File not found")

    media_type = "video/mp4" if filename.endswith(".mp4") else "audio/mpeg"
    file_size = filepath.stat().st_size

    range_header = request.headers.get("range")
    if range_header:
        # Parse "bytes=start-end"
        try:
            range_val = range_header.replace("bytes=", "")
            parts = range_val.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
        except (ValueError, IndexError):
            start, end = 0, file_size - 1

        end = min(end, file_size - 1)
        chunk_size = end - start + 1

        def ranged_file_iterator():
            with open(filepath, "rb") as f:
                f.seek(start)
                remaining = chunk_size
                while remaining > 0:
                    data = f.read(min(65536, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return StreamingResponse(
            ranged_file_iterator(),
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_size),
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
            },
        )

    # No Range header — serve entire file with Accept-Ranges advertised
    return FileResponse(
        str(filepath),
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length",
        },
    )


@app.get("/api/ads/stream/{job_id}")
async def stream_progress(request: Request, job_id: str):
    """Streams real-time progress via SSE. Sends JSON payloads."""
    async def event_generator():
        last_sent: str = ""
        while True:
            if await request.is_disconnected():
                break

            state = progress_streams.get(job_id)
            if not state:
                yield {"data": json.dumps({"progress": 0, "status": "Job not found"})}
                break

            payload = json.dumps({
                "progress": state["progress"],
                "status": state["status"],
                "variants": state.get("variants", []),
            })

            # Only send if state changed
            if payload != last_sent:
                yield {"data": payload}
                last_sent = payload

            if state["status"] == "SUCCESS" or "FAILED" in state["status"]:
                break

            await asyncio.sleep(0.8)

    return EventSourceResponse(event_generator())


@app.patch("/api/ads/{job_id}/edit")
async def edit_ad(job_id: str, edit: EditRequest):
    """
    Selective re-render: patches only changed layers without re-running the AI pipeline.
    Returns the new video URL for the re-rendered variant.
    """
    state = progress_streams.get(job_id)
    if not state or not state.get("variants"):
        # Try loading from DB
        db = get_db_client()
        rows = db.execute("SELECT storyboard_json FROM ads WHERE id = ?", (job_id,)).rows
        if not rows or not rows[0][0]:
            return {"error": "Job not found or not yet complete"}
        variants = json.loads(rows[0][0])
    else:
        variants = state["variants"]

    variant_index = min(edit.variant_index, len(variants) - 1)
    variant = variants[variant_index]
    scenes = variant.get("scenes", [])
    brand_kit = variant.get("brand_kit", {})

    # Apply text/image patches
    for scene in scenes:
        if edit.scene_number is None or scene["scene_number"] == edit.scene_number:
            if edit.text_overlay:
                scene["text_overlay"] = edit.text_overlay
            if edit.image_url:
                scene["image_url"] = edit.image_url

    if edit.voiceover_script and edit.scene_number is not None:
        from services.media_gen import generate_voice
        target = next((s for s in scenes if s["scene_number"] == edit.scene_number), None)
        if target:
            new_voice = await generate_voice(edit.voiceover_script)
            target["voice_data"] = new_voice

    if edit.call_to_action:
        variant["call_to_action"] = edit.call_to_action

    storyboard_for_render = {
        "primary_color": variant.get("primary_color", "#5e6ad2"),
        "call_to_action": variant.get("call_to_action", "Learn More"),
        "brand_name": variant.get("brand_name", "Brand"),
    }

    from services.composer import render_video_ad
    render_result = await render_video_ad(
        scenes, storyboard_for_render, brand_kit, output_format=edit.output_format
    )
    new_video_url = render_result.get("video_url", "")
    new_video_source = render_result.get("source", {})
    render_error = render_result.get("error", "")

    # Update in-memory state
    variant["video_url"] = new_video_url
    variant["video_source"] = new_video_source
    variant["render_error"] = render_error
    if state:
        progress_streams[job_id]["variants"][variant_index] = variant

    return {
        "video_url": new_video_url,
        "video_source": new_video_source,
        "variant_index": variant_index,
        "error": render_error,
    }


@app.get("/api/ads/{job_id}/render")
async def render_format(job_id: str, format: str = "16:9", variant_index: int = 0):
    """
    On-demand format re-render for format switcher.
    Renders an existing variant in a different aspect ratio.
    """
    state = progress_streams.get(job_id)
    if not state or not state.get("variants"):
        return {"error": "Job not found or not yet complete"}

    variants = state["variants"]
    variant = variants[min(variant_index, len(variants) - 1)]
    scenes = variant.get("scenes", [])
    brand_kit = variant.get("brand_kit", {})
    storyboard_for_render = {
        "primary_color": variant.get("primary_color", "#5e6ad2"),
        "call_to_action": variant.get("call_to_action", "Learn More"),
        "brand_name": variant.get("brand_name", "Brand"),
    }

    from services.composer import render_video_ad
    render_result = await render_video_ad(scenes, storyboard_for_render, brand_kit, output_format=format)

    return {
        "video_url": render_result.get("video_url", ""),
        "video_source": render_result.get("source", {}),
        "format": format,
        "variant_index": variant_index,
        "error": render_result.get("error", ""),
    }
