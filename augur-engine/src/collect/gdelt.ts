import type { Signal } from '../config/types.js';

const GDELT_DOC_API = 'https://api.gdeltproject.org/api/v2/doc/doc';

/** Collect geopolitical signals from GDELT Cloud API */
export async function collectGdelt(): Promise<Signal> {
  // GDELT DOC API: latest articles mentioning key themes
  const params = new URLSearchParams({
    query: 'theme:ECON_BANKRUPTCY OR theme:ENV_CLIMATECHANGE OR theme:CRISISLEX_CRISISLEXREC OR theme:MILITARY',
    mode: 'ArtList',
    maxrecords: '20',
    format: 'json',
    sort: 'DateDesc',
    timespan: '24h',
  });

  const res = await fetch(`${GDELT_DOC_API}?${params}`);
  if (!res.ok) {
    throw new Error(`GDELT API error: ${res.status} ${res.statusText}`);
  }

  const data = (await res.json()) as { articles?: Array<{
    url: string;
    title: string;
    seendate: string;
    domain: string;
    language: string;
    sourcecountry: string;
  }> };

  const articles = (data.articles ?? []).map((a) => ({
    title: a.title,
    url: a.url,
    date: a.seendate,
    source: a.domain,
    country: a.sourcecountry,
  }));

  return {
    source: 'gdelt',
    fetchedAt: new Date().toISOString(),
    content: articles,
  };
}
