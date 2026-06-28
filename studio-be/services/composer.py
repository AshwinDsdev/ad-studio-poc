import os
import asyncio
import logging
import uuid
import httpx
from PIL import Image, ImageDraw, ImageFont
import textwrap

logger = logging.getLogger(__name__)

# Output format -> (width, height)
FORMAT_DIMENSIONS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}

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

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")

# Raster image magic bytes: JPEG, PNG, GIF, WebP, BMP
_RASTER_MAGIC = [
    b"\xff\xd8\xff",       # JPEG
    b"\x89PNG\r\n",        # PNG
    b"GIF8",               # GIF
    b"RIFF",               # WebP (RIFF....WEBP)
    b"BM",                 # BMP
]

def _is_raster_image(data: bytes) -> bool:
    """Returns True if the byte content looks like a supported raster image."""
    for magic in _RASTER_MAGIC:
        if data[:len(magic)] == magic:
            return True
    return False

def _make_fallback_image(width: int = 1920, height: int = 1080, color: str = "#1a1a2e") -> str:
    """Creates a solid-color JPEG fallback and returns its local path."""
    from PIL import Image as _Image
    img = _Image.new("RGB", (width, height), color)
    path = os.path.join(AUDIO_CACHE_DIR, f"fallback_{uuid.uuid4().hex}.jpg")
    img.save(path, quality=85)
    logger.info(f"Created solid-color fallback image at {path}")
    return path

def _download_image_to_local(image_url: str) -> str:
    """If the image_url is a local path (starts with BACKEND), return the file path.
    Otherwise, download it using httpx with browser-like headers to avoid 403s from CDNs.
    Non-raster responses (SVG, HTML, etc.) are replaced with a solid-color fallback."""
    if image_url.startswith(BACKEND_BASE_URL):
        filename = image_url.split("/")[-1]
        local_path = os.path.join(AUDIO_CACHE_DIR, filename)
        if os.path.exists(local_path):
            # Validate the cached file is actually a raster image
            with open(local_path, "rb") as f:
                header = f.read(12)
            if not _is_raster_image(header):
                logger.warning(f"Cached file {filename} is not a raster image (likely SVG/HTML placeholder). Using fallback.")
                return _make_fallback_image()
            return local_path
        # File referenced but not on disk — fall through to download

    if not image_url:
        logger.warning("Empty image_url, using fallback.")
        return _make_fallback_image()

    # Download remote image (hero images from CDNs, Pollinations, uguu.se, etc.)
    local_path = os.path.join(AUDIO_CACHE_DIR, f"dl_{uuid.uuid4().hex}.jpg")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers) as client:
            r = client.get(image_url)
            if r.status_code != 200:
                logger.warning(f"Image download returned HTTP {r.status_code} for: {image_url}")
                return _make_fallback_image()
            content = r.content
            if not content:
                logger.warning(f"Empty response body for image: {image_url}")
                return _make_fallback_image()
            # Validate content is a real raster image before saving as .jpg
            if not _is_raster_image(content):
                content_preview = content[:200].decode("utf-8", errors="replace")
                logger.warning(
                    f"Downloaded content from {image_url} is not a raster image "
                    f"(got: {content_preview!r}...). Using solid-color fallback."
                )
                return _make_fallback_image()
            with open(local_path, "wb") as f:
                f.write(content)
        logger.info(f"Downloaded image ({len(content)//1024}KB) from {image_url}")
        return local_path
    except Exception as e:
        logger.error(f"Failed to download image {image_url}: {e}")
        return _make_fallback_image()

def _download_file_to_local(file_url: str, ext: str = "") -> str:
    """Downloads any file (audio, video, etc.) to the local cache without content validation.
    Returns the local path, or empty string on failure."""
    if not file_url:
        return ""
    if file_url.startswith(BACKEND_BASE_URL):
        filename = file_url.split("/")[-1]
        local_path = os.path.join(AUDIO_CACHE_DIR, filename)
        if os.path.exists(local_path):
            return local_path
        # File referenced but not on disk — fall through to download
    suffix = ext or (f".{file_url.rsplit('.', 1)[-1]}" if '.' in file_url.rsplit('/', 1)[-1] else ".bin")
    local_path = os.path.join(AUDIO_CACHE_DIR, f"dl_{uuid.uuid4().hex}{suffix}")
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(file_url)
            if r.status_code != 200:
                logger.warning(f"File download returned HTTP {r.status_code} for: {file_url}")
                return ""
            with open(local_path, "wb") as f:
                f.write(r.content)
        logger.info(f"Downloaded file ({len(r.content)//1024}KB) from {file_url}")
        return local_path
    except Exception as e:
        logger.error(f"Failed to download file {file_url}: {e}")
        return ""

def _create_scene_image_with_text(image_path: str, text: str, width: int, height: int, is_cta: bool = False, primary_color: str = "#5e6ad2") -> str:
    """Uses PIL to resize image and draw centered text on it."""
    try:
        if is_cta:
            img = Image.new("RGB", (width, height), primary_color)
        elif not image_path or not os.path.exists(image_path):
            logger.warning(f"image_path missing or not found ({image_path!r}), using solid-color fallback.")
            img = Image.new("RGB", (width, height), "#1a1a2e")
        else:
            img = Image.open(image_path).convert("RGBA")
            img_ratio = img.width / img.height
            target_ratio = width / height

            if img_ratio > target_ratio:
                new_width = int(target_ratio * img.height)
                offset = (img.width - new_width) // 2
                img = img.crop((offset, 0, offset + new_width, img.height))
            else:
                new_height = int(img.width / target_ratio)
                offset = (img.height - new_height) // 2
                img = img.crop((0, offset, img.width, offset + new_height))

            img = img.resize((width, height), Image.Resampling.LANCZOS)
            
        if text:
            overlay = Image.new('RGBA', img.size, (0,0,0,0))
            draw = ImageDraw.Draw(overlay)
            if not is_cta:
                draw.rectangle([(0, height//2), (width, height)], fill=(0,0,0,180))
            
            img = Image.alpha_composite(img.convert("RGBA"), overlay)
            draw = ImageDraw.Draw(img)
            
            try:
                # Need absolute path to a ttf if possible. Fallback will look ugly.
                font_path = "arial.ttf"
                if os.name == 'nt':
                    font_path = "C:\\Windows\\Fonts\\arialbd.ttf"
                font = ImageFont.truetype(font_path, int(height * (0.06 if not is_cta else 0.10)))
            except IOError:
                font = ImageFont.load_default()
                
            lines = textwrap.wrap(text, width=35 if not is_cta else 20)
            
            # total height of text block
            line_heights = [draw.textbbox((0,0), line, font=font)[3] for line in lines]
            total_text_height = sum(line_heights) + len(lines)*10
            
            y_text = height * 0.7 if not is_cta else (height - total_text_height) / 2
                
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                line_width = bbox[2] - bbox[0]
                x_text = (width - line_width) / 2
                
                # Stroke
                stroke_width = 3
                for dx in range(-stroke_width, stroke_width+1):
                    for dy in range(-stroke_width, stroke_width+1):
                        draw.text((x_text+dx, y_text+dy), line, font=font, fill="black")
                        
                draw.text((x_text, y_text), line, font=font, fill="white")
                y_text += line_heights[0] + 10

        out_path = os.path.join(AUDIO_CACHE_DIR, f"comp_{uuid.uuid4().hex}.jpg")
        img.convert("RGB").save(out_path, quality=95)
        return out_path
    except Exception as e:
        logger.error(f"Failed to process image with PIL: {e}")
        return image_path

async def render_video_ad(
    completed_scenes: list,
    storyboard: dict,
    brand_kit: dict | None = None,
    output_format: str = "16:9",
) -> dict:
    # On serverless platforms like Vercel, copy FFmpeg to a writable location and set execute permissions
    if os.name != 'nt':
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            tmp_ffmpeg = "/tmp/ffmpeg"
            if not os.path.exists(tmp_ffmpeg):
                import shutil
                import stat
                os.makedirs("/tmp", exist_ok=True)
                shutil.copy2(ffmpeg_exe, tmp_ffmpeg)
                os.chmod(tmp_ffmpeg, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
            os.environ["IMAGEIO_FFMPEG_EXE"] = tmp_ffmpeg
            logger.info(f"FFmpeg path overridden to {tmp_ffmpeg}")
        except Exception as ex:
            logger.error(f"Failed to configure FFmpeg executable in /tmp: {ex}")

    # Import moviepy inside the function to ensure it doesn't break startup if missing
    from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
    
    brand_kit = brand_kit or {}
    width, height = FORMAT_DIMENSIONS.get(output_format, (1920, 1080))
    primary_color = storyboard.get("primary_color", brand_kit.get("primary_color", "#5e6ad2"))
    
    clips = []
    
    for scene in completed_scenes:
        image_url = scene["image_url"]
        audio_url = scene.get("voice_data", {}).get("audio_url", "")
        text = scene["text_overlay"]
        
        local_img = _download_image_to_local(image_url)
        if not local_img:
            continue
            
        comp_img = _create_scene_image_with_text(local_img, text, width, height)
        
        audio_clip = None
        duration = scene.get("duration_seconds", 5.0)
        
        if audio_url:
            # Use the plain file downloader — audio must NOT go through raster validation
            local_audio = _download_file_to_local(audio_url, ext=".mp3")
            if local_audio and os.path.exists(local_audio):
                try:
                    audio_clip = AudioFileClip(local_audio)
                    duration = max(audio_clip.duration, 3.0)
                except Exception as e:
                    logger.error(f"AudioFileClip error: {e}")
                    audio_clip = None  # Ensure we don't reference a half-constructed clip
                    
        # Moviepy requires duration to be explicitly set for ImageClips
        img_clip = ImageClip(comp_img).with_duration(duration)
        if audio_clip:
            img_clip = img_clip.with_audio(audio_clip)
            
        clips.append(img_clip)
        
    # CTA clip
    cta_text = storyboard.get("call_to_action", "Learn More")
    cta_img = _create_scene_image_with_text("", cta_text, width, height, is_cta=True, primary_color=primary_color)
    cta_clip = ImageClip(cta_img).with_duration(3.0)
    clips.append(cta_clip)
    
    if not clips:
        return {"video_url": "https://placehold.co/1920x1080?text=No+Clips", "source": {}}
        
    try:
        final_video = concatenate_videoclips(clips, method="compose")
        out_filename = f"final_{uuid.uuid4().hex}.mp4"
        out_filepath = os.path.join(AUDIO_CACHE_DIR, out_filename)
        
        # MoviePy's write_videofile might write internal temporary files to the current working directory.
        # Since the deployment root (/var/task) is read-only, we temporarily switch the working directory
        # to the writeable AUDIO_CACHE_DIR (/tmp/audio_cache on Vercel) during execution.
        old_cwd = os.getcwd()
        os.chdir(AUDIO_CACHE_DIR)
        
        try:
            logger.info(f"Writing moviepy video to {out_filepath}...")
            temp_audio_name = f"temp_{uuid.uuid4().hex}.mp3"
            final_video.write_videofile(
                out_filepath,
                fps=24,
                codec="libx264",
                audio_codec="aac",
                ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "faststart"],
                logger=None,
                temp_audiofile=temp_audio_name,
                remove_temp=True
            )
        finally:
            os.chdir(old_cwd)
        
        video_url = f"{BACKEND_BASE_URL}/api/audio/{out_filename}"
        
        # To not break the frontend entirely, just pass an empty source
        return {"video_url": video_url, "source": None}
    except Exception as e:
        logger.error(f"Moviepy render failed: {e}")
        return {"video_url": "", "source": None}
