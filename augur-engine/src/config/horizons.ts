import type { HorizonKey } from './types.js';

/** Compute the fictive date for a given horizon from an anchor date */
export function computeFictiveDate(horizon: HorizonKey, anchor: Date = new Date()): string {
  const d = new Date(anchor);

  switch (horizon) {
    case 'tomorrow':
      d.setDate(d.getDate() + 1);
      break;
    case 'soon':
      d.setMonth(d.getMonth() + 1);
      break;
    case 'future':
      d.setFullYear(d.getFullYear() + 1);
      break;
  }

  return d.toISOString().slice(0, 10); // YYYY-MM-DD
}

/** Get today's date key */
export function todayKey(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Section labels per locale */
export const SECTION_LABELS = {
  en: {
    signal: 'The Signal',
    extrapolation: 'The Extrapolation',
    inTheWorks: 'In The Works',
    sources: 'Sources',
    sentiment: "The Augur's Sentiment",
    foreseenFor: 'Foreseen for',
    divined: 'Divined',
  },
  de: {
    signal: 'Das Signal',
    extrapolation: 'Die Extrapolation',
    inTheWorks: 'In Arbeit',
    sources: 'Quellen',
    sentiment: 'Die Einschätzung des Augur',
    foreseenFor: 'Vorhergesagt für',
    divined: 'Erstellt',
  },
} as const;
