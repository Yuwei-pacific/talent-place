// A1 §Fonti: "Una pagina aggregata è una fonte di scoperta, non un datore di
// lavoro." / A4: the same sentence, aimed at the column — `Company / Outreach
// Account` is the employer that hires, and an aggregator "va in `Sources /
// Portals`, mai qui".
//
// On the 2026-09-22 Accessory design ED.14 run, 363 unique cards arrived with a
// job board or an employment agency as `company`, and nothing downstream
// noticed. `dedupCards` could not: the two copies carry different URLs and
// different company names. The history check could not: the aggregator's name is
// not in the record either. The parser could not: it reports what the SERP said,
// correctly. So it was resolved by hand, and that resolution lived only in that
// run's verdicts.json.
//
// This module decides one thing — is the poster the employer — and nothing else.
// It cannot find the real employer; that needs a read, which A1 assigns to the
// agent. What it can do is refuse to attribute, which is exactly A1's
// instruction: "Se il datore non è identificabile con certezza, il candidato
// resta non risolto — attribuirlo all'aggregatore rompe il raggruppamento per
// azienda e la deduplicazione storica, che sono per azienda."
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { normCompany } from './normalize.js';

export interface AggregatorEntry {
  /** The normalised name, so the table is checkable against `normCompany`. */
  pattern: string;
  note: string;
}

export interface AggregatorTable {
  entries: AggregatorEntry[];
  /** Where the table was read from, for the run manifest. */
  source: string;
  /** True when the file was not there at all. Not the same answer as an empty
   *  table, and the manifest must not conflate them — the same distinction
   *  `load_aliases` had to make for `company-aliases.csv`. */
  missing: boolean;
}

/** Read the human-maintained table. `pattern;note`, `#` comments, one per line. */
export function loadAggregators(path: string): AggregatorTable {
  let text: string;
  try {
    text = readFileSync(path, 'utf-8');
  } catch {
    return { entries: [], source: path, missing: true };
  }
  const entries: AggregatorEntry[] = [];
  for (const raw of text.replace(/^﻿/, '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || line.startsWith('pattern;')) continue;
    const [pattern, ...rest] = line.split(';');
    const key = (pattern ?? '').trim().toLowerCase();
    if (key) entries.push({ pattern: key, note: rest.join(';').trim() });
  }
  return { entries, source: path, missing: false };
}

/** The file that ships with the engine. Resolved from `lib/`, so it is
 *  `engine/data/aggregators.csv` from the repo root.
 *
 *  `fileURLToPath`, not `.pathname`: the repo lives under a directory whose name
 *  contains spaces, and `.pathname` percent-encodes them — so the read would
 *  fail, the table would come back empty, and nothing down the line would say
 *  so. That is the failure `company-aliases.csv` already had once, and the test
 *  beside this asserts the path resolves to a file that is actually there. */
export function defaultAggregatorPath(): string {
  return fileURLToPath(new URL('../data/aggregators.csv', import.meta.url));
}

/**
 * Does `pattern` name this company?
 *
 * Whole-token containment rather than a substring test, and rather than plain
 * equality. Equality alone misses the measured variant spellings the SERP
 * produces ("Orienta" vs "Orienta Agenzia per il Lavoro"); a substring test
 * would match `orienta` inside `orientamento` and demote a real employer. Token
 * runs give both without the false positive.
 */
export function matchesCompany(pattern: string, companyNorm: string): boolean {
  if (!pattern || !companyNorm) return false;
  const want = pattern.split(/\s+/).filter(Boolean);
  const have = companyNorm.split(/\s+/).filter(Boolean);
  if (want.length === 0 || want.length > have.length) return false;
  for (let i = 0; i + want.length <= have.length; i++) {
    if (want.every((t, j) => have[i + j] === t)) return true;
  }
  return false;
}

/**
 * Which entry, if any, claims this poster.
 *
 * Returns the entry rather than a boolean so the caller can record WHICH name
 * fired — that is what makes the table's health reportable per entry, the way
 * `falseFriendHits` makes an inert false-friend term visible instead of merely
 * present.
 */
export function aggregatorFor(company: string, table: AggregatorTable): AggregatorEntry | null {
  const norm = normCompany(company ?? '');
  if (!norm) return null;
  return table.entries.find((e) => matchesCompany(e.pattern, norm)) ?? null;
}
