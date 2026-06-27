import uuid
import asyncio
import json
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from models import AdGenerationRequest, EditRequest
from database import get_db_client
from services.scraper import scrape_url
from services.llm import generate_storyboard

app = FastAPI(title="AdStudio API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        # Step 1: Scrape
        _push(job_id, 10, "Scraping website & extracting brand assets...")
        scraped_data = await scrape_url(url)
        brand_kit = scraped_data.get("brand_kit", {})

        # Step 2: LLM storyboard (3 variants)
        _push(job_id, 30, "Writing 3 creative ad concepts with AI...")
        storyboard = await asyncio.to_thread(generate_storyboard, scraped_data)

        variants_raw = storyboard.get("variants", [])
        brand_name = storyboard.get("brand_name", "Brand")
        primary_color = storyboard.get("primary_color", brand_kit.get("primary_color", "#5e6ad2"))

        # Inject primary_color into each variant so composer can access it
        for v in variants_raw:
            v["primary_color"] = primary_color
            v["brand_name"] = brand_name

        _push(job_id, 45, f"Generating media assets for {len(variants_raw)} ad variants in parallel...")

        # Step 3: Process all scenes for all variants concurrently
        from services.media_gen import process_scene

        async def process_variant_scenes(variant: dict) -> list:
            scene_tasks = [
                process_scene(scene, brand_kit)
                for scene in variant.get("scenes", [])
            ]
            return await asyncio.gather(*scene_tasks)

        all_variant_scenes = await asyncio.gather(
            *[process_variant_scenes(v) for v in variants_raw]
        )

        # Step 4: Render each variant
        from services.composer import render_video_ad

        completed_variants = []
        for i, (variant, scenes) in enumerate(zip(variants_raw, all_variant_scenes)):
            pct = 65 + int((i / len(variants_raw)) * 25)
            _push(job_id, pct, f"Rendering variant {i + 1}/{len(variants_raw)}: \"{variant.get('variant_label', '')}\"...")

            sorted_scenes = sorted(scenes, key=lambda s: s["scene_number"])
            render_result = await render_video_ad(sorted_scenes, variant, brand_kit, output_format="16:9")
            video_url = render_result.get("video_url", "")
            video_source = render_result.get("source", {})

            completed_variants.append({
                "variant_index": i,
                "variant_label": variant.get("variant_label", f"Variant {i+1}"),
                "hook": variant.get("hook", ""),
                "creative_score": variant.get("creative_score", 70),
                "score_rationale": variant.get("score_rationale", ""),
                "call_to_action": variant.get("call_to_action", "Learn More"),
                "video_url": video_url,
                "video_source": video_source,
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

    except Exception as e:
        _push(job_id, 0, f"FAILED: {str(e)}")


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

    # Update in-memory state
    variant["video_url"] = new_video_url
    variant["video_source"] = new_video_source
    if state:
        progress_streams[job_id]["variants"][variant_index] = variant

    return {"video_url": new_video_url, "video_source": new_video_source, "variant_index": variant_index}


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

    return {"video_url": render_result.get("video_url", ""), "video_source": render_result.get("source", {}), "format": format, "variant_index": variant_index}
