import { mkdir, writeFile, readdir, readFile, rename } from 'node:fs/promises';
import { join } from 'node:path';
import type { BrandConfig, Prediction, SocialPlatform, SocialQueueEntry } from '../config/types.js';

/** Schedule social posts for a prediction (staggered 2h apart per platform) */
export async function queueSocialPosts(
  prediction: Prediction,
  captions: Record<SocialPlatform, string>,
  brand: BrandConfig,
  siteDir: string,
): Promise<void> {
  const pendingDir = join(siteDir, '_data', 'social', 'pending');
  await mkdir(pendingDir, { recursive: true });

  const baseTime = new Date();
  let offsetHours = 0;

  for (const platform of brand.socialTargets) {
    const caption = captions[platform];
    if (!caption) continue;

    const scheduledAt = new Date(baseTime.getTime() + offsetHours * 60 * 60 * 1000);

    const entry: SocialQueueEntry = {
      brand: prediction.brand,
      horizon: prediction.horizon,
      dateKey: prediction.dateKey,
      platform,
      scheduledAt: scheduledAt.toISOString(),
      caption,
      imagePath: prediction.imagePaths?.[0] ?? '',
      createdAt: new Date().toISOString(),
      postUrl: null,
      retryCount: 0,
      error: null,
      postedAt: null,
    };

    const filename = `${prediction.brand}-${prediction.dateKey}-${platform}.json`;
    await writeFile(join(pendingDir, filename), JSON.stringify(entry, null, 2), 'utf-8');
    console.log(`[social] queued: ${filename} (scheduled ${scheduledAt.toISOString()})`);

    offsetHours += 2;
  }
}

/** Read all pending social posts */
export async function readPendingPosts(siteDir: string): Promise<Array<{ path: string; entry: SocialQueueEntry }>> {
  const pendingDir = join(siteDir, '_data', 'social', 'pending');
  const files = await readdir(pendingDir).catch(() => [] as string[]);

  const posts: Array<{ path: string; entry: SocialQueueEntry }> = [];

  for (const file of files) {
    if (!file.endsWith('.json')) continue;
    const filePath = join(pendingDir, file);
    const raw = await readFile(filePath, 'utf-8');
    const entry = JSON.parse(raw) as SocialQueueEntry;
    posts.push({ path: filePath, entry });
  }

  return posts.filter((p) => new Date(p.entry.scheduledAt) <= new Date());
}

/** Move a post from pending to posted (success) or failed (error) */
export async function movePost(
  filePath: string,
  entry: SocialQueueEntry,
  status: 'posted' | 'failed',
  siteDir: string,
  postUrl?: string,
  error?: string,
): Promise<void> {
  const targetDir = join(siteDir, '_data', 'social', status);
  await mkdir(targetDir, { recursive: true });

  if (status === 'posted') {
    entry.postUrl = postUrl ?? null;
    entry.postedAt = new Date().toISOString();
  } else {
    entry.error = error ?? 'unknown error';
    entry.retryCount += 1;
  }

  const filename = filePath.split('/').pop()!;
  const targetPath = join(targetDir, filename);
  await writeFile(targetPath, JSON.stringify(entry, null, 2), 'utf-8');

  // Remove from pending
  const { unlink } = await import('node:fs/promises');
  await unlink(filePath);

  console.log(`[social] ${status}: ${filename}`);
}
