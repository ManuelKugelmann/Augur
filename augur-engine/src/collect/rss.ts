import type { Signal } from '../config/types.js';
import Parser from 'rss-parser';

const parser = new Parser({
  timeout: 15_000,
  maxRedirects: 3,
});

/** Collect signals from an RSS/Atom feed */
export async function collectRss(url: string): Promise<Signal> {
  const feed = await parser.parseURL(url);

  const items = (feed.items ?? []).slice(0, 15).map((item) => ({
    title: item.title ?? '',
    url: item.link ?? '',
    snippet: item.contentSnippet?.slice(0, 300) ?? '',
    date: item.isoDate ?? item.pubDate ?? '',
  }));

  return {
    source: 'rss',
    fetchedAt: new Date().toISOString(),
    query: url,
    content: {
      feedTitle: feed.title,
      feedUrl: url,
      items,
    },
  };
}
