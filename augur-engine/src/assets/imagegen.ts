import { writeFile, mkdir } from 'node:fs/promises';
import { join, dirname } from 'node:path';

const REPLICATE_API = 'https://api.replicate.com/v1/models/black-forest-labs/flux-2-klein-4b/predictions';
const FAL_API = 'https://queue.fal.run/fal-ai/flux-2/klein/4b';

interface ReplicateResponse {
  id: string;
  status: string;
  output?: string[];
  error?: string;
  urls?: { get: string };
}

interface FalResponse {
  images?: Array<{ url: string }>;
  request_id?: string;
}

/** Generate an image via Replicate (primary) with fal.ai fallback */
export async function generateImage(
  prompt: string,
  outputPath: string,
): Promise<string> {
  // Try Replicate first
  const replicateToken = process.env['REPLICATE_API_TOKEN'];
  if (replicateToken) {
    try {
      const result = await generateViaReplicate(prompt, replicateToken);
      await downloadAndSave(result, outputPath);
      console.log('[image] generated via Replicate');
      return outputPath;
    } catch (err) {
      console.warn('[image] Replicate failed, trying fal.ai fallback:', err instanceof Error ? err.message : err);
    }
  }

  // Fallback to fal.ai
  const falKey = process.env['FAL_KEY'];
  if (falKey) {
    try {
      const result = await generateViaFal(prompt, falKey);
      await downloadAndSave(result, outputPath);
      console.log('[image] generated via fal.ai (fallback)');
      return outputPath;
    } catch (err) {
      throw new Error(`Both image providers failed. fal.ai error: ${err instanceof Error ? err.message : err}`);
    }
  }

  throw new Error('No image generation API key configured (REPLICATE_API_TOKEN or FAL_KEY)');
}

/** Generate via Replicate API (synchronous prediction) */
async function generateViaReplicate(prompt: string, token: string): Promise<string> {
  // Create prediction
  const createRes = await fetch(REPLICATE_API, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      input: {
        prompt,
        width: 1024,
        height: 768,
        num_outputs: 1,
        output_format: 'webp',
        output_quality: 85,
      },
    }),
  });

  if (!createRes.ok) {
    throw new Error(`Replicate create error: ${createRes.status} ${await createRes.text()}`);
  }

  let prediction = (await createRes.json()) as ReplicateResponse;

  // Poll for completion (max 60s)
  const pollUrl = prediction.urls?.get ?? `https://api.replicate.com/v1/predictions/${prediction.id}`;
  const deadline = Date.now() + 60_000;

  while (prediction.status !== 'succeeded' && prediction.status !== 'failed') {
    if (Date.now() > deadline) throw new Error('Replicate prediction timed out');
    await new Promise((r) => setTimeout(r, 1000));

    const pollRes = await fetch(pollUrl, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    prediction = (await pollRes.json()) as ReplicateResponse;
  }

  if (prediction.status === 'failed') {
    throw new Error(`Replicate prediction failed: ${prediction.error}`);
  }

  const imageUrl = prediction.output?.[0];
  if (!imageUrl) throw new Error('No image URL in Replicate output');
  return imageUrl;
}

/** Generate via fal.ai API */
async function generateViaFal(prompt: string, key: string): Promise<string> {
  const res = await fetch(FAL_API, {
    method: 'POST',
    headers: {
      'Authorization': `Key ${key}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      prompt,
      image_size: { width: 1024, height: 768 },
      num_images: 1,
      output_format: 'webp',
      sync_mode: true,
    }),
  });

  if (!res.ok) {
    throw new Error(`fal.ai error: ${res.status} ${await res.text()}`);
  }

  const data = (await res.json()) as FalResponse;
  const imageUrl = data.images?.[0]?.url;
  if (!imageUrl) throw new Error('No image URL in fal.ai output');
  return imageUrl;
}

/** Download an image URL and save to disk */
async function downloadAndSave(url: string, outputPath: string): Promise<void> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to download image: ${res.status}`);

  const buffer = Buffer.from(await res.arrayBuffer());
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, buffer);
}
