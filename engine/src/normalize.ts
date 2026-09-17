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

// ---------------------------------------------------------------------------
// Reading the canonical CSV's multi-value cells.
//
// There is deliberately NO single universal splitter. The separators in the
// wild are mixed (`Matching Job Titles`: 18 newline / 12 pipe;
// `Sources / Portals`: 8 newline / 14 pipe / 8 semicolon) and one column
// legitimately contains a separator character INSIDE a single value:
// `Work Modes` holds "Physical location shown; onsite/hybrid status to verify",
// so treating ';' as a separator there would shred one value into two.
// Hence a per-column policy rather than one splitter.
// ---------------------------------------------------------------------------

export interface MultiValueSpec {
  /** ';' separates items in this column (true for Sources / Portals only). */
  semicolon: boolean;
  /** Items may carry a leading "N. " numbering prefix to strip. */
  numbered: boolean;
  /** A line may be prefixed "alt. " to mark an alternate URL (Job Links only). */
  altMarker?: boolean;
}

/** Per-column separator policy. Mirrors `MULTI_VALUE_SPEC` in reconcile.py. */
export const MULTI_VALUE_SPEC: Record<string, MultiValueSpec> = {
  'Matching Job Titles': { semicolon: false, numbered: true },
  // altMarker: seen once in the canonical CSV (Cefriel), where a primary
  // employer URL and its LinkedIn mirror share one line. That alternate is a
  // real dedup target, so it must split out rather than ride along inside the
  // primary — otherwise the same role found via the other portal re-enters.
  'Job Links': { semicolon: false, numbered: true, altMarker: true },
  Locations: { semicolon: false, numbered: true },
  'Master-fit Themes': { semicolon: true, numbered: false },
  // semicolon:false is load-bearing — see the comment above.
  'Work Modes': { semicolon: false, numbered: false },
  'Sources / Portals': { semicolon: true, numbered: false },
};

/**
 * Split a numbered cell on its numbering, or return null if the cell does not
 * look like a genuine numbered list.
 *
 * The numbering only counts as a separator when it sits at a real item
 * boundary — the start of the cell, after a newline, or after a pipe — AND the
 * captured numbers form a contiguous 1..N run. Both conditions matter: a title
 * like "1. Intern - Level 2. Design" contains " 2. " mid-sentence, and splitting
 * there would produce bogus items, each of which becomes a wrong dedup key.
 */
function splitNumbered(raw: string): string[] | null {
  if (!/^\s*1\.\s/.test(raw)) return null;
  const parts = raw.split(/(?:^|\n|\|)\s*(\d+)\.\s+/);
  const nums: string[] = [];
  const texts: string[] = [];
  for (let i = 1; i < parts.length; i += 2) {
    nums.push(parts[i]);
    texts.push(parts[i + 1] ?? '');
  }
  if (nums.length === 0) return null;
  const sequential = nums.every((n, i) => n === String(i + 1));
  return sequential ? texts : null;
}

/**
 * Split a canonical multi-value cell into its items.
 *
 * Prefers the numbering when the cell is a genuine numbered list, otherwise
 * falls back to the separator characters. The fallback is equivalent for
 * well-formed input and safer for malformed input.
 */
export function splitMulti(value: string, spec: MultiValueSpec): string[] {
  const raw = (value ?? '').replace(/\r\n?/g, '\n');
  if (!raw.trim()) return [];

  let parts = (spec.numbered ? splitNumbered(raw) : null) ?? raw.split('\n');

  if (spec.altMarker) parts = parts.flatMap((p) => p.split(/(?:^|\s)alt\.\s+/i)).filter(Boolean);

  const out: string[] = [];
  for (const part of parts) {
    const subs = spec.semicolon ? part.split(/\s*\|\s*|\s*;\s*/) : part.split(/\s*\|\s*/);
    for (const sub of subs) {
      const item = sub.replace(/^\d+\.\s*/, '').trim();
      if (item) out.push(item);
    }
  }
  return out;
}

/** Convenience wrapper for a named canonical column. */
export function splitColumn(value: string, column: string): string[] {
  const spec = MULTI_VALUE_SPEC[column];
  if (!spec) throw new Error(`no multi-value spec for column: ${column}`);
  return splitMulti(value, spec);
}
