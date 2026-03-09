import { readFile } from 'node:fs/promises';
import type { Signal } from '../config/types.js';

interface SentimentData {
  sector: string;
  direction: string;
  confidence: number;
  horizon: string;
  rationale_signals: string[];
  generated_at: string;
}

/** Read trade.sh sentiment output from a JSON file */
export async function collectTradeSentiment(path?: string): Promise<Signal> {
  const filePath = path ?? process.env['TRADE_SENTIMENT_PATH'] ?? '/tmp/sentiment.json';

  const raw = await readFile(filePath, 'utf-8');
  const data = JSON.parse(raw) as SentimentData | SentimentData[];

  return {
    source: 'trade',
    fetchedAt: new Date().toISOString(),
    content: data,
  };
}
