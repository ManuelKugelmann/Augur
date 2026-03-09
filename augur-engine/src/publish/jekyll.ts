import { mkdir, writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import type { BrandConfig, HorizonKey, Prediction } from '../config/types.js';
import { BRANDS } from '../config/brands.js';

/** Convert a prediction to Jekyll Markdown with YAML front matter */
export function predictionToMarkdown(prediction: Prediction): string {
  const brand = BRANDS[prediction.brand];
  const horizonSlug = brand.horizons.find((h) => h.key === prediction.horizon)?.slug ?? prediction.horizon;

  // YAML front matter
  const fm: Record<string, unknown> = {
    layout: 'article',
    brand: prediction.brand,
    horizon: prediction.horizon,
    categories: `${prediction.brand}/${horizonSlug}`,
    date: prediction.dateKey,
    headline: prediction.headline,
    fictive_date: prediction.fictiveDate,
    created_at: prediction.createdAt,
    tags: prediction.tags,
    sources: prediction.sources,
    model: prediction.model,
  };

  if (prediction.imagePaths?.length) {
    fm['image_paths'] = prediction.imagePaths;
  }
  if (prediction.imagePrompt) {
    fm['image_prompt'] = prediction.imagePrompt;
  }
  if (prediction.sentimentSector) {
    fm['sentiment_sector'] = prediction.sentimentSector;
    fm['sentiment_direction'] = prediction.sentimentDirection;
    fm['sentiment_confidence'] = prediction.sentimentConfidence;
  }

  // Always include outcome fields (null for new predictions)
  fm['outcome'] = null;
  fm['outcome_note'] = null;
  fm['outcome_date'] = null;

  const yaml = toYaml(fm);

  // Markdown body — the three sections
  const sectionLabels = brand.locale === 'de'
    ? { signal: 'Das Signal', extrapolation: 'Die Extrapolation', inTheWorks: 'In Arbeit' }
    : { signal: 'The Signal', extrapolation: 'The Extrapolation', inTheWorks: 'In The Works' };

  const body = `## ${sectionLabels.signal}

${prediction.signal}

## ${sectionLabels.extrapolation}

${prediction.extrapolation}

## ${sectionLabels.inTheWorks}

${prediction.inTheWorks}
`;

  return `---\n${yaml}---\n\n${body}`;
}

/** Compute the file path for a prediction within the Jekyll site */
export function predictionFilePath(prediction: Prediction, siteDir: string): string {
  const brand = BRANDS[prediction.brand];
  const horizonSlug = brand.horizons.find((h) => h.key === prediction.horizon)?.slug ?? prediction.horizon;
  const slug = prediction.headline
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 60);

  // Jekyll expects: _posts/{path}/{YYYY-MM-DD}-{slug}.md
  return join(siteDir, '_posts', prediction.brand, horizonSlug, `${prediction.dateKey}-${slug}.md`);
}

/** Write a prediction as a Markdown file to the Jekyll site directory */
export async function writePrediction(prediction: Prediction, siteDir: string): Promise<string> {
  const filePath = predictionFilePath(prediction, siteDir);
  const markdown = predictionToMarkdown(prediction);

  await mkdir(dirname(filePath), { recursive: true });
  await writeFile(filePath, markdown, 'utf-8');

  console.log(`[publish] wrote ${filePath}`);
  return filePath;
}

/** Simple YAML serializer for front matter (handles our specific data shapes) */
function toYaml(obj: Record<string, unknown>, indent = 0): string {
  const pad = '  '.repeat(indent);
  let out = '';

  for (const [key, val] of Object.entries(obj)) {
    if (val === null || val === undefined) {
      out += `${pad}${key}:\n`;
    } else if (typeof val === 'string') {
      // Quote strings that contain special YAML chars
      if (val.includes(':') || val.includes('#') || val.includes('"') || val.includes('\n') || val.startsWith('[') || val.startsWith('{')) {
        out += `${pad}${key}: ${JSON.stringify(val)}\n`;
      } else {
        out += `${pad}${key}: "${val}"\n`;
      }
    } else if (typeof val === 'number' || typeof val === 'boolean') {
      out += `${pad}${key}: ${val}\n`;
    } else if (Array.isArray(val)) {
      if (val.length === 0) {
        out += `${pad}${key}: []\n`;
      } else if (typeof val[0] === 'string') {
        out += `${pad}${key}: [${val.map((v) => JSON.stringify(v)).join(', ')}]\n`;
      } else {
        // Array of objects
        out += `${pad}${key}:\n`;
        for (const item of val) {
          if (typeof item === 'object' && item !== null) {
            const entries = Object.entries(item as Record<string, unknown>);
            out += `${pad}  - ${entries[0][0]}: ${JSON.stringify(entries[0][1])}\n`;
            for (const [k, v] of entries.slice(1)) {
              out += `${pad}    ${k}: ${JSON.stringify(v)}\n`;
            }
          }
        }
      }
    } else if (typeof val === 'object') {
      out += `${pad}${key}:\n${toYaml(val as Record<string, unknown>, indent + 1)}`;
    }
  }

  return out;
}
