import type { Signal } from '../config/types.js';

const TAVILY_API = 'https://api.tavily.com/search';

interface TavilyResult {
  title: string;
  url: string;
  content: string;
  score: number;
  published_date?: string;
}

interface TavilyResponse {
  results: TavilyResult[];
  query: string;
}

/** Collect news signals via Tavily search API */
export async function collectTavily(query: string): Promise<Signal> {
  const apiKey = process.env['TAVILY_API_KEY'];
  if (!apiKey) throw new Error('TAVILY_API_KEY not set');

  const res = await fetch(TAVILY_API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key: apiKey,
      query,
      search_depth: 'advanced',
      max_results: 10,
      include_answer: false,
      include_raw_content: false,
    }),
  });

  if (!res.ok) {
    throw new Error(`Tavily API error: ${res.status} ${res.statusText}`);
  }

  const data = (await res.json()) as TavilyResponse;

  return {
    source: 'tavily',
    fetchedAt: new Date().toISOString(),
    query,
    content: data.results.map((r) => ({
      title: r.title,
      url: r.url,
      snippet: r.content,
      score: r.score,
      date: r.published_date,
    })),
  };
}
