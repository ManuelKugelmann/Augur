import type { BrandConfig, BrandKey } from './types.js';

const EN_GENERAL_HORIZONS = [
  { key: 'tomorrow' as const, slug: 'tomorrow', label: 'Tomorrow', refreshCron: '0 */6 * * *', dateOffset: '+1d' },
  { key: 'soon' as const, slug: 'soon', label: 'Soon', refreshCron: '0 2 * * *', dateOffset: '+1m' },
  { key: 'future' as const, slug: 'future', label: 'Future', refreshCron: '0 3 * * 1', dateOffset: '+1y' },
];

const DE_GENERAL_HORIZONS = [
  { key: 'tomorrow' as const, slug: 'morgen', label: 'Morgen', refreshCron: '0 1,7,13,19 * * *', dateOffset: '+1d' },
  { key: 'soon' as const, slug: 'bald', label: 'Bald', refreshCron: '0 4 * * *', dateOffset: '+1m' },
  { key: 'future' as const, slug: 'zukunft', label: 'Zukunft', refreshCron: '0 5 * * 1', dateOffset: '+1y' },
];

const IMAGE_STYLE_GENERAL = 'Editorial documentary photograph, photojournalistic style, natural lighting, high detail, 35mm lens. ';
const IMAGE_STYLE_FINANCIAL = 'Professional financial editorial photograph, Bloomberg terminal aesthetic, corporate environment, clean lighting. ';

export const BRANDS: Record<BrandKey, BrandConfig> = {
  the: {
    name: 'The Augur',
    slug: 'the',
    locale: 'en',
    module: 'general',
    masthead: 'THE AUGUR',
    subtitle: 'Foresight from the signal noise',
    horizons: EN_GENERAL_HORIZONS,
    palette: { bg: '#f4f0e8', ink: '#1a1a1a', accent: '#8b0000', meta: '#6b5b4f' },
    imageStylePrefix: IMAGE_STYLE_GENERAL,
    tonePrompt: 'You are a clear-eyed analyst writing for The Augur. Lead with the problem. Don\'t soften it. Then identify real, concrete, sourced efforts addressing it. Never fabricate solutions. If no credible solution exists, say so. Write in AP/Reuters style.',
    legalDisclaimer: 'AI-generated speculation — not news. Not financial advice.',
    osintSources: [
      { type: 'tavily', query: 'top geopolitical developments today' },
      { type: 'gdelt' },
      { type: 'rss', url: 'https://feeds.bbci.co.uk/news/world/rss.xml' },
      { type: 'rss', url: 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml' },
    ],
    socialTargets: ['x', 'bluesky', 'facebook'],
  },

  der: {
    name: 'Der Augur',
    slug: 'der',
    locale: 'de',
    module: 'general',
    masthead: 'DER AUGUR',
    subtitle: 'Voraussicht aus dem Signalrauschen',
    horizons: DE_GENERAL_HORIZONS,
    palette: { bg: '#f4f0e8', ink: '#1a1a1a', accent: '#1a3a5c', meta: '#6b5b4f' },
    imageStylePrefix: IMAGE_STYLE_GENERAL,
    tonePrompt: 'Du bist ein nüchterner Analyst, der für Der Augur schreibt. Beginne mit dem Problem. Beschönige nichts. Identifiziere dann reale, konkrete, belegte Lösungsansätze. Erfinde keine Lösungen. Wenn keine glaubwürdige Lösung existiert, sage das. Schreibe im Stil von Reuters/DPA.',
    legalDisclaimer: 'KI-generierte Spekulation — keine Nachricht. Keine Finanzberatung.',
    osintSources: [
      { type: 'tavily', query: 'wichtigste geopolitische Entwicklungen heute' },
      { type: 'gdelt' },
      { type: 'rss', url: 'https://www.tagesschau.de/xml/rss2/' },
      { type: 'rss', url: 'https://www.spiegel.de/schlagzeilen/tops/index.rss' },
    ],
    socialTargets: ['x', 'mastodon', 'linkedin'],
  },

  financial: {
    name: 'Financial Augur',
    slug: 'financial',
    locale: 'en',
    module: 'markets',
    masthead: 'FINANCIAL AUGUR',
    subtitle: 'Market foresight from open signals',
    horizons: [
      { key: 'tomorrow' as const, slug: 'tomorrow', label: 'Tomorrow', refreshCron: '0 2,8,14,20 * * *', dateOffset: '+1d' },
      { key: 'soon' as const, slug: 'soon', label: 'Soon', refreshCron: '30 2 * * *', dateOffset: '+1m' },
      { key: 'future' as const, slug: 'future', label: 'Future', refreshCron: '0 6 * * 1', dateOffset: '+1y' },
    ],
    palette: { bg: '#f0f2f4', ink: '#1a1a1a', accent: '#0a6e3a', meta: '#5a6570' },
    imageStylePrefix: IMAGE_STYLE_FINANCIAL,
    tonePrompt: 'You are a financial analyst writing for Financial Augur. Focus on market signals, sector rotations, and macro trends. Cite specific data points. Assign confidence levels. Never recommend specific trades. Frame as sector-level opinion only.',
    legalDisclaimer: 'AI-generated opinion — not financial advice. The Augur may hold positions in discussed sectors.',
    osintSources: [
      { type: 'tavily', query: 'financial markets major developments today' },
      { type: 'yahoo' },
      { type: 'rss', url: 'https://feeds.bloomberg.com/markets/news.rss' },
      { type: 'trade' },
    ],
    socialTargets: ['x', 'linkedin', 'bluesky'],
    tradeSystemFeed: '/tmp/sentiment.json',
  },

  finanz: {
    name: 'Finanz Augur',
    slug: 'finanz',
    locale: 'de',
    module: 'markets',
    masthead: 'FINANZ AUGUR',
    subtitle: 'Marktvoraussicht aus offenen Signalen',
    horizons: [
      { key: 'tomorrow' as const, slug: 'morgen', label: 'Morgen', refreshCron: '0 3,9,15,21 * * *', dateOffset: '+1d' },
      { key: 'soon' as const, slug: 'bald', label: 'Bald', refreshCron: '30 4 * * *', dateOffset: '+1m' },
      { key: 'future' as const, slug: 'zukunft', label: 'Zukunft', refreshCron: '0 7 * * 1', dateOffset: '+1y' },
    ],
    palette: { bg: '#f0f2f4', ink: '#1a1a1a', accent: '#0a6e3a', meta: '#5a6570' },
    imageStylePrefix: IMAGE_STYLE_FINANCIAL,
    tonePrompt: 'Du bist ein Finanzanalyst, der für Finanz Augur schreibt. Fokussiere auf Marktsignale, Sektorrotationen und Makrotrends. Zitiere spezifische Datenpunkte. Weise Konfidenzniveaus zu. Empfehle niemals spezifische Trades. Formuliere als Sektormeinung.',
    legalDisclaimer: 'KI-generierte Einschätzung — keine Finanzberatung. Der Augur kann Positionen in besprochenen Sektoren halten.',
    osintSources: [
      { type: 'tavily', query: 'Finanzmärkte wichtigste Entwicklungen heute' },
      { type: 'yahoo' },
      { type: 'rss', url: 'https://www.handelsblatt.com/contentexport/feed/top' },
      { type: 'trade' },
    ],
    socialTargets: ['x', 'mastodon', 'linkedin'],
    tradeSystemFeed: '/tmp/sentiment.json',
  },
};
