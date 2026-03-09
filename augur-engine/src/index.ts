#!/usr/bin/env node

/**
 * augur-engine CLI
 *
 * Commands:
 *   cycle   --brand=<key> --horizon=<key>   Generate predictions for a brand/horizon
 *   post                                     Process social posting queue
 *   scorecard                                Update outcome tracking
 */

import { join } from 'node:path';
import { BRANDS } from './config/brands.js';
import { computeFictiveDate } from './config/horizons.js';
import type { BrandKey, HorizonKey } from './config/types.js';
import { collectSignals, MIN_SIGNALS } from './collect/index.js';
import { extrapolate } from './extrapolate/pipeline.js';
import { generateImage } from './assets/imagegen.js';
import { applyWatermark } from './assets/watermark.js';
import { generateCards } from './assets/cards.js';
import { writePrediction } from './publish/jekyll.js';
import { commitAndPush } from './publish/git-push.js';
import { queueSocialPosts, readPendingPosts, movePost } from './publish/social-queue.js';

function usage(): void {
  console.log(`
augur-engine — AI prediction pipeline

Commands:
  cycle     --brand=<the|der|financial|finanz> --horizon=<tomorrow|soon|future>
  post      Process pending social posts
  scorecard Update prediction outcomes

Options:
  --dry-run   Print output without writing files or pushing
  --help      Show this help
`);
}

function parseArgs(args: string[]): { command: string; flags: Record<string, string> } {
  const command = args[0] ?? 'help';
  const flags: Record<string, string> = {};

  for (const arg of args.slice(1)) {
    const match = arg.match(/^--(\w[\w-]*)(?:=(.+))?$/);
    if (match) {
      flags[match[1]] = match[2] ?? 'true';
    }
  }

  return { command, flags };
}

function getSiteDir(): string {
  return process.env['SITE_REPO_PATH'] ?? join(process.cwd(), '..', 'augur-site');
}

async function runCycle(brandKey: BrandKey, horizonKey: HorizonKey, dryRun: boolean): Promise<void> {
  const brand = BRANDS[brandKey];
  const siteDir = getSiteDir();
  const fictiveDate = computeFictiveDate(horizonKey);

  console.log(`[augur] cycle: ${brand.name} / ${horizonKey} → ${fictiveDate}${dryRun ? ' (dry-run)' : ''}`);

  // Step 1: Collect signals
  console.log('[augur] step 1: collecting signals...');
  const signals = await collectSignals(brand.osintSources);

  if (signals.length < MIN_SIGNALS) {
    console.error(`[augur] abort: only ${signals.length} signals collected (need ${MIN_SIGNALS}+)`);
    process.exit(1);
  }

  // Step 2: Extrapolate via LLM
  console.log('[augur] step 2: extrapolating...');
  const { prediction, captions } = await extrapolate(brand, horizonKey, signals);

  if (dryRun) {
    console.log('[augur] dry-run — prediction:');
    console.log(JSON.stringify(prediction, null, 2));
    console.log('[augur] dry-run — captions:');
    console.log(JSON.stringify(captions, null, 2));
    return;
  }

  // Step 3: Generate image + watermark + social cards
  console.log('[augur] step 3: generating assets...');
  try {
    const imagePrefix = `${brandKey}-${horizonKey}-${prediction.dateKey}`;
    const imagePath = join(siteDir, 'assets', 'images', `${imagePrefix}.webp`);
    const fullPrompt = brand.imageStylePrefix + (prediction.imagePrompt ?? prediction.headline);

    await generateImage(fullPrompt, imagePath);
    await applyWatermark(imagePath);

    const horizonSlug = brand.horizons.find(h => h.key === horizonKey)?.slug ?? horizonKey;
    const cardPaths = await generateCards({
      imagePath,
      headline: prediction.headline,
      brandName: brand.masthead,
      horizonLabel: horizonSlug.toUpperCase(),
      fictiveDate: prediction.fictiveDate,
      accentColor: brand.palette.accent,
      outputDir: join(siteDir, 'assets', 'cards'),
      filePrefix: imagePrefix,
    });

    prediction.imagePaths = [
      `assets/images/${imagePrefix}.webp`,
      ...cardPaths.map(p => p.replace(siteDir + '/', '')),
    ];
  } catch (err) {
    console.warn('[augur] image generation failed, continuing without image:', err instanceof Error ? err.message : err);
  }

  // Step 4: Publish
  console.log('[augur] step 4: publishing...');
  await writePrediction(prediction, siteDir);
  await queueSocialPosts(prediction, captions, brand, siteDir);

  // Step 5: Commit and push
  console.log('[augur] step 5: pushing to git...');
  await commitAndPush(
    siteDir,
    `augur: ${brand.slug}/${horizonKey} ${prediction.dateKey} — ${prediction.headline.slice(0, 50)}`,
  );

  // Step 6: Notify
  console.log('[augur] step 6: notifying...');
  await notify(
    `${brand.name}: new prediction`,
    `${prediction.headline}\n${brand.slug}/${horizonKey}/${prediction.dateKey}`,
  );

  console.log('[augur] cycle complete');
}

async function runPost(): Promise<void> {
  const siteDir = getSiteDir();
  const pending = await readPendingPosts(siteDir);

  if (pending.length === 0) {
    console.log('[augur] post: no pending posts due');
    return;
  }

  console.log(`[augur] post: ${pending.length} posts due`);

  for (const { path, entry } of pending) {
    try {
      // Social platform posting is stubbed — each platform module will be implemented separately
      console.log(`[augur] posting to ${entry.platform}: ${entry.caption.slice(0, 60)}...`);
      console.warn(`[augur] ${entry.platform} posting not yet implemented — marking as failed`);
      await movePost(path, entry, 'failed', siteDir, undefined, 'platform not yet implemented');
    } catch (err) {
      console.error(`[augur] post failed for ${entry.platform}:`, err);
      await movePost(path, entry, 'failed', siteDir, undefined, err instanceof Error ? err.message : 'unknown');
    }
  }
}

async function notify(title: string, message: string): Promise<void> {
  const ntfyUrl = process.env['NTFY_URL'] ?? 'https://ntfy.sh';
  const ntfyToken = process.env['NTFY_TOKEN'];
  const ntfyTopic = process.env['NTFY_TOPIC'] ?? 'augur-pipeline';

  if (!ntfyToken) {
    console.log('[notify] NTFY_TOKEN not set, skipping notification');
    return;
  }

  try {
    await fetch(`${ntfyUrl}/${ntfyTopic}`, {
      method: 'POST',
      headers: {
        'Title': title,
        ...(ntfyToken ? { 'Authorization': `Bearer ${ntfyToken}` } : {}),
      },
      body: message,
    });
    console.log('[notify] sent');
  } catch (err) {
    console.warn('[notify] failed:', err instanceof Error ? err.message : err);
  }
}

async function main(): Promise<void> {
  const { command, flags } = parseArgs(process.argv.slice(2));

  if (command === 'help' || flags['help']) {
    usage();
    return;
  }

  switch (command) {
    case 'cycle': {
      const brandKey = flags['brand'] as BrandKey | undefined;
      const horizonKey = flags['horizon'] as HorizonKey | undefined;

      if (!brandKey || !BRANDS[brandKey]) {
        console.error(`Error: --brand must be one of: ${Object.keys(BRANDS).join(', ')}`);
        process.exit(1);
      }
      if (!horizonKey || !['tomorrow', 'soon', 'future'].includes(horizonKey)) {
        console.error('Error: --horizon must be one of: tomorrow, soon, future');
        process.exit(1);
      }

      await runCycle(brandKey, horizonKey, flags['dry-run'] === 'true');
      break;
    }

    case 'post':
      await runPost();
      break;

    case 'scorecard':
      console.log('[augur] scorecard: not yet implemented');
      break;

    default:
      console.error(`Unknown command: ${command}`);
      usage();
      process.exit(1);
  }
}

main().catch((err) => {
  console.error('[augur] fatal:', err);
  process.exit(1);
});
