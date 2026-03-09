import { describe, it, expect } from './harness.js';
import { BRANDS } from '../src/config/brands.js';
import { computeFictiveDate, SECTION_LABELS } from '../src/config/horizons.js';
import type { BrandKey, HorizonKey, BrandConfig } from '../src/config/types.js';

describe('BRANDS config', () => {
  const brandKeys: BrandKey[] = ['the', 'der', 'financial', 'finanz'];

  it('has all 4 brands', () => {
    expect(Object.keys(BRANDS).sort()).toEqual(brandKeys.sort());
  });

  it('every brand has required fields', () => {
    for (const key of brandKeys) {
      const brand = BRANDS[key];
      expect(brand.name).toBeTruthy();
      expect(brand.slug).toBe(key);
      expect(['en', 'de']).toContain(brand.locale);
      expect(['general', 'markets']).toContain(brand.module);
      expect(brand.masthead).toBeTruthy();
      expect(brand.subtitle).toBeTruthy();
      expect(brand.horizons.length).toBe(3);
      expect(brand.palette.bg).toMatch(/^#/);
      expect(brand.palette.ink).toMatch(/^#/);
      expect(brand.palette.accent).toMatch(/^#/);
      expect(brand.imageStylePrefix).toBeTruthy();
      expect(brand.tonePrompt).toBeTruthy();
      expect(brand.legalDisclaimer).toBeTruthy();
      expect(brand.osintSources.length).toBeGreaterThan(0);
      expect(brand.socialTargets.length).toBeGreaterThan(0);
    }
  });

  it('EN brands have en locale', () => {
    expect(BRANDS.the.locale).toBe('en');
    expect(BRANDS.financial.locale).toBe('en');
  });

  it('DE brands have de locale', () => {
    expect(BRANDS.der.locale).toBe('de');
    expect(BRANDS.finanz.locale).toBe('de');
  });

  it('financial brands have markets module', () => {
    expect(BRANDS.financial.module).toBe('markets');
    expect(BRANDS.finanz.module).toBe('markets');
  });

  it('financial brands have tradeSystemFeed', () => {
    expect(BRANDS.financial.tradeSystemFeed).toBeTruthy();
    expect(BRANDS.finanz.tradeSystemFeed).toBeTruthy();
  });

  it('general brands do NOT have tradeSystemFeed', () => {
    expect(BRANDS.the.tradeSystemFeed).toBeUndefined();
    expect(BRANDS.der.tradeSystemFeed).toBeUndefined();
  });

  it('EN brands have EN horizon slugs', () => {
    const slugs = BRANDS.the.horizons.map(h => h.slug);
    expect(slugs).toEqual(['tomorrow', 'soon', 'future']);
  });

  it('DE brands have DE horizon slugs', () => {
    const slugs = BRANDS.der.horizons.map(h => h.slug);
    expect(slugs).toEqual(['morgen', 'bald', 'zukunft']);
  });

  it('all horizons have cron expressions', () => {
    for (const key of brandKeys) {
      for (const h of BRANDS[key].horizons) {
        expect(h.refreshCron).toMatch(/^[\d*/,\s]+$/);
      }
    }
  });

  it('all OSINT sources have valid type', () => {
    const validTypes = ['tavily', 'gdelt', 'rss', 'yahoo', 'trade'];
    for (const key of brandKeys) {
      for (const src of BRANDS[key].osintSources) {
        expect(validTypes).toContain(src.type);
      }
    }
  });
});

describe('computeFictiveDate', () => {
  const anchor = new Date('2026-03-09T12:00:00Z');

  it('tomorrow = +1 day', () => {
    expect(computeFictiveDate('tomorrow', anchor)).toBe('2026-03-10');
  });

  it('soon = +1 month', () => {
    expect(computeFictiveDate('soon', anchor)).toBe('2026-04-09');
  });

  it('future = +1 year', () => {
    expect(computeFictiveDate('future', anchor)).toBe('2027-03-09');
  });

  it('returns YYYY-MM-DD format', () => {
    const result = computeFictiveDate('tomorrow', anchor);
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe('SECTION_LABELS', () => {
  it('has EN labels', () => {
    expect(SECTION_LABELS.en.signal).toBe('The Signal');
    expect(SECTION_LABELS.en.extrapolation).toBe('The Extrapolation');
    expect(SECTION_LABELS.en.inTheWorks).toBe('In The Works');
  });

  it('has DE labels', () => {
    expect(SECTION_LABELS.de.signal).toBe('Das Signal');
    expect(SECTION_LABELS.de.extrapolation).toBe('Die Extrapolation');
    expect(SECTION_LABELS.de.inTheWorks).toBe('In Arbeit');
  });
});
