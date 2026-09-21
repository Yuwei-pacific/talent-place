// Pre-prefilter URL dedup: the same posting is returned once per
// (query x location) fan-out. Merge before scoring so duplicates never
// consume top-K slots or detail budget.
import type { Card } from './types.js';
import { normalizeUrl } from './normalize.js';

/** Merge same-POSTING cards; keep the longest snippet, union discovery queries.
 *
 * Merging used to discard every URL but the survivor's. `Roles.xlsx` has an
 * `Alternate / Portal URLs` column that was declared unrecoverable for exactly
 * that reason, so the mirrors are now carried on the card instead of dropped.
 */
export function dedupCards(cards: Card[]): { unique: Card[]; dupCount: number } {
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
  return { unique: [...byUrl.values()], dupCount };
}
