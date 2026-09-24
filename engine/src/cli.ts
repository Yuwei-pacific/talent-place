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
import { runVerification, parseTargets } from './verify.js';
import { newCounters, indeedLine, exclude } from './observe.js';
import { admissibilityVerdict, isWorkMode, WORK_MODES } from './admissibility.js';

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

/** History matching, so the run never re-proposes a role the record already
 *  carries. One source: the CSV `export-history` renders from Review.xlsx. A
 *  card found in it is a duplicate. */
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
  if (r.unresolved.length) lines.push(`  unattrib. ${r.unresolved.length} posted by a board or agency, not an employer (A1 §Fonti)`);
  if (r.excluded.length) {
    const byGround = new Map<string, number>();
    for (const e of r.excluded) byGround.set(e.ground, (byGround.get(e.ground) ?? 0) + 1);
    lines.push(`  excluded  ${r.excluded.length} by A1 §44: ${[...byGround].map(([g, n]) => `${g} ${n}`).join(', ')}`);
  }
  if (r.workModeUndeclarable.length) {
    lines.push(
      `  coverage  work mode not declarable by: ${r.workModeUndeclarable.join(', ')}` +
        ` — A1 §44 fully-remote cannot fire on those boards, only in admit`,
    );
  }
  if (r.aggregatorTable.missing) lines.push(`  WARNING   aggregator table not found at ${r.aggregatorTable.source}`);
  const inert = Object.entries(r.aggregatorHits).filter(([, n]) => n === 0).map(([p]) => p);
  if (inert.length) lines.push(`  inert     aggregator entries that never fired: ${inert.join(', ')}`);
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

const USAGE = [
  'usage:',
  '  node lib/cli.js discover --config <run.json> --out <dir> [--history <exported history.csv>]',
  '  node lib/cli.js verify   --urls <list.txt>  --out <dir>',
  '  node lib/cli.js admit    --fields <declared.json> --out <dir>',
  '  node lib/cli.js indeed   --status Used|Unavailable --x N --y N --z N [--p N] [--note "<perché>"]',
  '',
  'verify reads one URL per line (optionally "label;url"), probes each on the',
  'employer side, and writes employer-checks.csv with an A4 Verification Status',
  'per URL. It answers "is this page alive / does it mention a stage / is there',
  'an apply path"; it does not judge whether a role suits a student.',
  '',
  'admit applies A1 §Ammissibilità to the fields a read established and writes',
  'exclusions.json. It exists because that rule had no home: the 2026-09-22 run',
  'carried a hand-written `work_mode == "remote"` gate in a script outside this',
  'repo, which is the only reason the Zenesis role did not reach Review.xlsx, and',
  'the next run had no such gate. Declared fields only — A1 §46 keeps an',
  'undeclared field uncertain, so only a declaration can exclude.',
  '',
  'indeed prints A4\'s mandatory Indeed line and refuses when X != Y + Z + P. It',
  'exists so the run computes that line instead of composing it by hand: the',
  'invariant was implemented and never ran, so the arithmetic A4 requires was',
  'never actually checked. A4 §58 defines the format, §60 the P term.',
].join('\n');

/**
 * A1 §Ammissibilità, applied to the fields a read established.
 *
 * JSON rather than a CSV, for the same reason `--config` is JSON: this is an
 * input an operator or an agent writes, and a JSON key cannot hide inside a cell
 * the way a separator-delimited one can. A missing key is also detectable
 * directly, which is the lesson `stage`'s missing-column guard was built on — a
 * column that reads as empty rather than failing is how a rule becomes silent.
 */
function cmdAdmit(args: Record<string, string>): number {
  if (!args.fields || !args.out) {
    process.stderr.write('admit needs --fields and --out\n');
    return 2;
  }
  const fieldsPath = resolve(args.fields);
  const raw = JSON.parse(readFileSync(fieldsPath, 'utf-8')) as Record<string, unknown>;

  // Refuse rather than guess, and report EVERY problem: a caller that fixes one
  // field per attempt learns nothing about the shape it got wrong.
  const problems: string[] = [];
  const strList = (v: unknown, where: string): string[] => {
    if (v === undefined || v === null) return [];
    if (!Array.isArray(v) || v.some((x) => typeof x !== 'string')) {
      problems.push(`${where} must be an array of strings`);
      return [];
    }
    return v as string[];
  };
  const admittedLanguages = strList(raw.admittedLanguages, 'admittedLanguages');
  if (!Array.isArray(raw.roles)) problems.push('roles must be an array');
  const roles = Array.isArray(raw.roles) ? (raw.roles as Array<Record<string, unknown>>) : [];
  roles.forEach((r, i) => {
    const where = `roles[${i}]`;
    if (typeof r?.title !== 'string' || !r.title.trim()) problems.push(`${where}.title is required`);
    if (typeof r?.url !== 'string' || !r.url.trim()) problems.push(`${where}.url is required`);
    // The closed set, refused rather than coerced. A value outside it would
    // never fire, and would sit in the run looking like a field that was checked
    // — which is precisely the failure this whole command exists to end.
    if (r?.workMode !== undefined && !(typeof r.workMode === 'string' && isWorkMode(r.workMode))) {
      problems.push(
        `${where}.workMode must be one of ${WORK_MODES.join('|')}, got ${JSON.stringify(r.workMode)}`,
      );
    }
    if (r?.applicationOpen !== undefined && typeof r.applicationOpen !== 'boolean') {
      problems.push(`${where}.applicationOpen must be true or false, got ${JSON.stringify(r.applicationOpen)}`);
    }
    strList(r?.requiredLanguages, `${where}.requiredLanguages`);
  });
  if (problems.length) {
    process.stderr.write(`admit refused ${fieldsPath}:\n${problems.map((p) => `  ${p}\n`).join('')}`);
    return 2;
  }

  const counters = newCounters();
  const excluded: Array<{ url: string; company: string; title: string; ground: string; detail: string }> = [];
  for (const r of roles) {
    const v = admissibilityVerdict({
      title: r.title as string,
      workMode: r.workMode as string | undefined,
      applicationOpen: r.applicationOpen as boolean | undefined,
      requiredLanguages: (r.requiredLanguages as string[] | undefined) ?? [],
      // Per-role wins when a role carries its own, otherwise A3's list decides.
      admittedLanguages: (r.admittedLanguages as string[] | undefined) ?? admittedLanguages,
    });
    if (v.verdict === 'ammissibile') continue;
    // `observe.exclude` is the run-level per-rule counter A4's exclusion
    // reporting is built from. It was written and had no caller until here.
    exclude(counters, v.ground);
    excluded.push({
      url: r.url as string,
      company: (r.company as string) ?? '',
      title: r.title as string,
      ground: v.ground,
      detail: v.detail,
    });
  }

  const outDir = resolve(args.out);
  mkdirSync(outDir, { recursive: true });
  writeFileSync(
    join(outDir, 'exclusions.json'),
    JSON.stringify(
      {
        generatedBy: 'admit',
        fields: fieldsPath,
        counts: {
          rows: roles.length,
          ammissibile: roles.length - excluded.length,
          escluso: excluded.length,
          excludedPerRule: counters.excludedPerRule,
          languagesAdmitted: admittedLanguages,
        },
        excluded,
      },
      null,
      1,
    ) + '\n',
  );

  // A4: show up to five motivated examples. More than five hides the pattern
  // behind the volume; fewer than all of them keeps the stdout readable and the
  // full list in the file.
  const byGround = Object.entries(counters.excludedPerRule);
  process.stdout.write(
    `admit ${roles.length} role(s): ${roles.length - excluded.length} ammissibile, ${excluded.length} escluso\n` +
      byGround.map(([g, n]) => `  ${g.padEnd(20)} ${n}\n`).join('') +
      excluded.slice(0, 5).map((e) => `  - ${e.title} [${e.ground}] ${e.detail}\n`).join('') +
      (excluded.length > 5 ? `  … ${excluded.length - 5} more in exclusions.json\n` : '') +
      `  wrote ${outDir}/exclusions.json\n`,
  );
  return 0;
}

/** A4's Indeed line. The invariant lives in `observe.ts`; this is its caller. */
function cmdIndeed(args: Record<string, string>): number {
  const num = (key: string): number => {
    const raw = args[key];
    if (raw === undefined) return 0;
    const n = Number(raw);
    if (!Number.isInteger(n) || n < 0) {
      throw new Error(`--${key} must be a non-negative integer, got ${JSON.stringify(raw)}`);
    }
    return n;
  };
  const counters = newCounters();
  // A4 §58: the states stay English and there are exactly two of them. Refused
  // rather than defaulted, so a typo cannot produce a line asserting a state the
  // run never reached.
  const status = args.status ?? 'Unavailable';
  if (status !== 'Used' && status !== 'Unavailable') {
    throw new Error(`--status must be Used or Unavailable, got ${JSON.stringify(status)}`);
  }
  counters.indeedStatus = status;
  counters.indeedNote = args.note ?? '';
  counters.indeedX = num('x');
  counters.indeedY = num('y');
  counters.indeedZ = num('z');
  counters.indeedP = num('p');
  process.stdout.write(indeedLine(counters) + '\n');
  return 0;
}

/** `verify` — the cheap employer probe, as a batch. */
async function cmdVerify(args: Record<string, string>): Promise<number> {
  if (!args.urls || !args.out) {
    process.stderr.write('verify needs --urls and --out\n');
    return 2;
  }
  const targets = parseTargets(readFileSync(resolve(args.urls), 'utf-8'));
  if (targets.length === 0) {
    process.stderr.write(`no URLs found in ${args.urls}\n`);
    return 2;
  }
  const outDir = resolve(args.out);
  mkdirSync(outDir, { recursive: true });

  const { results, report } = await runVerification(targets, {
    width: args.width ? Number(args.width) : undefined,
    ratePerSec: args.rate ? Number(args.rate) : undefined,
  });

  const cell = (v: unknown) => String(v).replace(/[\t\r\n;]+/g, ' ').trim();
  const header = 'url;label;status;reachable;has_apply;has_intern_signal;title;detail;elapsed_ms';
  const body = results.map((r) =>
    [r.url, r.label, r.status, r.reachable, r.hasApply, r.hasInternSignal, r.title, r.detail, r.elapsedMs]
      .map(cell)
      .join(';'),
  );
  writeFileSync(join(outDir, 'employer-checks.csv'), [header, ...body].join('\n') + '\n');

  process.stdout.write(
    `verified ${report.targets} URL(s) in ${(report.elapsedMs / 1000).toFixed(1)}s\n` +
      `  Employer verified active : ${report.verifiedActive}\n` +
      `  To verify                : ${report.toVerify}\n` +
      `  Blocked                  : ${report.blocked}\n` +
      `  requests ${report.health.requests} (ok ${report.health.ok}, 429 ${report.health.blocked429}, 403 ${report.health.blocked403})\n` +
      `  wrote ${outDir}/employer-checks.csv\n`,
  );
  return 0;
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2);
  const cmd = argv[0];
  const args = parseArgs(argv.slice(1));

  const COMMANDS = ['discover', 'verify', 'admit', 'indeed'];
  if (args.help || !cmd || !COMMANDS.includes(cmd)) {
    process.stderr.write(USAGE + '\n');
    return cmd && COMMANDS.includes(cmd) ? 0 : 2;
  }
  if (cmd === 'verify') return cmdVerify(args);
  if (cmd === 'admit') return cmdAdmit(args);
  if (cmd === 'indeed') return cmdIndeed(args);

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
    // Employer boards from the run config. Absent means the run stays on
    // LinkedIn alone, which is what every run before 2026-09-22 did.
    atsBoards: cfg.atsBoards,
  });
  const result = await runPipeline(adapters, cfg, { historyDup: historySplit(args.history) });

  writeFileSync(join(outDir, 'cards.json'), JSON.stringify(result.kept, null, 1));

  // Per-role evidence that A4's fixed 22-column TSV has nowhere to put. `stage`
  // reads it back with --evidence and fills Roles.xlsx's `Posted / Result Age`,
  // `Search Query` and `Alternate / Portal URLs`. Without it those columns are
  // declared unrecoverable and stay empty, which is how the freshness signal
  // A1 asks for ("verify the opportunity is current") got lost entirely.
  //
  // Semicolon-delimited like the canonical CSV; cells are stripped of tabs and
  // newlines so a value can never break the row.
  const cell = (v: string) => v.replace(/[\t\r\n;]+/g, ' ').trim();
  const evidence = [
    ['url', 'posted', 'alternate_urls', 'search_query'].join(';'),
    ...result.kept.map((c) =>
      [cell(c.url), cell(c.posted ?? ''), cell((c.alternateUrls ?? []).join(' | ')), cell(c.discoveryQuery)].join(';'),
    ),
  ];
  writeFileSync(join(outDir, 'role-evidence.csv'), evidence.join('\n') + '\n');
  writeFileSync(
    join(outDir, 'dropped.json'),
    JSON.stringify(
      {
        prefilterDropped: result.dropped,
        nonEu: result.droppedNonEu,
        // A1 §Fonti: not attributed to the board, and not discarded either.
        unresolved: result.unresolved,
        // A1 §44: excluded, with the ground. Deliberately its own key rather
        // than folded into `prefilterDropped` — A4 requires that incompatibility,
        // duplication and unreliability not be confused with one another.
        excluded: result.excluded,
        duplicates: result.duplicates,
      },
      null,
      1,
    ),
  );

  // A4's per-rule exclusion reporting. `exclude` is the accumulator that was
  // written for this and had no caller; the run is where it belongs, because the
  // run is what carries the counters.
  const counters = newCounters();
  for (const e of result.excluded) exclude(counters, e.ground);

  writeFileSync(
    join(outDir, 'run-report.json'),
    JSON.stringify(
      {
        config: cfg,
        counters: result.counters,
        sources: result.report,
        falseFriendHits: result.falseFriendHits,
        aggregatorHits: result.aggregatorHits,
        aggregatorTable: result.aggregatorTable,
        excludedPerRule: counters.excludedPerRule,
        // What this run could NOT gate, said out loud. A1's duty is to declare
        // coverage, and a ground that is dead for a whole branch is coverage.
        workModeUndeclarable: result.workModeUndeclarable,
      },
      null,
      1,
    ),
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
