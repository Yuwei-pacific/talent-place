// L0 adapters for employer ATS public JSON APIs (no auth) + generic
// employer career-page fetch. Indeed direct HTTP is 403 from datacenter-class
// clients, so Indeed stays L2-declared (public web discovery + employer verify)
// unless a connector is provided at runtime.
import type { Card, SourceAdapter, DiscoverContext } from '../types.js';
import { workModeFrom } from '../admissibility.js';
import { fetchGuarded } from './http.js';

/** One employer's board, as the run config lists it.
 *
 * `company` is the DISPLAY NAME and is required. A board slug is a lowercase
 * identifier, and A4 defines `Company / Outreach Account` as the employer that
 * hires -- the value colleagues read and the key dedup runs on. Letting the slug
 * through would create a second row for an employer already present under its
 * real name, which is the BoF Careers failure arriving by another route.
 *
 * `kind` names only what has a branch below. It used to declare 'ashby' and
 * 'workable' too, and a board of either kind fell through the if/else, returned
 * nothing and reported nothing. Ashby is reachable as employer.ts::ashbyBoard,
 * which is a plain function rather than a SourceAdapter.
 */
export interface AtsBoard {
  kind: 'greenhouse' | 'lever';
  board: string;
  company: string;
}

const HOSTS = {
  greenhouse: 'https://boards-api.greenhouse.io',
  lever: 'https://api.lever.co',
};

const KNOWN_KINDS: readonly string[] = Object.keys(HOSTS);

/**
 * Which kinds declare a work mode in their API.
 *
 * A1 §44's `fully-remote` ground can only fire on a declaration (A1 §46), so a
 * kind that does not declare one cannot be excluded at the card stage: the
 * ground stays dead for that entire branch. `runPipeline` reports this per run
 * rather than leaving it to be rediscovered, because "which grounds are live
 * here" is not visible in the output otherwise.
 *
 * Greenhouse is `false` on evidence, not for want of looking (probed
 * 2026-09-24). Its board API returns no workplace field — `metadata` was empty
 * on all 692 Stripe postings — so the only signal is `location.name`, and on
 * that same board it appeared in 83 distinct spellings, mostly MULTI-LOCATION:
 * "San Francisco, Seattle, New York, Chicago, Remote in the US". A1 excludes
 * "lavoro **interamente** da remoto", and remote-as-one-option is not that. A
 * substring test would exclude the wrong roles in one direction and miss the
 * rest in the other, silently.
 */
export const WORK_MODE_DECLARABLE: Record<AtsBoard['kind'], boolean> = {
  lever: true,
  greenhouse: false,
};

export function atsAdapter(boards: AtsBoard[], opts: { baseUrl?: string } = {}): SourceAdapter {
  // Refused at construction, not skipped per board. A kind with no branch used to
  // fall through the if/else below, so the source reported `ok` with zero cards
  // and nothing said the board had never been queried. Thrown here rather than
  // logged mid-sweep: a misconfigured run should die before it spends a sweep,
  // and the message names what is implemented.
  const unknown = boards.filter((b) => !KNOWN_KINDS.includes(b.kind));
  if (unknown.length) {
    throw new Error(
      `ats: no branch for kind=${unknown.map((b) => b.kind).join(', ')}; ` +
        `implemented: ${KNOWN_KINDS.join(', ')}`,
    );
  }

  return {
    id: 'ats',
    async discover(queries: string[], ctx: DiscoverContext): Promise<Card[]> {
      const out: Card[] = [];
      for (const b of boards) {
        if (ctx.stop.stopped) return out;
        const host = opts.baseUrl ?? HOSTS[b.kind];
        try {
          if (b.kind === 'greenhouse') {
            const res = await fetchGuarded(`${host}/v1/boards/${b.board}/jobs?content=false`, ctx.guard);
            if (!res.ok) continue;
            const data = JSON.parse(res.text) as { jobs?: Array<{ id: number; title: string; location?: { name?: string }; absolute_url: string }> };
            for (const j of data.jobs || []) {
              if (!queries.some((q) => matchQuery(q, `${j.title}`))) continue;
              // No `workMode`, deliberately: this API does not declare one. See
              // WORK_MODE_DECLARABLE above — `location.name` is free text and
              // reading it would be the marker-list failure. An absent value is
              // A1 §46's undeclared, which excludes nothing.
              out.push({
                title: j.title,
                company: b.company,
                location: j.location?.name || 'To verify',
                url: j.absolute_url,
                snippet: '',
                sourceJobId: String(j.id),
                source: 'employer',
                discoveryQuery: `ats:${b.board}`,
              });
            }
          } else if (b.kind === 'lever') {
            const res = await fetchGuarded(`${host}/v0/postings/${b.board}?mode=json`, ctx.guard);
            if (!res.ok) continue;
            const data = JSON.parse(res.text) as Array<{
              id: string;
              text: string;
              categories?: { location?: string };
              /** Probed 2026-09-24 on a live board: `onsite|hybrid|remote`, the
               *  API's own closed vocabulary. A1 §44's `fully-remote` ground has
               *  something to read here, so this branch declares it. */
              workplaceType?: string;
              hostedUrl: string;
            }>;
            for (const j of data || []) {
              if (!queries.some((q) => matchQuery(q, j.text))) continue;
              out.push({
                title: j.text,
                company: b.company,
                location: j.categories?.location || 'To verify',
                url: j.hostedUrl,
                snippet: '',
                sourceJobId: j.id,
                source: 'employer',
                discoveryQuery: `ats:${b.board}`,
                workMode: workModeFrom(j.workplaceType),
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
