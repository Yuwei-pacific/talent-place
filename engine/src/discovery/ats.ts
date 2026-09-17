// L0 adapters for employer ATS public JSON APIs (no auth) + generic
// employer career-page fetch. Indeed direct HTTP is 403 from datacenter-class
// clients, so Indeed stays L2-declared (public web discovery + employer verify)
// unless a connector is provided at runtime.
import type { Card, SourceAdapter, DiscoverContext } from '../types.js';
import { fetchGuarded } from './http.js';
import { stopSource } from '../ratelimit.js';

interface AtsBoard {
  id: string;
  kind: 'greenhouse' | 'lever' | 'ashby' | 'workable';
  board: string;
}

export function atsAdapter(boards: AtsBoard[]): SourceAdapter {
  return {
    id: 'ats',
    async discover(queries: string[], ctx: DiscoverContext): Promise<Card[]> {
      const out: Card[] = [];
      for (const b of boards) {
        if (ctx.stop.stopped) return out;
        try {
          if (b.kind === 'greenhouse') {
            const res = await fetchGuarded(`https://boards-api.greenhouse.io/v1/boards/${b.board}/jobs?content=false`, ctx.guard);
            if (!res.ok) continue;
            const data = JSON.parse(res.text) as { jobs?: Array<{ id: number; title: string; location?: { name?: string }; absolute_url: string }> };
            for (const j of data.jobs || []) {
              if (!queries.some((q) => matchQuery(q, `${j.title}`))) continue;
              out.push({
                title: j.title,
                company: b.board,
                location: j.location?.name || 'To verify',
                url: j.absolute_url,
                snippet: '',
                sourceJobId: String(j.id),
                source: 'employer',
                discoveryQuery: `ats:${b.board}`,
              });
            }
          } else if (b.kind === 'lever') {
            const res = await fetchGuarded(`https://api.lever.co/v0/postings/${b.board}?mode=json`, ctx.guard);
            if (!res.ok) continue;
            const data = JSON.parse(res.text) as Array<{ id: string; text: string; categories?: { location?: string }; hostedUrl: string }>;
            for (const j of data || []) {
              if (!queries.some((q) => matchQuery(q, j.text))) continue;
              out.push({
                title: j.text,
                company: b.board,
                location: j.categories?.location || 'To verify',
                url: j.hostedUrl,
                snippet: '',
                sourceJobId: j.id,
                source: 'employer',
                discoveryQuery: `ats:${b.board}`,
              });
            }
          }
        } catch {
          continue; // one board failing never kills the run
        }
      }
      return out;
    },
  };
}

function matchQuery(query: string, title: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter((t) => t.length > 2);
  const hay = title.toLowerCase();
  return terms.some((t) => hay.includes(t));
}
