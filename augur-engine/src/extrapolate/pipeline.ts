import type { BrandConfig, HorizonKey, Prediction, Signal, SocialPlatform } from '../config/types.js';
import { computeFictiveDate } from '../config/horizons.js';
import {
  systemPromptPass1,
  userPromptPass1,
  systemPromptPass2,
  systemPromptPass3,
} from './prompts.js';

const ANTHROPIC_API = 'https://api.anthropic.com/v1/messages';

interface AnthropicMessage {
  role: 'user' | 'assistant';
  content: string;
}

interface AnthropicResponse {
  content: Array<{ type: string; text?: string }>;
  stop_reason: string;
  usage: { input_tokens: number; output_tokens: number };
}

/** Call Claude API */
async function callClaude(
  system: string,
  messages: AnthropicMessage[],
  model?: string,
): Promise<string> {
  const apiKey = process.env['ANTHROPIC_API_KEY'];
  if (!apiKey) throw new Error('ANTHROPIC_API_KEY not set');

  const res = await fetch(ANTHROPIC_API, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: model ?? process.env['NEWS_MODEL'] ?? 'claude-sonnet-4-5-20250514',
      max_tokens: 8000,
      system,
      messages,
    }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Anthropic API error ${res.status}: ${body}`);
  }

  const data = (await res.json()) as AnthropicResponse;
  const text = data.content.find((c) => c.type === 'text')?.text;
  if (!text) throw new Error('No text content in Anthropic response');

  console.log(`[llm] tokens: ${data.usage.input_tokens} in / ${data.usage.output_tokens} out`);
  return text;
}

/** Extract JSON from a response that may contain markdown fences */
function extractJson(text: string): string {
  const fenced = text.match(/```(?:json)?\s*\n?([\s\S]*?)\n?```/);
  if (fenced) return fenced[1].trim();
  // Try to find JSON object directly
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start !== -1 && end > start) return text.slice(start, end + 1);
  return text;
}

interface Pass1Output {
  headline: string;
  signal: string;
  extrapolation: string;
  in_the_works: string;
  sources: Array<{ title: string; url?: string }>;
  tags: string[];
  image_prompt: string;
  confidence: string;
  sentiment_sector?: string;
  sentiment_direction?: string;
  sentiment_confidence?: number;
}

interface Pass3Output {
  captions: Record<string, string>;
}

/** Run the full 3-pass extrapolation pipeline */
export async function extrapolate(
  brand: BrandConfig,
  horizon: HorizonKey,
  signals: Signal[],
): Promise<{ prediction: Prediction; captions: Record<SocialPlatform, string> }> {
  const fictiveDate = computeFictiveDate(horizon);
  const signalData = signals.map((s) => ({ source: s.source, data: s.content }));

  // Pass 1: Signals → prediction
  console.log('[llm] pass 1: generating prediction...');
  const pass1Raw = await callClaude(
    systemPromptPass1(brand),
    [{ role: 'user', content: userPromptPass1(signalData, horizon, fictiveDate, brand.locale) }],
  );
  const pass1 = JSON.parse(extractJson(pass1Raw)) as Pass1Output;

  // Pass 2: Rewrite with constructive angle
  console.log('[llm] pass 2: editorial rewrite...');
  const pass2Raw = await callClaude(
    systemPromptPass2(brand.locale),
    [{ role: 'user', content: JSON.stringify(pass1, null, 2) }],
  );
  const pass2 = JSON.parse(extractJson(pass2Raw)) as Pass1Output;

  // Pass 3: Social captions
  console.log('[llm] pass 3: social captions...');
  const pass3Raw = await callClaude(
    systemPromptPass3(brand.socialTargets, brand.locale),
    [{ role: 'user', content: JSON.stringify({ headline: pass2.headline, signal: pass2.signal }, null, 2) }],
  );
  const pass3 = JSON.parse(extractJson(pass3Raw)) as Pass3Output;

  const dateKey = fictiveDate;
  const now = new Date().toISOString();

  const prediction: Prediction = {
    brand: brand.slug as Prediction['brand'],
    horizon,
    dateKey,
    fictiveDate,
    createdAt: now,
    headline: pass2.headline,
    signal: pass2.signal,
    extrapolation: pass2.extrapolation,
    inTheWorks: pass2.in_the_works,
    sources: pass2.sources,
    tags: pass2.tags,
    imagePrompt: pass2.image_prompt,
    model: process.env['NEWS_MODEL'] ?? 'claude-sonnet-4-5-20250514',
    sentimentSector: pass2.sentiment_sector,
    sentimentDirection: pass2.sentiment_direction,
    sentimentConfidence: pass2.sentiment_confidence,
  };

  const captions = pass3.captions as Record<SocialPlatform, string>;

  return { prediction, captions };
}
