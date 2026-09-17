// L0 adapter: CercoLavoro public SERP (no auth).
// URL shape: https://www.cercolavoro.com/offerte-lavoro-milano?ricerca=<terms>
// (city slug + ?ricerca= works; other shapes 404 — probed 2026-09-10.)
// Card markup: article.job-card > .job-card-title a (title+url),
// .job-card-work-place a ("Company - City (PR)"), .data_pubblicazione (DD/MM/YYYY).
// Jobijoba: no stable public search URL found (404) — not included.
// You'll Get It: /internships?search= 308-redirects to a JS app shell with no
// server-rendered postings — not script-fetchable. Kept out; its postings
// still surface via WebFetch detail verification when needed.
import type { Card, SourceAdapter, DiscoverContext } from '../types.js';
import { fetchGuarded } from './http.js';
import { stopSource } from '../ratelimit.js';

function clean(s: string): string {
  return s
    .replace(/<[^>]+>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim();
}

export function parseCercoCards(html: string, discoveryQuery: string): Card[] {
  const cards: Card[] = [];
  const blocks = html.split('<article class="job-card"');
  for (const b of blocks.slice(1)) {
    const titleM = b.match(/job-card-title[\s\S]*?<a href="([^"]+)">([\s\S]*?)<\/a>/);
    const placeM = b.match(/job-card-work-place[\s\S]*?<a[^>]*>([\s\S]*?)<\/a>/);
    const dateM = b.match(/data_pubblicazione">(\d{2}\/\d{2}\/\d{4})</);
    if (!titleM) continue;
    const url = titleM[1];
    const title = clean(titleM[2]);
    const place = placeM ? clean(placeM[1]) : 'To verify';
    // "Nazca srl - Milano (MI)" -> company "Nazca srl", location "Milano (MI)"
    const dash = place.lastIndexOf(' - ');
    const company = dash > 0 ? place.slice(0, dash).trim() : place;
    const location = dash > 0 ? place.slice(dash + 3).trim() : 'To verify';
    const idM = url.match(/-(\d+)$/);
    cards.push({
      title,
      company,
      location,
      url,
      snippet: dateM ? `pubblicato il ${dateM[1]}` : '',
      posted: dateM ? dateM[1] : undefined,
      sourceJobId: idM ? `cerc:${idM[1]}` : undefined,
      source: 'cercolavoro',
      discoveryQuery,
    });
  }
  return cards;
}

const CITY_SLUGS = ['milano', 'roma', 'torino', 'bologna', 'italia'];

export function cercoLavoroAdapter(): SourceAdapter {
  return {
    id: 'cercolavoro',
    async discover(queries: string[], ctx: DiscoverContext): Promise<Card[]> {
      const out: Card[] = [];
      for (const q of queries) {
        for (const city of CITY_SLUGS) {
          if (ctx.stop.stopped) return out;
          const url = `https://www.cercolavoro.com/offerte-lavoro-${city}?ricerca=${encodeURIComponent(q)}`;
          const res = await fetchGuarded(url, ctx.guard);
          if (!res.ok) continue; // one city failing never kills the run
          out.push(...parseCercoCards(res.text, `${q} @ ${city}`));
          if (out.length >= ctx.cap) {
            stopSource(ctx.stop, 'cap', `cap ${ctx.cap} reached`);
            return out;
          }
        }
      }
      return out;
    },
  };
}
