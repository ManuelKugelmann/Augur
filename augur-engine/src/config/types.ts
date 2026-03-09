/** Brand identifiers */
export type BrandKey = 'the' | 'der' | 'financial' | 'finanz';

/** Internal horizon keys (locale-independent) */
export type HorizonKey = 'tomorrow' | 'soon' | 'future';

/** Brand module type */
export type BrandModule = 'general' | 'markets';

/** Locale */
export type Locale = 'en' | 'de';

/** Horizon configuration */
export interface HorizonConfig {
  key: HorizonKey;
  slug: string;        // locale-specific URL segment
  label: string;       // display name
  refreshCron: string; // cron expression
  dateOffset: string;  // "+1d" | "+1m" | "+1y"
}

/** Color palette */
export interface PaletteConfig {
  bg: string;
  ink: string;
  accent: string;
  meta: string;
}

/** OSINT source configuration */
export interface SourceConfig {
  type: 'tavily' | 'gdelt' | 'rss' | 'yahoo' | 'trade';
  query?: string;
  url?: string;
}

/** Social platform targets */
export type SocialPlatform = 'x' | 'bluesky' | 'mastodon' | 'facebook' | 'linkedin' | 'instagram';

/** Brand configuration */
export interface BrandConfig {
  name: string;
  slug: string;               // URL path prefix
  locale: Locale;
  module: BrandModule;
  masthead: string;
  subtitle: string;
  horizons: HorizonConfig[];
  palette: PaletteConfig;
  imageStylePrefix: string;   // prepended to every image gen prompt
  tonePrompt: string;         // injected into LLM system prompt
  legalDisclaimer: string;
  osintSources: SourceConfig[];
  socialTargets: SocialPlatform[];
  tradeSystemFeed?: string;   // path to sentiment.json (financial brands only)
}

/** Signal data from a source */
export interface Signal {
  source: SourceConfig['type'];
  fetchedAt: string;          // ISO timestamp
  query?: string;
  content: unknown;           // raw signal data
}

/** Prediction article */
export interface Prediction {
  brand: BrandKey;
  horizon: HorizonKey;
  dateKey: string;            // YYYY-MM-DD
  fictiveDate: string;        // prediction target date
  createdAt: string;          // ISO timestamp
  headline: string;
  signal: string;             // "The Signal" section markdown
  extrapolation: string;      // "The Extrapolation" section markdown
  inTheWorks: string;         // "In The Works" section markdown
  sources: Array<{ title: string; url?: string }>;
  tags: string[];
  imagePrompt?: string;
  imagePaths?: string[];

  // Financial brands only
  sentimentSector?: string;
  sentimentDirection?: string;
  sentimentConfidence?: number;

  // LLM metadata
  model: string;
}

/** Social post queue entry */
export interface SocialQueueEntry {
  brand: BrandKey;
  horizon: HorizonKey;
  dateKey: string;
  platform: SocialPlatform;
  scheduledAt: string;        // ISO timestamp
  caption: string;
  imagePath: string;
  createdAt: string;
  postUrl: string | null;
  retryCount: number;
  error: string | null;
  postedAt: string | null;
}

/** Outcome status for prediction tracking */
export type OutcomeStatus = 'confirmed' | 'partial' | 'wrong' | null;
