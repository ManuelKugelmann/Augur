"""Jekyll Markdown + YAML front matter writer."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config.brands import BRANDS
from ..config.horizons import SECTION_LABELS
from ..config.types import Prediction


def prediction_to_markdown(prediction: Prediction) -> str:
    """Convert a prediction to Jekyll Markdown with YAML front matter."""
    brand = BRANDS[prediction.brand]
    horizon_slug = next(
        (h.slug for h in brand.horizons if h.key == prediction.horizon),
        prediction.horizon,
    )

    fm: dict[str, object] = {
        "layout": "article",
        "brand": prediction.brand,
        "horizon": prediction.horizon,
        "categories": f"{prediction.brand}/{horizon_slug}",
        "date": prediction.date_key,
        "headline": prediction.headline,
        "fictive_date": prediction.fictive_date,
        "created_at": prediction.created_at,
        "tags": prediction.tags,
        "sources": prediction.sources,
        "model": prediction.model,
    }

    if prediction.image_paths:
        fm["image_paths"] = prediction.image_paths
    if prediction.image_prompt:
        fm["image_prompt"] = prediction.image_prompt
    if prediction.sentiment_sector:
        fm["sentiment_sector"] = prediction.sentiment_sector
        fm["sentiment_direction"] = prediction.sentiment_direction
        fm["sentiment_confidence"] = prediction.sentiment_confidence

    # Always include outcome fields (null for new predictions)
    fm["outcome"] = None
    fm["outcome_note"] = None
    fm["outcome_date"] = None

    yaml = _to_yaml(fm)

    labels = SECTION_LABELS[brand.locale]

    body = f"""## {labels['signal']}

{prediction.signal}

## {labels['extrapolation']}

{prediction.extrapolation}

## {labels['in_the_works']}

{prediction.in_the_works}
"""

    return f"---\n{yaml}---\n\n{body}"


def prediction_file_path(prediction: Prediction, site_dir: str) -> str:
    """Compute the file path for a prediction within the Jekyll site."""
    brand = BRANDS[prediction.brand]
    horizon_slug = next(
        (h.slug for h in brand.horizons if h.key == prediction.horizon),
        prediction.horizon,
    )
    slug = re.sub(r"[^a-z0-9]+", "-", prediction.headline.lower())
    slug = slug.strip("-")[:60]

    return str(
        Path(site_dir)
        / "_posts"
        / prediction.brand
        / horizon_slug
        / f"{prediction.date_key}-{slug}.md"
    )


def write_prediction(prediction: Prediction, site_dir: str) -> str:
    """Write a prediction as a Markdown file to the Jekyll site directory."""
    file_path = prediction_file_path(prediction, site_dir)
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(file_path).write_text(prediction_to_markdown(prediction), encoding="utf-8")
    return file_path


def _to_yaml(obj: dict[str, object], indent: int = 0) -> str:
    """Simple YAML serializer for front matter."""
    pad = "  " * indent
    out = ""

    for key, val in obj.items():
        if val is None:
            out += f"{pad}{key}:\n"
        elif isinstance(val, str):
            if any(c in val for c in ":#{}\n[]") or val.startswith(("'", '"')):
                out += f"{pad}{key}: {json.dumps(val)}\n"
            else:
                out += f'{pad}{key}: "{val}"\n'
        elif isinstance(val, (int, float)):
            out += f"{pad}{key}: {val}\n"
        elif isinstance(val, bool):
            out += f"{pad}{key}: {'true' if val else 'false'}\n"
        elif isinstance(val, list):
            if not val:
                out += f"{pad}{key}: []\n"
            elif isinstance(val[0], str):
                items = ", ".join(json.dumps(v) for v in val)
                out += f"{pad}{key}: [{items}]\n"
            elif isinstance(val[0], dict):
                out += f"{pad}{key}:\n"
                for item in val:
                    entries = list(item.items())
                    out += f"{pad}  - {entries[0][0]}: {json.dumps(entries[0][1])}\n"
                    for k, v in entries[1:]:
                        out += f"{pad}    {k}: {json.dumps(v)}\n"
            else:
                out += f"{pad}{key}: {json.dumps(val)}\n"
        elif isinstance(val, dict):
            out += f"{pad}{key}:\n{_to_yaml(val, indent + 1)}"

    return out
