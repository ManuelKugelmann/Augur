"""Image generation via Replicate (primary) with fal.ai fallback."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx

log = logging.getLogger("augur.assets")

REPLICATE_API = "https://api.replicate.com/v1/models/black-forest-labs/flux-2-klein-4b/predictions"
FAL_API = "https://queue.fal.run/fal-ai/flux-2/klein/4b"


async def generate_image(prompt: str, output_path: str) -> str:
    """Generate an image via Replicate (primary) with fal.ai fallback.

    Returns the output path on success.
    """
    replicate_token = os.environ.get("REPLICATE_API_TOKEN")
    if replicate_token:
        try:
            url = await _generate_via_replicate(prompt, replicate_token)
            await _download_and_save(url, output_path)
            log.info("generated via Replicate")
            return output_path
        except Exception as exc:
            log.warning("Replicate failed, trying fal.ai fallback: %s", exc)

    fal_key = os.environ.get("FAL_KEY")
    if fal_key:
        try:
            url = await _generate_via_fal(prompt, fal_key)
            await _download_and_save(url, output_path)
            log.info("generated via fal.ai (fallback)")
            return output_path
        except Exception as exc:
            raise RuntimeError(
                f"Both image providers failed. fal.ai error: {exc}"
            ) from exc

    raise RuntimeError(
        "No image generation API key configured (REPLICATE_API_TOKEN or FAL_KEY)"
    )


async def _generate_via_replicate(prompt: str, token: str) -> str:
    """Generate via Replicate API with polling."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            REPLICATE_API,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "input": {
                    "prompt": prompt,
                    "width": 1024,
                    "height": 768,
                    "num_outputs": 1,
                    "output_format": "webp",
                    "output_quality": 85,
                }
            },
        )
        resp.raise_for_status()
        prediction = resp.json()

    poll_url = prediction.get("urls", {}).get(
        "get", f"https://api.replicate.com/v1/predictions/{prediction['id']}"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(60):  # max 60s
            if prediction["status"] in ("succeeded", "failed"):
                break
            await asyncio.sleep(1)
            resp = await client.get(
                poll_url, headers={"Authorization": f"Bearer {token}"}
            )
            prediction = resp.json()

    if prediction["status"] == "failed":
        raise RuntimeError(f"Replicate prediction failed: {prediction.get('error')}")

    output = prediction.get("output", [])
    if not output:
        raise RuntimeError("No image URL in Replicate output")
    return output[0]


async def _generate_via_fal(prompt: str, key: str) -> str:
    """Generate via fal.ai API."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            FAL_API,
            headers={
                "Authorization": f"Key {key}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "image_size": {"width": 1024, "height": 768},
                "num_images": 1,
                "output_format": "webp",
                "sync_mode": True,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    images = data.get("images", [])
    if not images:
        raise RuntimeError("No image URL in fal.ai output")
    return images[0]["url"]


async def _download_and_save(url: str, output_path: str) -> None:
    """Download an image URL and save to disk."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        Path(output_path).write_bytes(resp.content)
