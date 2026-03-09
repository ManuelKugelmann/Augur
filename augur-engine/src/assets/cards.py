"""Social card compositing using Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CARD_SIZES = {
    "1x1": (1080, 1080),
    "9x16": (1080, 1920),
    "16x9": (1200, 675),
}


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", size
        )
    except OSError:
        return ImageFont.load_default()


def _load_mono_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size
        )
    except OSError:
        return ImageFont.load_default()


def generate_cards(
    image_path: str,
    headline: str,
    brand_name: str,
    horizon_label: str,
    fictive_date: str,
    accent_color: str,
    output_dir: str,
    file_prefix: str,
) -> list[str]:
    """Generate social sharing cards in all 3 ratios. Returns list of output paths."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    for ratio, (w, h) in CARD_SIZES.items():
        out_path = str(Path(output_dir) / f"{file_prefix}-{ratio}.webp")
        _generate_card(image_path, headline, brand_name, horizon_label,
                       fictive_date, accent_color, w, h, out_path)
        paths.append(out_path)

    return paths


def _generate_card(
    image_path: str,
    headline: str,
    brand_name: str,
    horizon_label: str,
    fictive_date: str,
    accent_color: str,
    width: int,
    height: int,
    output_path: str,
) -> None:
    """Generate a single social card."""
    # Load and resize source image
    src = Image.open(image_path).convert("RGB")
    src = _cover_resize(src, width, height)
    card = src.copy()
    draw = ImageDraw.Draw(card, "RGBA")

    font_size = round(width * 0.04)
    headline_font_size = round(width * 0.05)
    padding = round(width * 0.06)

    # Semi-transparent overlay at bottom
    overlay_top = round(height * 0.55)
    draw.rectangle(
        [(0, overlay_top), (width, height)],
        fill=(0, 0, 0, 178),
    )

    font = _load_font(font_size)
    headline_font = _load_font(headline_font_size)
    mono_font = _load_mono_font(round(font_size * 0.6))

    # Brand name
    draw.text(
        (padding, round(height * 0.60)),
        f"\u263d {brand_name}",
        fill=(255, 255, 255, 230),
        font=font,
    )

    # Horizon label
    draw.text(
        (padding, round(height * 0.66)),
        f"\u2500\u2500 {horizon_label.upper()} \u2500\u2500",
        fill=accent_color,
        font=_load_font(round(font_size * 0.7)),
    )

    # Headline (truncated)
    max_chars = (width - 2 * padding) // max(1, round(headline_font_size * 0.5))
    display_headline = headline[:max_chars - 3] + "..." if len(headline) > max_chars else headline
    draw.text(
        (padding, round(height * 0.74)),
        display_headline,
        fill=(255, 255, 255),
        font=headline_font,
    )

    # Date
    draw.text(
        (padding, round(height * 0.86)),
        f"Foreseen: {fictive_date}",
        fill=(255, 255, 255, 178),
        font=mono_font,
    )

    # AI disclaimer
    draw.text(
        (padding, round(height * 0.92)),
        "AI-generated speculation",
        fill=(255, 255, 255, 128),
        font=_load_mono_font(round(font_size * 0.5)),
    )

    # Bottom accent bar
    draw.rectangle(
        [(0, height - 4), (width, height)],
        fill=accent_color,
    )

    card.convert("RGB").save(output_path, "WEBP", quality=85)


def _cover_resize(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize image to cover target dimensions, then center-crop."""
    src_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        new_h = target_h
        new_w = round(img.width * (target_h / img.height))
    else:
        new_w = target_w
        new_h = round(img.height * (target_w / img.width))

    img = img.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))
