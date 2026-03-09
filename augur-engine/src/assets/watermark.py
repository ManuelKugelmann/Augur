"""Visible watermark overlay for AI-generated images using Pillow."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

WATERMARK_TEXT = "AI-GENERATED \u00b7 NOT A PHOTO"


def apply_watermark(input_path: str, output_path: str | None = None) -> str:
    """Apply a visible watermark bar to the bottom of an image.

    Returns the output path.
    """
    out = output_path or input_path
    img = Image.open(input_path).convert("RGBA")
    width, height = img.size

    bar_height = max(24, round(height * 0.035))

    # Create watermark bar
    bar = Image.new("RGBA", (width, bar_height), (0, 0, 0, 192))
    draw = ImageDraw.Draw(bar)

    font_size = round(bar_height * 0.5)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_width = bbox[2] - bbox[0]
    text_x = (width - text_width) // 2
    text_y = (bar_height - (bbox[3] - bbox[1])) // 2

    draw.text((text_x, text_y), WATERMARK_TEXT, fill=(255, 255, 255, 230), font=font)

    # Composite bar onto bottom of image
    composite = Image.new("RGBA", img.size)
    composite.paste(img, (0, 0))
    composite.paste(bar, (0, height - bar_height), bar)

    # Save as RGB (webp doesn't need alpha)
    composite.convert("RGB").save(out)
    return out
