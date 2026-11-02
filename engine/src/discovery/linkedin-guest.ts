// L0 adapter: LinkedIn public guest API (no login, no session).
// Falls back to 'blocked' (L2) when challenged — never bypasses.
import type { Card, SourceAdapter, DiscoverContext } from '../types.js';
import { fetchGuarded } from './http.js';
import { mapPool, stopSource } from '../ratelimit.js';
import { loadCheckpoint, recordCheckpoint } from './checkpoint.js';

function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)));
}

function clean(s: string): string {
  return decodeEntities(s.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')).trim();
}

/**
 * The `base-card__full-link` anchor's href, attribute-order independent.
 *
 * Why this is not a global regex over the whole document any more:
 *
 * The previous implementation collected all links with one document-wide regex
 * and zipped that array against `urns` **by index**, while deliberately
 * excluding `links` from the `Math.min(...)` length guard. One card whose
 * full-link anchor carries no `href` (or no such anchor at all) makes `links`
 * one shorter than `urns`, and from that index onward EVERY card takes its
 * neighbour's URL — the cascade was verified against the old code, not
 * inferred.
 *
 * On the 2026-09-17 Strategic Design run, 11 of 284 cards came out with a URL
 * belonging to a neighbouring posting: company and title right, link pointing
 * at someone else's role. Reading the href out of the SAME block that carries
 * title and urn confines that damage to the one malformed card, which falls
 * back to its own urn URL, instead of re-labelling every card after it.
 */
function fullLinkIn(block: string): string | undefined {
  for (const m of block.matchAll(/<a\b[^>]*>/g)) {
    const tag = m[0];
    if (!tag.includes('base-card__full-link')) continue;
    const href = tag.match(/\bhref="([^"]+)"/);
    if (href) return decodeEntities(href[1]);
  }
  return undefined;
}

/**
 * Parse one guest SERP into cards.
 *
 * Parsed per `<li>` block, not by zipping global arrays: every field of a card
 * must come from the same block, or a single malformed card silently re-labels
 * its neighbours.
 */
export function parseGuestCards(html: string, discoveryQuery: string): Card[] {
  const cards: Card[] = [];
  for (const block of html.split('<li>').slice(1)) {
    const urn = block.match(/data-entity-urn="urn:li:jobPosting:(\d+)"/)?.[1];
    const title = block.match(/base-search-card__title">\s*([\s\S]*?)\s*<\/h3>/)?.[1];
    if (!urn || !title) continue; // not a job card block
    const company = block.match(/base-search-card__subtitle[^>]*>([\s\S]*?)<\/a>/)?.[1];
    const loc = block.match(/job-search-card__location">\s*([\s\S]*?)\s*<\/span>/)?.[1];
    const posted = block.match(/<time[^>]*>([\s\S]*?)<\/time>/)?.[1];
    // Fallback to the urn URL only if the block carries no full-link anchor.
    const url = (fullLinkIn(block) || `https://www.linkedin.com/jobs/view/${urn}/`).split('?')[0];
    cards.push({
      title: clean(title),
      company: company ? clean(company) : '',
      location: loc ? clean(loc) : '',
      url,
      // Kept on the Card: freshness is how A1's "verify the opportunity is
      // current" becomes checkable. It used to be dropped one stage later.
      snippet: posted ? `posted: ${clean(posted)}` : '',
      posted: posted ? clean(posted) : undefined,
      sourceJobId: urn,
      source: 'linkedin',
      discoveryQuery,
    });
  }
  return cards;
}

/** The description block of a guest `jobPosting` page, as text, and whether the page
 *  says the role has closed. `html` is one job's page and only this one block is read,
 *  or the surrounding chrome comes with it. */
export function parsePosting(html: string): { desc: string; closed: boolean } {
  const closed = /No longer accepting applications/.test(html);
  const block = html.match(/show-more-less-html__markup[^>]*>([\s\S]*?)<\/div>/)?.[1];
  if (!block) return { desc: '', closed };
  const desc = decodeEntities(
    block
      .replace(/<(br|\/p|\/li|\/h\d)[^>]*>/g, '\n')
      .replace(/<[^>]+>/g, ' ')
      .replace(/&nbsp;/g, ' '),
  )
    .replace(/[ \t]+/g, ' ')
    .trim();
  return { desc, closed };
}

function guestUrl(keywords: string, location: string, start: number, base: string, recencyDays?: number): string {
  const q = new URLSearchParams({ keywords, location, start: String(start) });
  if (recencyDays !== undefined) q.set('f_TPR', `r${recencyDays * 86400}`);
  return `${base}/jobs-guest/jobs/api/seeMoreJobPostings/search?${q.toString()}`;
}

/**
 * What LinkedIn must be asked for a location a run wrote.
 *
 * LinkedIn reads this parameter as a place name, and "EU" is one: Eu, a town in
 * Normandy. A3's `geography_priority` writes EU and means the Union, and that is
 * the right word there, because the rest of the system reads it as geography.
 * So the translation is this source's and lives at this source's boundary. On
 * the 2026-09-24 run, all 194 French cards of 698 were in Normandy or
 * Hauts-de-France and no other EU country appeared; A3's third priority had
 * never been searched.
 */
function linkedinLocation(location: string): string {
  return /^e\.?u\.?$/i.test(location.trim()) ? 'European Union' : location;
}

export function linkedinGuestAdapter(
  locations: string[],
  opts: {
    baseUrl?: string;
    width?: number;
    /** Ask the server for postings this recent, so a request stops paying for cards
     *  the run would discard. The experience and job-type filters are not used here:
     *  on 2026-11-02 `f_JT=I` returned Senior ESG Consultants. */
    recencyDays?: number;
    /** File of finished pairs. Those in it are not asked for again. */
    checkpoint?: string;
  } = {},
): SourceAdapter {
  const base = opts.baseUrl ?? 'https://www.linkedin.com';
  const width = opts.width ?? 4;
  const { recencyDays, checkpoint } = opts;
  if (recencyDays !== undefined && !(recencyDays > 0)) throw new RangeError(`recencyDays must be > 0, got ${recencyDays}`);
  // A Set because every request is budget: on 2026-11-02 the source was stopped
  // after 25, so the same place written twice must not be searched twice.
  const places = [...new Set(locations.map(linkedinLocation))];
  return {
    id: 'linkedin-guest',
    // The guest cards carry title, company, place and date, and no work mode.
    workModeUndeclarable: ['linkedin-guest'],
    async discover(queries: string[], ctx: DiscoverContext): Promise<Card[]> {
      const pairs = queries.flatMap((q) => places.map((loc) => ({ q, loc })));
      const finished = checkpoint ? loadCheckpoint(checkpoint) : new Map<string, Card[]>();
      let collected = 0;
      // Pooled rather than serial: the limiter, not the loop, is the pacing
      // knob, so overlapping the round-trips hides latency without raising the
      // request rate. Results come back in input order — pushing into a shared
      // array from parallel workers would make card order nondeterministic and
      // every downstream diff noisy.
      const perPair = await mapPool(pairs, width, async ({ q, loc }) => {
        const key = `${q} — ${loc} — ${recencyDays ?? ''}`;
        const known = finished.get(key);
        if (known) {
          collected += known.length;
          return known;
        }
        if (ctx.stop.stopped || collected >= ctx.cap) return [] as Card[];
        // Was `throw new Error(...)` on any non-gone failure, so a single 403
        // or 429 aborted every remaining query and lost the whole source's
        // output. Every other adapter continues; this one now does too, and the
        // StopToken decides when the source is genuinely finished.
        const res = await fetchGuarded(guestUrl(q, loc, 0, base, recencyDays), ctx.guard);
        if (!res.ok) return [] as Card[];
        const cards = parseGuestCards(res.text, `${q} — ${loc}`);
        if (checkpoint) recordCheckpoint(checkpoint, key, cards);
        collected += cards.length;
        if (collected >= ctx.cap) stopSource(ctx.stop, 'cap', `cap ${ctx.cap} reached`);
        return cards;
      });
      return perPair.flat().slice(0, ctx.cap);
    },
  };
}
