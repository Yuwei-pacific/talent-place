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
import { WORK_MODE_DECLARABLE, type AtsBoard } from './discovery/ats.js';
import { geoFilter } from './geo.js';
import { dedupCards } from './dedup-cards.js';
import { prefilter } from './prefilter.js';
import { admissibilityVerdict, type AdmissibilityGround } from './admissibility.js';
import { loadAggregators, defaultAggregatorPath, aggregatorFor, type AggregatorTable } from './attribution.js';
import { runDiscovery, DEFAULT_CAP, type RunOptions, type SourceReport } from './discovery/run.js';

export interface PipelineConfig {
  masterId: string;
  edition: string;
  /** A2 area name -> that area's search terms, verbatim from the profile. */
  areas: Record<string, string[]>;
  /** Combined with every area term to bias the fan-out toward student roles. */
  internshipTerms: string[];
  locations: string[];
  /** A2's stated false positives, copied verbatim from that profile's `termini:`
   *  lines (A1, Valutazione). Scored down, never silently dropped. */
  falseFriends: string[];
  /** Employer ATS boards to poll under `source: 'employer'`. Absent means no
   *  `ats` source at all. A board carries its employer's DISPLAY name, because
   *  its slug must never reach `Company / Outreach Account` — see ats.ts. */
  atsBoards?: AtsBoard[];
  /** Cards kept after scoring. The rest stay in `dropped`, never discarded. */
  topK: number;
  /** The languages A3 admits. Absent means undeclared, and A1 §46 then excludes
   *  nothing on language — that ground needs both sides to say something. */
  admittedLanguages?: string[];
  /** Known boards and agencies. Absent reads `engine/data/aggregators.csv`. */
  aggregators?: string;
  rates?: Record<string, number>;
  cap?: number;
}

export interface TaggedCard extends Card {
  /** A2 areas the query that found this card belonged to. */
  areas: string[];
  /** Every query that surfaced it, deduped. */
  queries: string[];
}

/** A card A1 §44 excluded, with the ground that fired. The ground is the reason
 *  A4 requires ("mostrare fino a cinque esempi motivati") and the key the run's
 *  `excludedPerRule` counter is built from. */
export interface ExcludedCard {
  card: Card;
  ground: AdmissibilityGround;
  detail: string;
}

export interface PipelineResult {
  queries: string[];
  cards: TaggedCard[];
  kept: TaggedCard[];
  dropped: TaggedCard[];
  /** Cards dropped for being outside the admitted geography. */
  droppedNonEu: Card[];
  /** Cards whose poster is a discovery source rather than an employer (A1
   *  §Fonti). Not attributed to the board, and not discarded either: A1 says the
   *  candidate "resta non risolto", which is a named exit the agent can act on.
   *  `card.poster` holds the board's name for `Sources / Portals`. */
  unresolved: Card[];
  /** Cards A1 §44 excludes, each with the ground that fired. Separate from
   *  droppedNonEu (geography) and from prefilter's `dropped` (relevance): A4
   *  requires that incompatibility, duplication and unreliability not be
   *  confused with one another. */
  excluded: ExcludedCard[];
  /** Cards matching a false friend. Reported per term so a list that cannot
   *  fire is visible instead of merely populated — see prefilter.ts. */
  falseFriendHits: Record<string, number>;
  /** The same remedy for the aggregator table: hit counts per entry, so an entry
   *  that stopped firing says so rather than sitting there looking like cover. */
  aggregatorHits: Record<string, number>;
  /** Where the aggregator table came from, and whether it was there at all.
   *  "missing" and "empty" are different answers. */
  aggregatorTable: { source: string; missing: boolean };
  /** Board kinds on this run whose API cannot declare a work mode, so A1 §44's
   *  `fully-remote` ground cannot fire against them at this stage and is left to
   *  `admit`. Derived from the boards actually configured, so it cannot claim a
   *  coverage the run does not have — and reported at all because "which grounds
   *  are live on this run" is invisible in the output otherwise. */
  workModeUndeclarable: string[];
  /** Roles already in the canonical history or in Review.xlsx. */
  duplicates: Card[];
  report: SourceReport[];
  counters: {
    queriesTried: number;
    cardsSeen: number;
    afterGeo: number;
    unresolved: number;
    excluded: number;
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
  /** Injected so a test needs no file on disk. Defaults to the table that ships
   *  with the engine. */
  aggregators?: AggregatorTable;
}

/**
 * Run the whole deterministic pipeline.
 *
 * Order matters and is asserted by the tests: geo, then the two A1 gates, then
 * dedup, then prefilter. Every stage that can remove a card runs before the one
 * that costs more — a non-EU card should not consume dedup work, an unattributable
 * one should not consume it either, and neither should occupy a topK slot or a
 * share of the detail-reading budget.
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

  // A1 §Fonti, before anything groups by company. An aggregator's name must not
  // reach `Company / Outreach Account`, and it must not reach the dedup keys
  // either — the two copies of the Italdesign CMF role carried different URLs and
  // different company names, so `dedupCards` could not have caught them.
  const table = deps.aggregators ?? loadAggregators(cfg.aggregators ?? defaultAggregatorPath());
  const aggregatorHits: Record<string, number> = {};
  for (const e of table.entries) aggregatorHits[e.pattern] = 0;
  const attributed: Card[] = [];
  const unresolved: Card[] = [];
  for (const c of eu) {
    const hit = aggregatorFor(c.company, table);
    if (!hit) {
      attributed.push(c);
      continue;
    }
    aggregatorHits[hit.pattern]++;
    // `company` is left as observed: it is the evidence the agent resolves the
    // real employer against. `poster` carries the board for `Sources / Portals`,
    // and the bucket — not an empty string — is what stops the attribution.
    unresolved.push({ ...c, poster: c.company });
  }

  // A1 §44, before the label is ever assigned. Zenesis was judged `pertinente`
  // on its merits and its own verdict recorded that it was inadmissible; nothing
  // between the read and the TSV evaluated §44, so it shipped.
  const excluded: ExcludedCard[] = [];
  const admissible: Card[] = [];
  for (const c of attributed) {
    const v = admissibilityVerdict({ ...c, admittedLanguages: cfg.admittedLanguages });
    if (v.verdict === 'ammissibile') admissible.push(c);
    else excluded.push({ card: c, ground: v.ground, detail: v.detail });
  }

  const unique = dedupCards(admissible).unique;
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
    unresolved,
    excluded,
    duplicates: split.duplicates,
    falseFriendHits: scored.falseFriendHits,
    aggregatorHits,
    aggregatorTable: { source: table.source, missing: table.missing },
    workModeUndeclarable: [
      ...new Set((cfg.atsBoards ?? []).filter((b) => !WORK_MODE_DECLARABLE[b.kind]).map((b) => b.kind)),
    ],
    report,
    counters: {
      queriesTried: queries.length,
      cardsSeen: cards.length,
      afterGeo: eu.length,
      unresolved: unresolved.length,
      excluded: excluded.length,
      afterDedup: unique.length,
      duplicates: split.duplicates.length,
      kept: kept.length,
      dropped: dropped.length,
    },
  };
}
