// L0 adapter: LinkedIn public guest API (no login, no session).
// Falls back to 'blocked' (L2) when challenged — never bypasses.
import type { Card, SourceAdapter } from '../types.js';
import { fetchText } from './http.js';

function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

function clean(s: string): string {
  return decodeEntities(s.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')).trim();
}

export function parseGuestCards(html: string, discoveryQuery: string): Card[] {
  const urns = [...html.matchAll(/data-entity-urn="urn:li:jobPosting:(\d+)"/g)].map((m) => m[1]);
  const titles = [...html.matchAll(/base-search-card__title">\s*([\s\S]*?)\s*<\/h3>/g)].map((m) => clean(m[1]));
  const subs = [...html.matchAll(/base-search-card__subtitle[^>]*>([\s\S]*?)<\/a>/g)].map((m) => clean(m[1]));
  const locs = [...html.matchAll(/job-search-card__location">\s*([\s\S]*?)\s*<\/span>/g)].map((m) => clean(m[1]));
  const links = [...html.matchAll(/<a[^>]+class="base-card__full-link[^"]*"[^>]+href="([^"]+)"/g)].map((m) =>
    decodeEntities(m[1]),
  );
  const dates = [...html.matchAll(/<time[^>]*>([\s\S]*?)<\/time>/g)].map((m) => clean(m[1]));
  const n = Math.min(urns.length, titles.length, subs.length, locs.length);
  const cards: Card[] = [];
  for (let i = 0; i < n; i++) {
    const url = (links[i] || `https://www.linkedin.com/jobs/view/${urns[i]}/`).split('?')[0];
    cards.push({
      title: titles[i],
      company: subs[i],
      location: locs[i],
      url,
      snippet: dates[i] ? `posted: ${dates[i]}` : '',
      sourceJobId: urns[i],
      source: 'linkedin',
      discoveryQuery,
    });
  }
  return cards;
}

function guestUrl(keywords: string, location: string, start: number): string {
  const q = new URLSearchParams({ keywords, location, start: String(start) });
  return `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?${q.toString()}`;
}

export function linkedinGuestAdapter(locations: string[]): SourceAdapter {
  return {
    id: 'linkedin-guest',
    async discover(queries: string[]): Promise<Card[]> {
      const out: Card[] = [];
      for (const q of queries) {
        for (const loc of locations) {
          const res = await fetchText(guestUrl(q, loc, 0));
          if (!res.ok) {
            if (res.kind === 'gone') continue;
            throw new Error(`linkedin-guest ${res.kind}: ${res.detail}`);
          }
          out.push(...parseGuestCards(res.text, `${q} — ${loc}`));
          if (out.length >= 200) return out;
        }
      }
      return out;
    },
  };
}
