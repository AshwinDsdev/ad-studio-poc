from pydantic import BaseModel, Field
from typing import List, Optional


class BrandKit(BaseModel):
    logo_url: str = Field(default="", description="URL of the brand logo extracted from the site.")
    primary_color: str = Field(default="#5e6ad2", description="Primary brand color in hex.")
    secondary_color: str = Field(default="#FFFFFF", description="Secondary brand color in hex.")
    hero_images: List[str] = Field(default_factory=list, description="Up to 3 hero/product image URLs from the site.")


class VideoScene(BaseModel):
    scene_number: int = Field(..., description="The sequence number of the scene.")
    visual_image_prompt: str = Field(..., description="Detailed prompt for the AI image generator.")
    voiceover_script: str = Field(..., description="The script for the voiceover to read.")
    duration_seconds: float = Field(..., description="Duration of this scene in seconds.")
    text_overlay_headline: str = Field(..., description="Headline text to display on screen.")


class AdVariant(BaseModel):
    variant_label: str = Field(..., description="Short label for this creative angle, e.g. 'Pain Point Hook'.")
    hook: str = Field(..., description="The opening hook line (first 2-3 seconds) designed to stop the scroll.")
    creative_score: int = Field(..., description="Predicted conversion likelihood 0-100, based on hook strength, CTA clarity, and messaging angle.")
    score_rationale: str = Field(..., description="One concise sentence explaining why this score was assigned.")
    call_to_action: str = Field(..., description="The final call to action text, e.g. 'Shop Now'.")
    scenes: List[VideoScene] = Field(..., description="List of video scenes for this variant.")


class AdStoryboardSchema(BaseModel):
    brand_name: str = Field(..., description="The name of the brand.")
    primary_color: str = Field(..., description="The primary brand color in hex (e.g., #FFFFFF).")
    variants: List[AdVariant] = Field(..., description="Exactly 3 distinct ad variants with different creative angles.")


class AdGenerationRequest(BaseModel):
    url: str = Field(..., description="The target website URL to generate an ad for.")
    tenant_id: str = Field(default="demo-tenant", description="The workspace/tenant ID.")


class EditRequest(BaseModel):
    scene_number: Optional[int] = Field(default=None, description="Scene to edit (None = global change).")
    text_overlay: Optional[str] = Field(default=None, description="New headline text for the scene.")
    voiceover_script: Optional[str] = Field(default=None, description="New voiceover script for the scene.")
    image_url: Optional[str] = Field(default=None, description="Replacement image URL for the scene.")
    call_to_action: Optional[str] = Field(default=None, description="New CTA text.")
    music_track: Optional[str] = Field(default=None, description="New background music track name.")
    output_format: str = Field(default="16:9", description="Output format: '16:9', '9:16', or '1:1'.")
    variant_index: int = Field(default=0, description="Which variant (0-2) to re-render.")
