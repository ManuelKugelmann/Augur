import sharp from 'sharp';
import { mkdir } from 'node:fs/promises';
import { join, dirname } from 'node:path';

/** Social card aspect ratios */
const CARD_SIZES = {
  '1x1': { width: 1080, height: 1080 },   // Instagram feed, Facebook
  '9x16': { width: 1080, height: 1920 },   // Stories, Reels, TikTok
  '16x9': { width: 1200, height: 675 },    // X/Twitter, OpenGraph
} as const;

type CardRatio = keyof typeof CARD_SIZES;

interface CardOptions {
  imagePath: string;       // source article image
  headline: string;
  brandName: string;       // e.g. "THE AUGUR"
  horizonLabel: string;    // e.g. "TOMORROW"
  fictiveDate: string;
  accentColor: string;     // brand accent hex
  outputDir: string;       // directory for card files
  filePrefix: string;      // e.g. "the-tomorrow-2026-03-10"
}

/** Generate social sharing cards in all 3 ratios */
export async function generateCards(options: CardOptions): Promise<string[]> {
  await mkdir(options.outputDir, { recursive: true });
  const paths: string[] = [];

  for (const [ratio, size] of Object.entries(CARD_SIZES)) {
    const outputPath = join(options.outputDir, `${options.filePrefix}-${ratio}.webp`);
    await generateCard(options, size, outputPath);
    paths.push(outputPath);
    console.log(`[cards] generated ${ratio}: ${outputPath}`);
  }

  return paths;
}

async function generateCard(
  options: CardOptions,
  size: { width: number; height: number },
  outputPath: string,
): Promise<void> {
  const { width, height } = size;
  const fontSize = Math.round(width * 0.04);
  const headlineFontSize = Math.round(width * 0.05);
  const padding = Math.round(width * 0.06);

  // Truncate headline to fit
  const maxHeadlineChars = Math.floor((width - 2 * padding) / (headlineFontSize * 0.5));
  const headline = options.headline.length > maxHeadlineChars
    ? options.headline.slice(0, maxHeadlineChars - 3) + '...'
    : options.headline;

  // Create text overlay SVG
  const svg = `<svg width="${width}" height="${height}">
    <!-- Semi-transparent overlay at bottom -->
    <rect y="${height * 0.55}" width="100%" height="${height * 0.45}" fill="rgba(0,0,0,0.7)"/>

    <!-- Brand name -->
    <text x="${padding}" y="${height * 0.62}"
      font-family="serif" font-weight="bold" font-size="${fontSize}"
      fill="white" letter-spacing="4" opacity="0.9">
      ☽ ${escapeXml(options.brandName)}
    </text>

    <!-- Horizon -->
    <text x="${padding}" y="${height * 0.67}"
      font-family="serif" font-size="${fontSize * 0.7}"
      fill="${options.accentColor}" letter-spacing="3">
      ── ${escapeXml(options.horizonLabel)} ──
    </text>

    <!-- Headline -->
    <text x="${padding}" y="${height * 0.76}"
      font-family="serif" font-weight="bold" font-size="${headlineFontSize}"
      fill="white">
      ${escapeXml(headline)}
    </text>

    <!-- Date + source count -->
    <text x="${padding}" y="${height * 0.87}"
      font-family="monospace" font-size="${fontSize * 0.6}"
      fill="rgba(255,255,255,0.7)">
      🔮 Foreseen: ${escapeXml(options.fictiveDate)}
    </text>

    <!-- AI disclaimer -->
    <text x="${padding}" y="${height * 0.93}"
      font-family="monospace" font-size="${fontSize * 0.5}"
      fill="rgba(255,255,255,0.5)" letter-spacing="1">
      ⚠ AI-generated speculation
    </text>

    <!-- Bottom watermark pattern -->
    <rect y="${height - 4}" width="100%" height="4" fill="${options.accentColor}" opacity="0.6"/>
  </svg>`;

  // Resize source image, composite text overlay
  await sharp(options.imagePath)
    .resize(width, height, { fit: 'cover' })
    .composite([{
      input: Buffer.from(svg),
      top: 0,
      left: 0,
    }])
    .webp({ quality: 85 })
    .toFile(outputPath);
}

function escapeXml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}
