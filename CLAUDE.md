# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Internship-search system for POLI.design Master's programmes. Two halves that must be kept in sync but change for different reasons:

- **`config/`** — the method (A1–A4) plus one profile per Master. Markdown/YAML, written in Italian, read by a human and by Claude during a search run. **This is the behavioural source of truth.**
- **`engine/`** — a TypeScript library of deterministic helpers (normalization, geo filtering, prefiltering, dedup, history lookup) plus Python CSV writers.

**There is no CLI and no `main()`.** Nothing in `engine/` runs a search end to end. A search run is *Claude Code itself* reading A1–A4 + the Master's A2/A3 and emitting a TSV, calling engine helpers and doing web fetches as it goes. Adding an engine entrypoint is a design change, not a missing feature.

## Commands

All from `engine/`:

```bash
npm run build       # tsc: src/ -> lib/
npm run typecheck   # tsc --noEmit
npm test            # runs build, then all 9 smoke tests in sequence
node test/geo-smoke.mjs   # single test — run `npm run build` first; tests import from lib/, not src/
```

`npm test` is not a test runner; it is a shell `&&` chain in `package.json`. To add a test you must also append it to that chain. Tests are plain `node:assert` scripts that `console.log('<name>: OK')` on success.

Three tests hit the live network (`aggregators-smoke`, `employer-smoke`, and `prefilter-smoke`/`history-smoke`/`dedup-cards-smoke` indirectly) and will fail without connectivity or when a scraped page's markup changes. `test/history-smoke.mjs` hardcodes an absolute path to the canonical CSV — it only passes on this machine.

## The A1–A4 method

| File | Governs | Scope |
|---|---|---|
| `A1-regole-ricerca.md` | Search method: sources, eligibility, verification, scoring | all Masters |
| `A2-profilo-<master>.md` | The programme's professional areas ("schede") | one per Master |
| `A3-cohort.yaml` | Student constraints, preferences, `history_file` pointer | one per edition |
| `A4-regole-registrazione.md` | Output format: TSV columns, Notes, Verification Status, Indeed accounting | all Masters |

`config/00-Talent placement&Design lab.md` is the human-facing guide and is **not** an agent input.

Precedence: A1 sets method, A2 sets the educational perimeter, A3 sets student conditions, A4 sets output. **A3 preferences never rewrite A2's perimeter.** A2 `master_id` must match A3's and the requested Master — if they disagree or one is missing, stop and ask rather than substituting a Master by analogy.

## Invariants the engine encodes

These are A1/A4 rules expressed as code. Changing one means changing a rule, so check the config first.

- **No label or score without a read description.** `labels.ts::decisionToA1` returns `non_risolto` when no reliable description exists, even if a score was passed. Score 0–100 is optional and only ever orders results; the qualitative label (`pertinente` / `adiacente` / `fuori profilo`) is what carries meaning.
- **Only `pertinente` and `adiacente` reach the main TSV.** `fuori profilo` goes to exclusions; unreliable ones go to unresolved.
- **History is read-only.** `history.ts` loads the canonical CSV; `python/add_verified.py` is the only writer and only runs on human-confirmed rows.
- **Never bypass login/CAPTCHA/rate limits.** `discovery/http.ts` classifies those as `blocked` and the ladder moves to another source. `BLOCKED_MARKERS` is deliberately narrow — `captcha` and `enable javascript to` appear on *legitimate* Ashby/Workday pages, so widening the list silently kills the whole employer branch.
- **Indeed accounting invariant:** `X = Y + Z + P` (unique found / included / excluded-or-duplicate / unresolved-outside-TSV), rendered by `observe.ts::indeedLine`.
- **Employer page beats portal page** for verification status (A1). A generic Careers page is never proof a specific role exists and is not a dedup key.

## Pipeline order (in the engine)

`Card` (a discovery hit) → `geoFilter` → `dedupCards` → `prefilter` → detail fetch/verify → `Role`. Dedup runs **before** prefilter so that duplicates from the (query × location) fan-out don't consume `topK` slots or detail budget.

Discovery adapters live in `src/discovery/`, each returning `Card[]` behind the `SourceAdapter` interface: LinkedIn public guest API, employer ATS JSON APIs (Greenhouse/Lever/Ashby/Workable), Ashby job boards, CercoLavoro public SERP, and a generic employer-page check. Indeed direct HTTP is 403 from datacenter clients, so Indeed stays a runtime-declared source (public web + employer verification) unless a connector is provided.

## Gotchas

- **`tsconfig.json` `include` is an explicit allowlist, not a glob.** A new `src/*.ts` file will silently not compile until it is added there. The existing `include` is the authoritative list of live modules.
- **`lib/` is gitignored build output that the tests import.** A fresh clone must `npm install` before anything runs, and editing `src/` without rebuilding leaves tests running the old code — this is why `npm test` runs `build` first.
- Imports use NodeNext ESM, so intra-repo specifiers end in `.js` even in `.ts` files (`from './types.js'`).
- **Dead code:** `src/reference/constraints.ts` and `src/reference/dedup.ts` have no live counterpart — `src/reference/types.ts` doesn't exist and neither file is in `tsconfig`'s include. Nothing imports them. Don't resurrect or import from them; the live dedup is `src/dedup-cards.ts` + `src/normalize.ts`.
- `python/io.py` is legacy xlsx-workbook tooling (docstring still says `poli-job-desk`) and its `COMPANY_HEADERS` lists only **20** columns, omitting `First Contact Date` and `Recall`. A4 specifies **22**. Its headers are not the current contract.
- The canonical CSV is **semicolon**-delimited; TSV output is **tab**-delimited. `index/Strategic_Design_Company_Index.csv` has 22 real header columns followed by trailing empty columns inherited from the original xlsx export — don't treat those as real.
- In the TSV, columns 1–20 are mandatory; 21–22 (`First Contact Date`, `Recall`) are production extensions: leave empty for new roles, but preserve them when updating an existing row. Every row must have exactly as many tabs as the header.

## Where changes go

| Change | Location |
|---|---|
| Matching/eligibility/verification rules | `config/A1-*.md` / `A4-*.md` — not code |
| A Master's professional areas | `config/<Master> ED.NN>/A2-profilo-*.md` |
| Cohort constraints, `history_file` | `config/<Master> ED.NN>/A3-cohort.yaml` |
| A new discovery source | `src/discovery/` + add to `tsconfig` `include` + a `test/*-smoke.mjs` appended to the `package.json` chain |
| A canonical-history write rule | `python/add_verified.py` (human-confirmed rows only) |

Do not add a new config file per search run (A4) and do not create a second copy of A2/A3 content elsewhere.
