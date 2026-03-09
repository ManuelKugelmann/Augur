import { describe, it, expect } from './harness.js';
import { BRANDS } from '../src/config/brands.js';
import {
  systemPromptPass1,
  userPromptPass1,
  systemPromptPass2,
  systemPromptPass3,
} from '../src/extrapolate/prompts.js';

describe('systemPromptPass1', () => {
  it('includes brand tone prompt', () => {
    const prompt = systemPromptPass1(BRANDS.the);
    expect(prompt).toContain('clear-eyed analyst');
  });

  it('includes section labels for EN', () => {
    const prompt = systemPromptPass1(BRANDS.the);
    expect(prompt).toContain('The Signal');
    expect(prompt).toContain('The Extrapolation');
    expect(prompt).toContain('In The Works');
  });

  it('includes section labels for DE', () => {
    const prompt = systemPromptPass1(BRANDS.der);
    expect(prompt).toContain('Das Signal');
    expect(prompt).toContain('Die Extrapolation');
    expect(prompt).toContain('In Arbeit');
  });

  it('requests JSON output', () => {
    const prompt = systemPromptPass1(BRANDS.the);
    expect(prompt).toContain('JSON');
    expect(prompt).toContain('headline');
    expect(prompt).toContain('tags');
  });

  it('includes sentiment fields for financial brands', () => {
    const prompt = systemPromptPass1(BRANDS.financial);
    expect(prompt).toContain('sentiment_sector');
    expect(prompt).toContain('sentiment_direction');
  });

  it('excludes sentiment fields for general brands', () => {
    const prompt = systemPromptPass1(BRANDS.the);
    expect(prompt).not.toContain('sentiment_sector');
  });

  it('instructs German writing for DE brands', () => {
    const prompt = systemPromptPass1(BRANDS.der);
    expect(prompt).toContain('German');
  });
});

describe('userPromptPass1', () => {
  it('includes horizon label', () => {
    const prompt = userPromptPass1([{ test: true }], 'tomorrow', '2026-03-10', 'en');
    expect(prompt).toContain('Tomorrow');
  });

  it('includes DE horizon label for DE locale', () => {
    const prompt = userPromptPass1([{ test: true }], 'tomorrow', '2026-03-10', 'de');
    expect(prompt).toContain('Morgen');
  });

  it('includes fictive date', () => {
    const prompt = userPromptPass1([], 'tomorrow', '2026-03-10', 'en');
    expect(prompt).toContain('2026-03-10');
  });

  it('includes serialized signals', () => {
    const signals = [{ source: 'tavily', data: 'test data' }];
    const prompt = userPromptPass1(signals, 'tomorrow', '2026-03-10', 'en');
    expect(prompt).toContain('tavily');
    expect(prompt).toContain('test data');
  });
});

describe('systemPromptPass2', () => {
  it('instructs editorial rewrite', () => {
    const prompt = systemPromptPass2('en');
    expect(prompt).toContain('editor');
    expect(prompt).toContain('constructive');
  });
});

describe('systemPromptPass3', () => {
  it('includes platform names', () => {
    const prompt = systemPromptPass3(['x', 'bluesky'], 'en');
    expect(prompt).toContain('"x"');
    expect(prompt).toContain('"bluesky"');
  });

  it('requires disclaimer in captions', () => {
    const prompt = systemPromptPass3(['x'], 'en');
    expect(prompt).toContain('AI-generated prediction');
  });

  it('requires link placeholder', () => {
    const prompt = systemPromptPass3(['x'], 'en');
    expect(prompt).toContain('[LINK]');
  });
});
