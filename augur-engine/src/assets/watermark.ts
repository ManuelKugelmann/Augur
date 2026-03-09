import sharp from 'sharp';

const WATERMARK_TEXT = 'AI-GENERATED · NOT A PHOTO';

/** Apply a visible watermark bar to the bottom of an image */
export async function applyWatermark(inputPath: string, outputPath?: string): Promise<string> {
  const out = outputPath ?? inputPath;
  const image = sharp(inputPath);
  const { width, height } = await image.metadata();

  if (!width || !height) throw new Error('Could not read image dimensions');

  const barHeight = Math.max(24, Math.round(height * 0.035));
  const fontSize = Math.round(barHeight * 0.5);

  // Create SVG watermark bar
  const svg = `<svg width="${width}" height="${barHeight}">
    <rect width="100%" height="100%" fill="rgba(0,0,0,0.75)"/>
    <text
      x="50%" y="55%"
      text-anchor="middle"
      dominant-baseline="middle"
      font-family="monospace"
      font-size="${fontSize}"
      fill="white"
      letter-spacing="2"
    >${WATERMARK_TEXT}</text>
  </svg>`;

  await image
    .composite([{
      input: Buffer.from(svg),
      gravity: 'south',
    }])
    .toFile(out);

  return out;
}
