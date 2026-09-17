// The run driver — the piece that was missing.
//
// Before this file, every adapter in this directory was an UNCALLED library:
// `grep -rn '\.discover(' src/` returned zero hits, and so did `indeedLine`,
// `geoFilter`, `dedupCards` and `prefilter`. The one time a search actually
// ran (Strategic Design ED.28, 2026-09-17, ~63 min) the loop lived in a
// throwaway script outside the repo, so nothing about it was reproducible,
// testable, or fixable in place.
//
// What this driver owns:
//   * one limiter, one StopToken and one health record PER SOURCE, created
//     fresh here and never stored in a module global — a global leaks rate and
//     stop state across runs and across tests, which is how "it passed
//     yesterday" happens;
//   * a report saying what each source did and why it stopped, which is the
//     A1/A4 "declare the reason" obligation expressed as a return value rather
//     than an exception nobody catches.
//
// Concurrency lives here as POOL WIDTH, never as a rate. Each source keeps its
// own limiter, so running sources (or query pairs within a source) in parallel
// changes how many requests are outstanding and never how often one leaves.
// `test/ratelimit-width-invariance.mjs` asserts that, because the failure mode
// is a "faster" run that is simply less polite.
//
// What it still deliberately does NOT own: any rate ramp. See the header of
// ../ratelimit.ts for why that absence is load-bearing.
import type { Card, SourceAdapter } from '../types.js';
import type { Guard, SourceHealth, StopKind } from '../ratelimit.js';
import { RateLimiter, mapPool, newSourceHealth, newStopToken, stopSource } from '../ratelimit.js';
import { linkedinGuestAdapter } from './linkedin-guest.js';

/**
 * Per-source request rates, in requests/second.
 *
 * These are CONSERVATIVE CHOICES, not descriptions of current behaviour. This
 * engine previously had no rate at all — `fetchText` sets no delay and the
 * adapters await serially, so at ~300ms p50 the LinkedIn guest adapter ran at
 * roughly 3.3 req/s. 0.625 is deliberately far below that. Do not "restore"
 * the old number: it was never a decision, it was the absence of one.
 */
export const DEFAULT_RATES: Record<string, number> = {
  'linkedin-guest': 0.625, // 1600ms gap
  ats: 2, // documented public JSON APIs, meant to be polled
  employer: 2,
};

export interface SourceReport {
  id: string;
  status: 'ok' | 'blocked' | 'error' | 'capped';
  cards: number;
  reason: string;
  elapsedMs: number;
  health: SourceHealth;
}

/**
 * Runaway guard, NOT a budget.
 *
 * The old adapter returned early at 200 cards, which read as harmless because
 * the throwaway driver called `discover` once per query — the counter reset
 * every time and the cap never fired. Driving all queries through ONE call (as
 * the CLI does) made it fire after 20 of 72 queries and silently cost most of
 * the fan-out. A query x location pair yields 10 cards, so a 72-query fan-out
 * legitimately reaches ~720; a cap that truncates that is a recall bug wearing
 * a safety costume. The real budgets are `topK` after scoring and how many
 * descriptions the agent can read.
 */
export const DEFAULT_CAP = 5000;

export interface RunOptions {
  rates?: Record<string, number>;
  cap?: number;
  /** How many SOURCES may run at once. Each keeps its own limiter, so this
   *  cannot raise any single source's request rate — it only stops a slow
   *  source from idling the ones behind it. Default 3. */
  sourceWidth?: number;
  /** Test seam: build a source's guard yourself. */
  guardFor?: (id: string, limiter: RateLimiter) => Guard;
}

export interface RunResult {
  cards: Card[];
  report: SourceReport[];
}

function statusOf(kind: StopKind): SourceReport['status'] {
  switch (kind) {
    case 'blocked':
      return 'blocked';
    case 'error':
      return 'error';
    case 'cap':
      return 'capped';
    default:
      return 'ok';
  }
}

/**
 * Run every adapter and collect the cards that survive.
 *
 * Never rejects. An adapter that throws is caught, its source is marked
 * stopped with the error as the reason, and every OTHER source still runs —
 * one source failing must not cost the run.
 */
export async function runDiscovery(
  adapters: SourceAdapter[],
  queries: string[],
  opts: RunOptions = {},
): Promise<RunResult> {
  const cap = opts.cap ?? DEFAULT_CAP;

  // One limiter, one StopToken and one health record PER SOURCE, built here and
  // never stored in a module global: a global leaks rate and stop state across
  // runs and across tests. Sources run concurrently because each carries its
  // own limiter — that is what makes a throttled source unable to stall a
  // healthy one, and why `sourceWidth` cannot raise any single source's rate.
  const runs = await mapPool(adapters, opts.sourceWidth ?? 3, async (adapter) => {
    const limiter = new RateLimiter({ ratePerSec: opts.rates?.[adapter.id] ?? DEFAULT_RATES[adapter.id] ?? 1 });
    const stop = newStopToken();
    const health = newSourceHealth();
    const guard: Guard = opts.guardFor?.(adapter.id, limiter) ?? { limiter, stop, health };
    const t0 = Date.now();
    let got: Card[] = [];
    try {
      got = await adapter.discover(queries, { guard, stop, cap });
    } catch (err) {
      stopSource(stop, 'error', err instanceof Error ? err.message : String(err));
      got = [];
    }
    return {
      cards: got,
      report: {
        id: adapter.id,
        status: statusOf(stop.kind),
        cards: got.length,
        reason: stop.reason,
        elapsedMs: Date.now() - t0,
        health,
      } satisfies SourceReport,
    };
  });

  return { cards: runs.flatMap((r) => r.cards), report: runs.map((r) => r.report) };
}

/**
 * The live source set: LinkedIn's public guest API, plus ATS boards when the
 * caller has tokens for them.
 *
 * CercoLavoro is deliberately absent. On the 2026-09-17 run it produced 10
 * candidates from ~160 requests and NONE survived triage (9 `fuori profilo`,
 * 1 `non_risolto`), while costing 7 of the 11.6 sweep minutes — roughly 25x
 * worse yield per request than LinkedIn. Its candidates were a classifieds
 * board's: a dog sitter, cleaning staff, a sysadmin. The parser and its
 * fixture test are kept; only the driver stops calling it.
 */
export function defaultAdapters(opts: {
  linkedinLocations: string[];
  /** Test/ops seam: point the adapter at a local server instead of linkedin.com. */
  linkedinBaseUrl?: string;
}): SourceAdapter[] {
  return [linkedinGuestAdapter(opts.linkedinLocations, { baseUrl: opts.linkedinBaseUrl })];
}
