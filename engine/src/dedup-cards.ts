// Pre-prefilter URL dedup: the same posting is returned once per
// (query x location) fan-out. Merge before scoring so duplicates never
// consume top-K slots or detail budget.
import type { Card } from './types.js';
import { crossPortalKey, normalizeUrl } from './normalize.js';

/** Cards that A4 §9 calls one role but that the URL/ID merge could not join.
 *
 * A4 names THREE dedup keys — normalised URL, source id, and "combinazione
 * azienda + titolo normalizzato + luogo". Only the first two are merged here,
 * because the third is not a merge: A4 says "Confermare l'identità prima di
 * fondere record", and two identical titles at one company in one city can be
 * two openings the employer posted separately.
 *
 * Measured on the 2026-09-24 Strategic design run: Ferrero's "Assistant Chef de
 * produit Glaces" arrived twice with LinkedIn ids 4460373968 and 4460388636,
 * identical company, title, city and date. Different ids, different URLs, so
 * nothing above could join them and the role would have reached `Roles.xlsx`
 * twice. The group is reported instead, for the agent to resolve — which is what
 * happened by hand on that run, and by hand is exactly what has to become
 * reproducible.
 */
export interface NearDuplicate {
  key: string;
  cards: Card[];
}

export interface DedupResult {
  unique: Card[];
  dupCount: number;
  nearDuplicates: NearDuplicate[];
}

/** Merge same-POSTING cards; keep the longest snippet, union discovery queries.
 *
 * Merging used to discard every URL but the survivor's. `Roles.xlsx` has an
 * `Alternate / Portal URLs` column that was declared unrecoverable for exactly
 * that reason, so the mirrors are now carried on the card instead of dropped.
 */
export function dedupCards(cards: Card[]): DedupResult {
  const byUrl = new Map<string, Card>();
  let dupCount = 0;
  for (const c of cards) {
    const key = c.sourceJobId ? `${c.source}:${c.sourceJobId}` : `url:${normalizeUrl(c.url)}`;
    const prev = byUrl.get(key);
    if (!prev) {
      byUrl.set(key, c);
      continue;
    }
    dupCount++;
    const snippet = (c.snippet || '').length > (prev.snippet || '').length ? c.snippet : prev.snippet;
    const dq = prev.discoveryQuery.includes(c.discoveryQuery)
      ? prev.discoveryQuery
      : `${prev.discoveryQuery} + ${c.discoveryQuery}`;
    // Every URL seen for this posting except the survivor's, deduped.
    const alternates = [...new Set([...(prev.alternateUrls ?? []), ...(c.alternateUrls ?? []), c.url])].filter(
      (u) => normalizeUrl(u) !== normalizeUrl(prev.url),
    );
    byUrl.set(key, { ...prev, snippet, discoveryQuery: dq, alternateUrls: alternates });
  }
  const unique = [...byUrl.values()];

  // A4 §9's third key, as a REPORT rather than a merge — see NearDuplicate.
  const byTriple = new Map<string, Card[]>();
  for (const c of unique) {
    const k = crossPortalKey(c.company, c.title, c.location);
    const g = byTriple.get(k);
    if (g) g.push(c);
    else byTriple.set(k, [c]);
  }
  const nearDuplicates: NearDuplicate[] = [...byTriple]
    .filter(([, g]) => g.length > 1)
    .map(([key, cards]) => ({ key, cards }));

  return { unique, dupCount, nearDuplicates };
}
