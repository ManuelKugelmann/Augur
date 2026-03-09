import { describe, it, expect } from './harness.js';
import { predictionToMarkdown, predictionFilePath } from '../src/publish/jekyll.js';
import type { Prediction } from '../src/config/types.js';

function makePrediction(overrides?: Partial<Prediction>): Prediction {
  return {
    brand: 'the',
    horizon: 'tomorrow',
    dateKey: '2026-03-10',
    fictiveDate: '2026-03-10',
    createdAt: '2026-03-09T14:22:00Z',
    headline: 'Grid failures accelerate across three European regions',
    signal: 'European TSOs reported capacity margins below 5%.',
    extrapolation: 'If the blocking pattern holds, load-shedding becomes probable.',
    inTheWorks: 'CATL Erfurt plant reached 14 GWh annual capacity.',
    sources: [
      { title: 'ENTSO-E Transparency Platform', url: 'https://transparency.entsoe.eu/' },
    ],
    tags: ['energy', 'europe'],
    model: 'claude-sonnet-4-5-20250514',
    ...overrides,
  };
}

describe('predictionToMarkdown', () => {
  it('produces valid front matter delimiters', () => {
    const md = predictionToMarkdown(makePrediction());
    expect(md.startsWith('---\n')).toBe(true);
    const parts = md.split('---');
    // Should have at least 3 parts: before first ---, front matter, after second ---
    expect(parts.length).toBeGreaterThanOrEqual(3);
  });

  it('includes headline in front matter', () => {
    const md = predictionToMarkdown(makePrediction());
    expect(md).toContain('headline:');
    expect(md).toContain('Grid failures');
  });

  it('includes brand and horizon in front matter', () => {
    const md = predictionToMarkdown(makePrediction());
    expect(md).toContain('brand: "the"');
    expect(md).toContain('horizon: "tomorrow"');
  });

  it('includes EN section headers for EN brands', () => {
    const md = predictionToMarkdown(makePrediction({ brand: 'the' }));
    expect(md).toContain('## The Signal');
    expect(md).toContain('## The Extrapolation');
    expect(md).toContain('## In The Works');
  });

  it('includes DE section headers for DE brands', () => {
    const md = predictionToMarkdown(makePrediction({ brand: 'der' }));
    expect(md).toContain('## Das Signal');
    expect(md).toContain('## Die Extrapolation');
    expect(md).toContain('## In Arbeit');
  });

  it('includes tags as array', () => {
    const md = predictionToMarkdown(makePrediction({ tags: ['energy', 'europe'] }));
    expect(md).toContain('tags:');
    expect(md).toContain('"energy"');
    expect(md).toContain('"europe"');
  });

  it('includes sources', () => {
    const md = predictionToMarkdown(makePrediction());
    expect(md).toContain('sources:');
    expect(md).toContain('ENTSO-E');
  });

  it('includes outcome fields as null', () => {
    const md = predictionToMarkdown(makePrediction());
    expect(md).toContain('outcome:');
    expect(md).toContain('outcome_note:');
    expect(md).toContain('outcome_date:');
  });

  it('includes sentiment fields for financial brands', () => {
    const md = predictionToMarkdown(makePrediction({
      brand: 'financial',
      sentimentSector: 'semiconductors',
      sentimentDirection: 'bullish',
      sentimentConfidence: 0.6,
    }));
    expect(md).toContain('sentiment_sector:');
    expect(md).toContain('semiconductors');
    expect(md).toContain('sentiment_direction:');
    expect(md).toContain('bullish');
  });

  it('includes categories for Jekyll routing', () => {
    const md = predictionToMarkdown(makePrediction({ brand: 'the', horizon: 'tomorrow' }));
    expect(md).toContain('categories: "the/tomorrow"');
  });

  it('uses DE horizon slug for DE brands', () => {
    const md = predictionToMarkdown(makePrediction({ brand: 'der', horizon: 'tomorrow' }));
    expect(md).toContain('categories: "der/morgen"');
  });
});

describe('predictionFilePath', () => {
  it('generates correct path for EN brand', () => {
    const path = predictionFilePath(makePrediction(), '/site');
    expect(path).toContain('_posts/the/tomorrow/2026-03-10-');
    expect(path).toContain('grid-failures');
    expect(path.endsWith('.md')).toBe(true);
  });

  it('uses DE horizon slug for DE brands', () => {
    const path = predictionFilePath(makePrediction({ brand: 'der', horizon: 'tomorrow' }), '/site');
    expect(path).toContain('_posts/der/morgen/');
  });

  it('slugifies headline', () => {
    const path = predictionFilePath(makePrediction({ headline: 'Hello World! 123' }), '/site');
    expect(path).toContain('hello-world-123');
  });

  it('truncates long slugs', () => {
    const path = predictionFilePath(makePrediction({
      headline: 'A'.repeat(100) + ' very long headline that should be truncated',
    }), '/site');
    // Slug should be max 60 chars
    const filename = path.split('/').pop()!;
    const slug = filename.replace(/^\d{4}-\d{2}-\d{2}-/, '').replace('.md', '');
    expect(slug.length).toBeLessThanOrEqual(60);
  });
});
