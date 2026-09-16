// Pre-prefilter URL dedup: the same posting is returned once per
// (query x location) fan-out. Merge before scoring so duplicates never
// consume top-K slots or detail budget.
import type { Card } from './types.js';

function normUrl(u: string): string {
  return u.trim().split('?')[0].replace(/\/+$/, '').toLowerCase();
}

/** Merge same-URL cards; keep the longest snippet, union discovery queries. */
export function dedupCards(cards: Card[]): { unique: Card[]; dupCount: number } {
  const byUrl = new Map<string, Card>();
  let dupCount = 0;
  for (const c of cards) {
    const key = c.sourceJobId ? `${c.source}:${c.sourceJobId}` : `url:${normUrl(c.url)}`;
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
    byUrl.set(key, { ...prev, snippet, discoveryQuery: dq });
  }
  return { unique: [...byUrl.values()], dupCount };
}
