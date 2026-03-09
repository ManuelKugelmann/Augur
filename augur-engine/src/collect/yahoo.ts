import type { Signal } from '../config/types.js';

const YAHOO_QUOTE_API = 'https://query1.finance.yahoo.com/v7/finance/quote';

const MARKET_TICKERS = [
  '^GSPC',    // S&P 500
  '^DJI',     // Dow Jones
  '^IXIC',    // NASDAQ
  '^STOXX50E',// Euro Stoxx 50
  '^N225',    // Nikkei 225
  'GC=F',     // Gold futures
  'CL=F',     // Crude oil futures
  'DX-Y.NYB', // USD index
  '^VIX',     // VIX
  '^TNX',     // 10Y Treasury yield
];

interface QuoteResult {
  symbol: string;
  shortName?: string;
  regularMarketPrice?: number;
  regularMarketChange?: number;
  regularMarketChangePercent?: number;
  regularMarketTime?: number;
}

/** Collect market signals from Yahoo Finance */
export async function collectYahoo(): Promise<Signal> {
  const symbols = MARKET_TICKERS.join(',');
  const res = await fetch(`${YAHOO_QUOTE_API}?symbols=${encodeURIComponent(symbols)}`, {
    headers: {
      'User-Agent': 'augur-engine/0.1',
    },
  });

  if (!res.ok) {
    throw new Error(`Yahoo Finance API error: ${res.status} ${res.statusText}`);
  }

  const data = (await res.json()) as { quoteResponse?: { result?: QuoteResult[] } };
  const quotes = (data.quoteResponse?.result ?? []).map((q) => ({
    symbol: q.symbol,
    name: q.shortName ?? q.symbol,
    price: q.regularMarketPrice,
    change: q.regularMarketChange,
    changePct: q.regularMarketChangePercent,
  }));

  return {
    source: 'yahoo',
    fetchedAt: new Date().toISOString(),
    content: quotes,
  };
}
