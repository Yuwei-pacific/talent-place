// The deterministic half of a search run: fan out the queries, discover, then
// geo / dedup / prefilter.
//
// Everything here is mechanical. The half that is NOT mechanical — reading each
// surviving description and judging it against A1 and the Master's A2 — is the
// agent's job and deliberately has no code path in this file.
//
// Before this existed, that deterministic half lived in a throwaway script
// outside the repo. The 2026-09-17 run took ~63 min and none of its shape was
// reproducible: the query fan-out, the false-friend list, the topK, the sleep
// between requests were all invented in the moment and discarded with the file.
import type { Card, SourceAdapter } from './types.js';
import type { ScoredCard } from './prefilter.js';
import { geoFilter } from './geo.js';
import { dedupCards } from './dedup-cards.js';
import { prefilter } from './prefilter.js';
import { runDiscovery, DEFAULT_CAP, type RunOptions, type SourceReport } from './discovery/run.js';

export interface PipelineConfig {
  masterId: string;
  edition: string;
  /** A2 area name -> that area's search terms, verbatim from the profile. */
  areas: Record<string, string[]>;
  /** Combined with every area term to bias the fan-out toward student roles. */
  internshipTerms: string[];
  locations: string[];
  /** A2's stated false positives. Scored down, never silently dropped. */
  falseFriends: string[];
  /** Cards kept after scoring. The rest stay in `dropped`, never discarded. */
  topK: number;
  rates?: Record<string, number>;
  cap?: number;
}

export interface TaggedCard extends Card {
  /** A2 areas the query that found this card belonged to. */
  areas: string[];
  /** Every query that surfaced it, deduped. */
  queries: string[];
}

export interface PipelineResult {
  queries: string[];
  cards: TaggedCard[];
  kept: TaggedCard[];
  dropped: TaggedCard[];
  /** Cards dropped for being outside the admitted geography. */
  droppedNonEu: Card[];
  /** Roles already in the canonical history or in Review.xlsx. */
  duplicates: Card[];
  report: SourceReport[];
  counters: {
    queriesTried: number;
    cardsSeen: number;
    afterGeo: number;
    afterDedup: number;
    duplicates: number;
    kept: number;
    dropped: number;
  };
}

/** The (query, area) fan-out. A1: combine activity terms with internship terms;
 *  never run only the first term of a list. */
export function buildQueries(cfg: PipelineConfig): Array<{ query: string; area: string }> {
  const out: Array<{ query: string; area: string }> = [];
  for (const [area, terms] of Object.entries(cfg.areas)) {
    for (const t of terms) {
      for (const suffix of cfg.internshipTerms) {
        out.push({ query: `${t} ${suffix}`.trim(), area });
      }
    }
  }
  return out;
}

/**
 * Tag a card with every area whose query produced it.
 *
 * A card found by two queries is genuinely in both areas, and `dedupCards`
 * records that by joining the queries with ' + '. So the match has to be per
 * SEGMENT, not a prefix of the whole string: matching the whole string only
 * ever credits the first query, which silently drops the second area from
 * `Master-fit Themes` in the output. Adaptors also append their own location
 * to each segment, so the comparison is a prefix within the segment.
 */
export function tagCards(cards: Card[], pairs: Array<{ query: string; area: string }>): TaggedCard[] {
  // An adapter appends its own location to each segment ("<query> — <loc>"), so
  // the query is the segment's HEAD. Comparing with `startsWith` alone credited a
  // card to any area whose query is a prefix of another area's — harmless only
  // for as long as no A2 term list happens to collide, which is not a property
  // anyone maintains.
  const headOf = (segment: string): string => segment.split(' — ')[0];
  return cards.map((c) => {
    const segments = c.discoveryQuery.split(' + ').map(headOf);
    const areas: string[] = [];
    const queries: string[] = [];
    for (const { query, area } of pairs) {
      if (!segments.includes(query)) continue;
      if (!areas.includes(area)) areas.push(area);
      if (!queries.includes(query)) queries.push(query);
    }
    return { ...c, areas, queries };
  });
}

export interface PipelineDeps {
  /** Injected so the pipeline can be tested without a network. */
  historyDup?: (cards: Card[]) => { fresh: Card[]; duplicates: Card[] };
}

/**
 * Run the whole deterministic pipeline.
 *
 * Order matters and is asserted by the tests: geo first (a non-EU card should
 * not consume dedup work), then dedup, then prefilter. Dedup runs BEFORE
 * prefilter so that duplicates from the (query x location) fan-out do not
 * consume topK slots or the detail-reading budget.
 */
export async function runPipeline(
  adapters: SourceAdapter[],
  cfg: PipelineConfig,
  deps: PipelineDeps = {},
  runOpts: RunOptions = {},
): Promise<PipelineResult> {
  const pairs = buildQueries(cfg);
  const queries = [...new Set(pairs.map((p) => p.query))];

  const { cards, report } = await runDiscovery(adapters, queries, {
    cap: cfg.cap ?? DEFAULT_CAP,
    rates: cfg.rates,
    ...runOpts,
  });

  const { eu, droppedNonEu } = geoFilter(cards);
  const unique = dedupCards(eu).unique;
  const split = deps.historyDup ? deps.historyDup(unique) : { fresh: unique, duplicates: [] as Card[] };

  const scored = prefilter(split.fresh, {
    falseFriends: cfg.falseFriends,
    queryTerms: Object.values(cfg.areas).flat(),
    topK: cfg.topK,
  });

  const kept = tagCards(scored.kept.map((s: ScoredCard) => s.card), pairs);
  const dropped = tagCards(scored.dropped.map((s: ScoredCard) => s.card), pairs);

  return {
    queries,
    cards: tagCards(cards, pairs),
    kept,
    dropped,
    droppedNonEu,
    duplicates: split.duplicates,
    report,
    counters: {
      queriesTried: queries.length,
      cardsSeen: cards.length,
      afterGeo: eu.length,
      afterDedup: unique.length,
      duplicates: split.duplicates.length,
      kept: kept.length,
      dropped: dropped.length,
    },
  };
}
