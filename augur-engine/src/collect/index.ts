import type { Signal, SourceConfig } from '../config/types.js';
import { collectTavily } from './tavily.js';
import { collectRss } from './rss.js';
import { collectGdelt } from './gdelt.js';
import { collectYahoo } from './yahoo.js';
import { collectTradeSentiment } from './trade-sentiment.js';

/** Collect signals from all sources configured for a brand */
export async function collectSignals(sources: SourceConfig[]): Promise<Signal[]> {
  const results: Signal[] = [];
  const errors: Array<{ source: string; error: unknown }> = [];

  const tasks = sources.map(async (src) => {
    try {
      let signal: Signal;
      switch (src.type) {
        case 'tavily':
          signal = await collectTavily(src.query ?? 'top global developments today');
          break;
        case 'rss':
          signal = await collectRss(src.url!);
          break;
        case 'gdelt':
          signal = await collectGdelt();
          break;
        case 'yahoo':
          signal = await collectYahoo();
          break;
        case 'trade':
          signal = await collectTradeSentiment();
          break;
        default:
          throw new Error(`Unknown source type: ${(src as SourceConfig).type}`);
      }
      results.push(signal);
    } catch (err) {
      errors.push({ source: src.type, error: err });
      console.warn(`[collect] ${src.type} failed:`, err instanceof Error ? err.message : err);
    }
  });

  await Promise.all(tasks);

  console.log(`[collect] ${results.length}/${sources.length} sources succeeded`);
  if (errors.length > 0) {
    console.warn(`[collect] ${errors.length} sources failed: ${errors.map(e => e.source).join(', ')}`);
  }

  return results;
}

/** Minimum number of signals needed to proceed with generation */
export const MIN_SIGNALS = 1;
