# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Internship-search system for POLI.design Master's programmes. Two halves that must be kept in sync but change for different reasons:

- **`config/`** — the method (A1–A4) plus one profile per Master. Markdown/YAML, written in Italian, read by a human and by Claude during a search run. **This is the behavioural source of truth.**
- **`engine/`** — a TypeScript library of deterministic helpers (normalization, geo filtering, prefiltering, dedup, history lookup) plus two Python CLIs:
  - `python/sync_export.py` — publishes a run into a synced SharePoint folder, and reads colleagues' decisions back out
  - `python/add_verified.py` — appends human-confirmed TSV rows to the canonical CSV

**No CLI runs a search.** A search run is *Claude Code itself* reading A1–A4 + the Master's A2/A3 and emitting a TSV, calling engine helpers and doing web fetches as it goes. `sync_export.py` is the **publishing** half: it takes the TSV that a run produced and puts it where colleagues can review it. It does not discover anything.

## The publish/review loop (`sync_export.py`)

Search output used to be pasted into SharePoint by hand. It no longer is. Ownership is split **by file**, not by sheet:

| File | Owner | Machine behaviour |
|---|---|---|
| `Review.xlsx` | **colleagues** | reads freely; **appends new company rows only**, behind guards. Never regenerated. |
| `Roles.xlsx` | **machine** | regenerated wholesale every run: sheet `Roles` (one row per role) + `Company Summary` (one row per company, with the human columns copied in read-only) |
| `_machine/*.csv` | machine | plain-text diffable copies, no openpyxl |
| `_machine/backups/` | machine | pre-write copies of `Review.xlsx` and the canonical CSV |
| `Review-additions-<run>.csv` | machine | written **instead of** touching `Review.xlsx` when a guard refuses |

`Roles.xlsx` is **not** a review queue anyone merges — it is a rendering. That distinction matters: a machine file a human must merge back is just the paste step relocated.

A run's TSV is the **input contract for `stage`**, not a deliverable. Producing a TSV and stopping hands the paste step back to a human, which is the one thing this loop exists to remove: a run is not finished until `stage` (and `append`) have run against the Master's folder. Handing over a TSV and saying "now paste this" is the failure mode, not the fallback.

Command order for a weekly run:

```
doctor       verify the target dir (sync mount? dataless? Excel lock?)
stage        TSV -> Roles.xlsx + _machine/*.csv        (never touches Review.xlsx)
append       add genuinely-new companies to Review.xlsx
harvest      report what colleagues decided            (read-only audit)
pull         write their decisions into the canonical CSV
```

`init-review` (create `Review.xlsx`), `color` (install the status rules) and `backfill-ids` (add the `Company ID` column) are one-time setup.

### Why `append` is safe

It is the only command that writes into a file colleagues edit. Four rules, not "don't touch it":

1. **Append-only** — values go into *empty* cells at the bottom; no existing cell is ever overwritten
2. **Values only, never styles** — colour comes from conditional-formatting rules installed once by `color`, so the machine's recurring footprint is "add values to empty rows"
3. **Backup first**, then temp file + `os.replace` in the same directory
4. **Refuse rather than half-write** — on `~$` Excel lock, a dataless file, or a concurrent save it writes the sidecar and exits 0. A missed append costs one paste; a botched write costs a week.

The `~$` lock check is a **heuristic**: it sees a colleague editing on this machine, not one editing in Excel for the web, and OneDrive does not sync `~$` files. The pre-write backup is the actual safety net.

## Commands

All from `engine/`:

```bash
npm run build       # tsc: src/ -> lib/
npm run typecheck   # tsc --noEmit
npm test            # build, then 12 node smoke tests, then the Python suite

# single test — node tests import from lib/, so build first
node test/geo-smoke.mjs
python3 python/test_sync_export.py            # the whole Python suite
python3 python/test_sync_export.py TestAppend # one Python test class
python3 python/sync_export.py <cmd> --help
```

`npm test` is not a test runner; it is a shell `&&` chain in `package.json`. **To add a node test you must also append it to that chain** — nothing discovers it. Node tests are plain `node:assert` scripts that `console.log('<name>: OK')`. The Python suite is `unittest`, self-discovering within its one file.

Only `employer-smoke` hits the live network, and because the chain is `&&` its failure also prevents the Python suite from running. Everything else — including `aggregators-smoke` (checked-in fixture) and every timing test (local `node:http` server) — is offline.

### Running a search

```bash
npm run discover -- --config <run.json> --out <dir> [--history ../index/<Master>_Company_Index.csv]
```

`src/cli.ts` is the **deterministic half** of a run: query fan-out → discover → geo → dedup → prefilter → `cards.json` + `run-report.json`. It deliberately stops there. Reading each surviving description and judging it against A1 and the Master's A2 stays with the agent; putting that judgement behind a flag would make it a checkbox.

`run-report.json` records per-source `requests / ok / 429 / 403 / stop_kind / reason`. That is the A1 "declare the reason" duty as data rather than prose.

Before `src/cli.ts` existed, the adapters, `geoFilter`, `dedupCards`, `prefilter` and `observe` were all an uncalled library and the run loop lived in a throwaway script — so nothing about a run was reproducible. **If you find yourself writing a `/tmp` script to drive the adapters, that script belongs in `src/` instead.**

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
- **Three writers touch the canonical CSV; `history.ts` only reads it.** `add_verified.py` (human-confirmed rows), `sync_export.py backfill-ids` (one-time column add) and `sync_export.py pull` (colleagues' decisions out of `Review.xlsx`). Each takes a pre-write backup, and `pull` *reports* an overwrite of a non-empty value instead of doing it silently.
- **Column ownership is data, not a comment.** `reconcile.py` declares `HUMAN_COLS`, `MACHINE_UNION_COLS`, `MACHINE_LATEST_COLS`. A column cannot be in two sets, and tests assert that.
- **The Python and TypeScript implementations must agree.** `reconcile.py` and `normalize.ts` both read the canonical CSV, so `MULTI_VALUE_SPEC` and `norm_company` are asserted equal across the two languages in `test_sync_export.py`. Two readers disagreeing about one file was a real bug.
- **Column identity vs. date-ness are different axes.** `DATE_COLUMNS` spans both owners — `Last Checked` is machine-owned while `First Contact Date`/`Recall` are human-owned. Blanking every date column when appending silently drops the run date.
- **An id shared by two rows is ambiguous.** The 5 duplicate names share a proposed `Company ID`. Resolving by id would send every update to the first row and strand the second — the same failure as `add_verified.py`'s old last-row-wins, via a different key.
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
- The canonical CSV is **semicolon**-delimited; TSV output is **tab**-delimited. `index/Strategic_Design_Company_Index.csv` carries 38 physical header cells but only the first 23 are real (the 22 A4 columns plus `Company ID`); the rest are empty columns inherited from the original xlsx export — don't treat them as real. `pull` appends a `Reviewer Notes` column the first time it has a colleague's note to store.
- In the TSV, columns 1–20 are mandatory; 21–22 (`First Contact Date`, `Recall`) are production extensions: leave empty for new roles, but preserve them when updating an existing row. **Every row must have exactly as many tabs as the header, using empty fields for columns with no value** — neither omitting trailing tabs nor inserting blanks mid-row. Both historical `outputs/*.tsv` files violate this, in two different ways (one is short by two columns, the other has its tail shifted +2), and `stage` refuses both.
- **The tab-count rule alone is not enough.** A row shifted sideways still has the right count. `stage` also validates values against A4's closed sets (`Verification Status` prefixes, `Outreach Decision`, `Contact Search Status`) and against the date columns; `--lenient` overrides and records the problems in the run manifest.
- **Multi-value cells need a per-column separator policy, not one splitter.** `Work Modes` legitimately contains `;` *inside* a single value (`"Physical location shown; onsite/hybrid status to verify"`, 50 rows), so a universal `;` split shreds it. `reconcile.MULTI_VALUE_SPEC` holds the policy; `Work Modes` has `semicolon: false`.
- **Dates must be written as real dates, never text.** A conditional-formatting formula like `$W2<=TODAY()` compares *strings* against `"03/09/2026"` and silently returns the wrong answer while the cell still looks right. `doctor` asserts the date columns actually hold dates.

## Where changes go

| Change | Location |
|---|---|
| Matching/eligibility/verification rules | `config/A1-*.md` / `A4-*.md` — not code |
| A Master's professional areas | `config/<Master> ED.NN>/A2-profilo-*.md` |
| Cohort constraints, `history_file` | `config/<Master> ED.NN>/A3-cohort.yaml` |
| A new discovery source | `src/discovery/` + add to `tsconfig` `include` + a `test/*-smoke.mjs` appended to the `package.json` chain |
| A canonical-history write rule | `python/add_verified.py` **and** `sync_export.py pull`/`backfill-ids` — all three write it |
| The review columns colleagues see | `sync_export.py` → `REVIEW_COLUMNS`. **Changing it after `init-review` has run means migrating live data.** |
| The status colours | `sync_export.py` → `_install_color_rules`, then re-run `color` (idempotent) |
| The status vocabulary itself | `config/A4-status-vocabulary.proposed.md` is a **proposal**; A4 is human-owned and unamended |

Do not add a new config file per search run (A4) and do not create a second copy of A2/A3 content elsewhere.

## Known data problems awaiting a human decision

Machine-detected, deliberately not auto-resolved — each needs someone who knows the history:

- `index/duplicate-names-report.csv` — 5 company names on two rows each (`JAKALA`, `KPMG`, `NTT DATA`, `PwC`, `TeamViewer`) **plus** one orphan row (index 82: a bare `First Contact Date = 03/09/2026` with no company, between `Logotel` and `Doctolib`).
- **Column-shift corruption** in `Bain & Company` and `Moncler`: `Verification Status` and `Last Checked` hold the next row's values / header text. Flagged by `doctor` and `init-review`. The true values are unknown.
- `Moncler Group` (from a run) vs `Moncler` (canonical) — same company or not? Decided via `index/company-aliases.csv` (human-maintained: `alias_norm;canonical_id;note`), never by fuzzy matching.

`sync_export.py` refuses to guess on any of these: a near-duplicate is deferred, an ambiguous update is refused, an unparseable date is reported and left visible.
