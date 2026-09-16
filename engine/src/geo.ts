// Geographic hard filter (A1: Milan > Italy > EU; exclude non-EU).
// Discovery adapters (esp. LinkedIn guest) may ignore the location param,
// so every card is filtered here before the prefilter.
import type { Card } from './types.js';

const EU_HINT =
  /\b(italy|italia|milan|milano|rome|roma|turin|torino|naples|napoli|bologna|florence|venice|france|paris|germany|berlin|munich|spain|madrid|barcelona|austria|vienna|netherlands|amsterdam|belgium|brussels|portugal|lisbon|sweden|stockholm|denmark|copenhagen|ireland|dublin|greece|athens|finland|helsinki|poland|warsaw|europe|european union|\beu\b)\b/i;
const NON_EU_STATES =
  'alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|hampshire|jersey|mexico|york|carolina|dakota|ohio|oklahoma|oregon|pennsylvania|rhode|tennessee|texas|utah|vermont|virginia|washington|wisconsin|wyoming|district of columbia';
const NON_EU_HINT = new RegExp(
  `\\b(united states|u\\.?s\\.?a?\\b|${NON_EU_STATES}|washington dc|new york city|united kingdom|\\buk\\b|england|london|canada|toronto|india|china|beijing|shanghai|singapore|dubai|uae|australia|sydney|brasil|brazil|mexico|chile|colombia|japan|tokyo|korea|seoul)\\b`,
  'i',
);

export function geoVerdict(location: string): 'eu' | 'non-eu' | 'unknown' {
  if (!location || !location.trim()) return 'unknown';
  // US state abbreviations ("College Station, TX") never match \b...\b word
  // patterns, so check them explicitly first.
  if (/,?\s*\b(AK|AL|AR|AZ|CA|CO|CT|DC|DE|FL|GA|HI|IA|ID|IL|IN|KS|KY|LA|MA|MD|ME|MI|MN|MO|MS|MT|NC|ND|NE|NH|NJ|NM|NV|NY|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VA|VT|WA|WI|WV|WY)\.?$/.test(location.trim())) {
    return 'non-eu';
  }
  if (NON_EU_HINT.test(location) && !EU_HINT.test(location)) return 'non-eu';
  if (EU_HINT.test(location)) return 'eu';
  return 'unknown';
}

/** Drop non-EU cards; keep EU + unknown (unknown goes to non_risolto later, never silently dropped). */
export function geoFilter(cards: Card[]): { eu: Card[]; droppedNonEu: Card[] } {
  const eu: Card[] = [];
  const droppedNonEu: Card[] = [];
  for (const c of cards) {
    if (geoVerdict(c.location) === 'non-eu') droppedNonEu.push(c);
    else eu.push(c);
  }
  return { eu, droppedNonEu };
}
