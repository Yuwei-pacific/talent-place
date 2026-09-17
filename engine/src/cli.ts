#!/usr/bin/env node
// The run entry point.
//
//   node lib/cli.js discover --config run.json --out <dir> [--history <csv>]
//
// This is the deterministic half of a search run, and it is the thing that did
// not exist before: the 2026-09-17 run drove the adapters from a throwaway
// script, so nothing about that run — the fan-out, the pacing, the reasons a
// source stopped — was reproducible or testable.
//
// It deliberately stops at the prefiltered card list. Reading each surviving
// description and judging it against A1 and the Master's A2 is the agent's job;
// encoding that here would put a judgement behind a `--flag`.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { resolve, join } from 'node:path';
import type { Card } from './types.js';
import { runPipeline, type PipelineConfig, type PipelineResult } from './pipeline.js';
import { defaultAdapters } from './discovery/run.js';
import { loadHistory, checkDup } from './history.js';

function parseArgs(argv: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      out[key] = next;
      i++;
    } else {
      out[key] = 'true';
    }
  }
  return out;
}

/** History matching, so the run never re-proposes a role the canonical CSV or
 *  Review.xlsx already carries. Both sources are read; a card found in either
 *  is a duplicate. */
function historySplit(csvPath: string | undefined) {
  if (!csvPath) return undefined;
  const history = loadHistory(resolve(csvPath));
  return (cards: Card[]) => {
    const fresh: Card[] = [];
    const duplicates: Card[] = [];
    for (const c of cards) {
      const v = checkDup(history, c.company, c.title, c.location, c.url);
      (v.dup ? duplicates : fresh).push(c);
    }
    return { fresh, duplicates };
  };
}

function summary(r: PipelineResult, masterId: string, edition: string): string {
  const c = r.counters;
  const lines: string[] = [];
  lines.push(`${masterId} ${edition}`);
  lines.push(`  queries   ${c.queriesTried}`);
  lines.push(`  cards     ${c.cardsSeen} seen -> ${c.afterGeo} in-scope -> ${c.afterDedup} unique -> ${c.duplicates} already known`);
  lines.push(`  kept      ${c.kept} (dropped by prefilter: ${c.dropped})`);
  if (r.droppedNonEu.length) lines.push(`  non-EU    ${r.droppedNonEu.length} dropped by geography`);
  lines.push('  sources:');
  for (const s of r.report) {
    const why = s.reason ? ` — ${s.reason}` : '';
    lines.push(
      `    ${s.id}: ${s.status}, ${s.cards} cards, ${s.elapsedMs}ms, ` +
        `${s.health.requests} requests (ok ${s.health.ok}, 429 ${s.health.blocked429}, 403 ${s.health.blocked403}, gone ${s.health.gone}, err ${s.health.errors})${why}`,
    );
  }
  return lines.join('\n');
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2);
  const cmd = argv[0];
  const args = parseArgs(argv.slice(1));

  if (cmd !== 'discover' || args.help) {
    process.stderr.write(
      'usage: node lib/cli.js discover --config <run.json> --out <dir> [--history <canonical.csv>]\n',
    );
    return cmd === 'discover' ? 0 : 2;
  }
  if (!args.config || !args.out) {
    process.stderr.write('discover needs --config and --out\n');
    return 2;
  }

  const cfg = JSON.parse(readFileSync(resolve(args.config), 'utf-8')) as PipelineConfig;
  const outDir = resolve(args.out);
  mkdirSync(outDir, { recursive: true });

  const adapters = defaultAdapters({
    linkedinLocations: cfg.locations,
    // Only ever set by tests and by an operator pointing at a local fixture.
    linkedinBaseUrl: args['linkedin-base'],
  });
  const result = await runPipeline(adapters, cfg, { historyDup: historySplit(args.history) });

  writeFileSync(join(outDir, 'cards.json'), JSON.stringify(result.kept, null, 1));
  writeFileSync(
    join(outDir, 'dropped.json'),
    JSON.stringify({ prefilterDropped: result.dropped, nonEu: result.droppedNonEu, duplicates: result.duplicates }, null, 1),
  );
  writeFileSync(
    join(outDir, 'run-report.json'),
    JSON.stringify({ config: cfg, counters: result.counters, sources: result.report }, null, 1),
  );

  process.stdout.write(summary(result, cfg.masterId, cfg.edition) + '\n');
  process.stdout.write(`  wrote ${outDir}/cards.json, dropped.json, run-report.json\n`);
  return 0;
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (err) => {
    process.stderr.write(`run failed: ${err instanceof Error ? err.message : String(err)}\n`);
    process.exitCode = 1;
  },
);
