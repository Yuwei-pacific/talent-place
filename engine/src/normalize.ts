// Normalization for cross-portal dedup (A4 rule: same role must merge even when
// portals spell company/title/location differently). Display values are NOT
// modified — only the match keys are normalized.
const LEGAL_SUFFIX =
  /\b(s\.?p\.?a\.?|s\.?r\.?l\.?|s\.?a\.?s\.?|ltd|limited|gmbh|sas|sarl|bv|nv|sl|sa|inc|llc|spa|srl)\b/gi;

const CITY_ALIASES: Record<string, string> = {
  milano: 'milan',
  roma: 'rome',
  torino: 'turin',
  italia: 'italy',
  francia: 'france',
  germania: 'germany',
  spagna: 'spain',
  'paesi bassi': 'netherlands',
  olanda: 'netherlands',
};

// All internship synonyms fold to one token so cross-language duplicates merge.
const TITLE_EQUIV: Array<[RegExp, string]> = [
  [/\bstage\b|\bstagista\b|\bstagiaire\b|\bstageur\b/gi, 'intern'],
  [/\btirocinio\b|\btirocinante\b/gi, 'intern'],
  [/\binternship\b|\bintern\b/gi, 'intern'],
  [/\bpraktikant(?:\:in)?\b|\bpraktikum\b/gi, 'intern'],
  [/\bbeca(?:rio\/a)?\b/gi, 'intern'],
];

export function normCompany(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(LEGAL_SUFFIX, ' ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

export function normTitle(value: string): string {
  let out = value
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '');
  for (const [re, rep] of TITLE_EQUIV) out = out.replace(re, rep);
  return out
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

export function normCity(value: string): string {
  // Take the first segment before a comma FIRST (commas separate city/region/country).
  const first = value.split(',')[0].trim().toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');
  const clean = first.replace(/[^a-z\s]+/g, ' ').trim().replace(/\s+/g, ' ');
  return CITY_ALIASES[clean] || clean;
}

/** Cross-portal merge key: normalized company + title + city. */
export function crossPortalKey(company: string, title: string, location: string): string {
  return `x:${normCompany(company)}|${normTitle(title)}|${normCity(location)}`;
}
