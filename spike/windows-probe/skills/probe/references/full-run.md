# The full run (T6)

What this measures, most important first: whether one command can run for 2 to 3 hours here, how much Claude allowance a run uses, and how the engine's waiting behaves against LinkedIn's real limit. It has never met that limit before, so report what happens rather than fixing it.

Everything goes in `TEST/_probe-run/`. `ENGINE` below is `${CLAUDE_SKILL_DIR}/engine`. To run the engine's Python, set `PYTHONPATH` to `ENGINE/python/vendor`.

1. Ask the colleague which Master to test, and to note the figures on Claude's usage page (Settings, Usage).
2. Read `CONFIG/A1-regole-ricerca.md`, `CONFIG/A4-regole-registrazione.md`, and that Master's A2 and A3.
3. Export the history:
   `python3 "ENGINE/python/sync_export.py" export-history --dir "TEST" --out "TEST/_probe-run/history.csv"`
4. Write `TEST/_probe-run/run.json` from A2 and A3, with the fields of `PipelineConfig` in the engine: `topK` 200, `cooldownMinutes` 20, `maxCooldowns` 12. No `recencyDays` and no derogations.
5. Note the time, then run this in the background, sending its output to `TEST/_probe-run/discover.log`:
   `node "ENGINE/lib/cli.js" discover --config "TEST/_probe-run/run.json" --out "TEST/_probe-run" --history "TEST/_probe-run/history.csv"`
   Expect about 2 hours, most of it waiting. **This is the point of the test.** Note when it ends, and anything that interrupted it: a shell timeout, the sandbox, the computer sleeping. If it was interrupted, run the same command with `--resume` added, and note how many times you had to.
6. In the same way, run:
   `node "ENGINE/lib/cli.js" read --cards "TEST/_probe-run/cards.json" --out "TEST/_probe-run" --top 60 --cooldown-minutes 20`
   Expect about 1 hour. If its output shows `empty` above 0, report that: those pages held no posting.
7. Judge each posting that was read against A1 and the A2, and write `TEST/_probe-run/verdicts.json`. Copy each URL from `descriptions.json`; never compose one.
8. Do not run `stage` or `append`. Nothing from this run goes into a Review file.
9. Report: start and end times, interruptions and `--resume` count, `sources` (with `health.events429` and `cooldowns`) and `counters` from `run-report.json`, `read-report.json`, how many postings you judged, and ask the colleague to note the usage figures again.
