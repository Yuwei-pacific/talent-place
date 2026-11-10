---
name: diagnostica
description: Explain what went wrong in a Talent Placement internship search, or what state the last run is in. Use when a search stopped, gave an error or a stop code, found nothing, or someone asks che cosa è successo, perché si è fermato, or a che punto è la ricerca.
---

# Diagnostica

You are helping a non-technical colleague understand a search that stopped or looks wrong. Speak Italian and plain. You change nothing here: this skill only reads and explains.

- `ENGINE` is `${CLAUDE_SKILL_DIR}/../cerca-stage/engine`.
- `PY` is the first of `python`, `python3`, `py -3` that runs.
- `JOB` is short for: `PY -X utf8 "ENGINE/python/job_run.py"`.
- The stop codes are explained in `${CLAUDE_SKILL_DIR}/../cerca-stage/references/arresti.md`.

## What to do

1. If the colleague has a stop code or an error message, start from `arresti.md`.
2. Run `JOB masters` to find the Master's folder. Its runs are in `_machine/runs/` inside that folder, one folder per day; take the most recent one for that Master.
3. Read what is there, in this order, and stop at the first that explains it:
   - `run-report.json`: each source's `status`, `reason` and `health` (requests, `ok`, `blocked429`, `cooldowns`, `events429`). `blocked` with 429 means LinkedIn asked to slow down and the waits ran out.
   - `checkpoint.jsonl` against `run.json`: how many searches finished out of those planned.
   - `read-report.json`: read, `empty`, `unread`. Many `empty` pages mean LinkedIn's page changed or showed a sign-in wall.
   - `final/publish.json`: `state` is `awaiting_confirmation`, `written` or `refused_to_sidecar`.
   - a `Review-additions-…csv` file in the Master's folder: a write that was refused, with the rows kept safe.
4. Do not open `Review.xlsx` or `history.csv`.

## What to tell the colleague

Three things, briefly: what happened, whether anything was written to Review.xlsx, and what they can do now. Typical answers:

- **LinkedIn blocked the search:** nothing is lost. Running the search again the same day continues from where it stopped; wait at least 20 minutes.
- **The computer went to sleep or the app was closed:** the same, run it again.
- **Review.xlsx was open or online-only:** close Excel, set it to stay on the device, and run the last step again.
- **Anything in `arresti.md` that says to tell Yuwei, or anything you cannot explain:** write a short note for the colleague to forward, with the Master, the run name, the stop code or error text exactly as printed, and the numbers from `run-report.json`. Say plainly that this needs a technical person.

Never say a search was complete unless every planned search finished and every source's status is `ok`.
