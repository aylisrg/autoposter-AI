"""Image generation via Gemini 2.5 Flash Image ("Nano Banana").

Why Gemini 2.5 Flash Image:
- ~$0.039 per image (standard) or $0.0195 (Batch API)
- Supports text-in-image natively (unlike DALL-E 3)
- Character consistency across edits (good for brand mascots / product shots)

Alternatives easy to plug in:
- DALL-E 3 (OpenAI) — swap client
- SDXL locally via ComfyUI or diffusers — zero cost, needs GPU
"""
from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from pathlib import Path

from google import genai
from google.genai import types

from app.config import settings

# Where generated images are saved locally.
IMAGES_DIR = Path("data/images")
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class GeneratedImage:
    local_path: str  # relative path under data/images/
    prompt: str
    model: str
    cost_usd: float


def _build_image_prompt(post_text: str, business_desc: str, tone: str) -> str:
    """Turn a post's text into a visual brief.

    Keep it tight and descriptive of a SCENE, not an abstract concept. Gemini image
    does best with concrete visual descriptions.
    """
    return f"""A scroll-stopping social media image for this post.

Business: {business_desc}
Tone: {tone}
Post text: {post_text[:500]}

Style: clean, modern, high-contrast. Looks like a photo or a clear illustration, not \
a generic stock image. No watermarks, no corporate cliché imagery (no handshakes, no \
lightbulbs, no people pointing at charts). Specific and visual.

Format: square 1024x1024.
"""


def generate_image(post_text: str, business_desc: str, tone: str = "casual") -> GeneratedImage:
    """Generate an image for a post using Gemini 2.5 Flash Image.

    Returns GeneratedImage with a local filesystem path. Caller is responsible for
    serving the image (usually via /static mount in FastAPI).
    """
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    if not settings.enable_image_gen:
        raise RuntimeError("Image generation disabled via ENABLE_IMAGE_GEN=false")

    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = _build_image_prompt(post_text, business_desc, tone)

    response = client.models.generate_content(
        model=settings.image_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["Image"],
        ),
    )

    # Extract image bytes from response
    image_bytes: bytes | None = None
    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            data = part.inline_data.data
            # SDK may return bytes directly or base64-encoded str
            image_bytes = data if isinstance(data, bytes) else base64.b64decode(data)
            break

    if image_bytes is None:
        raise RuntimeError("Gemini returned no image data")

    filename = f"{uuid.uuid4().hex}.png"
    out_path = IMAGES_DIR / filename
    out_path.write_bytes(image_bytes)

    # Gemini 2.5 Flash Image @ 1024x1024 ~= 1290 tokens = $0.039/image at $30/M out
    cost = 0.039

    return GeneratedImage(
        local_path=f"images/{filename}",
        prompt=prompt,
        model=settings.image_model,
        cost_usd=cost,
    )
