---
name: cerca-stage
description: Run the weekly internship search for a POLI.design Master and publish the result to its Review.xlsx. Use when someone asks to cercare stage, fare la ricerca stage, avviare il giro settimanale, or search internships for a Master such as Strategic design or Accessory design.
---

# Ricerca stage

You are running the internship search for a colleague in Talent Placement who is not technical. Speak to them in Italian, in plain words, and never show them a command, a file path or raw JSON unless they ask. They decide; you do the work and say honestly what happened.

## Paths and commands

- `ENGINE` is `${CLAUDE_SKILL_DIR}/engine`.
- `PY` is the first of `python`, `python3`, `py -3` that runs on this computer.
- `JOB` is short for: `PY -X utf8 "ENGINE/python/job_run.py"`. So `JOB masters` means running that script with the argument `masters`.
- Every `JOB` command prints JSON. A result with `"stop"` is a stop: open `${CLAUDE_SKILL_DIR}/references/arresti.md`, tell the colleague what its row says, and do what it says. Do not improvise around a stop.

## Rules

- Never run `JOB publish` with `--confirm` unless the colleague has just answered yes, in this conversation, to the question in step 8. Nothing else writes to Review.xlsx, and nothing else may.
- Never type a URL, a job title, a company name, a date or a place from memory, and never edit `cards.json`, `shortlist.json` or `descriptions.json`. The engine copies those facts from what it found. Your judgement goes in `verdicts.json` and nowhere else.
- Never retry LinkedIn yourself. The engine already waits when LinkedIn asks it to slow down. If a step ends blocked, report it and stop there.
- Never edit the engine or work around a failure to make a step pass. Show the colleague what happened.
- Do not open `Review.xlsx` or `history.csv`: they hold colleagues' contacts and notes. The engine reads them.
- A partial search is still useful, and it is never complete. Say which areas were not searched, every time.
- Do not use any other source in this version: no Indeed connector, no web search for postings.

## 1. Check the computer

Run `node --version` and `PY --version`. If either is missing, tell the colleague that Node and Python must be installed first, give them this line to paste into PowerShell, and stop:

`winget install -e --id OpenJS.NodeJS.LTS; winget install -e --id Python.Python.3.12`

This skill needs the **Code** tab of the Claude desktop app, on the computer. If you are in a chat or cloud session with no access to the computer's own network and files, say so and stop: from there LinkedIn cannot be reached.

## 2. Choose the Master

Run `JOB masters`. If it stops with `config_not_found`, the session was opened in the wrong folder: ask the colleague to open the Code session in the OneDrive folder `talent-place` or `jobSearch_outPut`, and stop.

If the colleague has not named a Master, list the ones marked `ready` and ask. Use the name exactly as listed. If the one they want is not `ready`, explain its `problem` from `arresti.md`.

## 3. Before starting

Tell the colleague, and wait for their go-ahead:

- the search takes from 20 minutes to about 2 hours, mostly waiting, and they can do other work meanwhile;
- the computer must stay on and plugged in, with the Claude app open and the lid open;
- `Review.xlsx` of that Master should be closed in Excel;
- in Esplora file, the Master's folder in `jobSearch_outPut` should be set to **Conserva sempre in questo dispositivo** (on some computers the item is called **Mantieni sempre su questo dispositivo**).

Then read, from the `config_root` that `JOB masters` printed: `A1-regole-ricerca.md`, `A4-regole-registrazione.md`, and the Master's `A2-profilo-*.md` and `A3-cohort.yaml`. They are the rules you judge by. Do not use another Master's profile.

## 4. Search

Run `JOB prepare --master "<Master>"` **in the background**, and wait for it to finish. Do not poll it and do not start it twice.

When it ends, tell the colleague in a few plain lines:

- how many searches were done out of how many planned, and area by area (`coverage.per_area`): an area with `searched` 0 was **not searched**, which is different from finding nothing;
- whether LinkedIn stopped the search (`sources[].status` other than `ok`) and after how many requests;
- any `doctor_problems` about Review.xlsx being online-only or open in Excel.

If `complete` is false, say so plainly. The same command, run again the same day, continues from where it stopped: offer that for later, at least 20 minutes after a block. Then go on with what was found; an incomplete search still gets published, with its gaps declared.

## 5. Choose what to read

Run `JOB cards --master "<Master>" --run "<run>"` (`run` is in the result of step 4). Choose the cards worth reading against the A2 areas, from title, company and snippet. When in doubt, read it: a title is not a description. Leave out only what is clearly outside the Master.

Then run `JOB shortlist --master "<Master>" --run "<run>" --ids <id> <id> ...` with the chosen ids. Each description takes about 10 seconds to fetch, so tell the colleague roughly how long this will take.

## 6. Read

Run `JOB read --master "<Master>" --run "<run>"` in the background and wait. Report how many were read, how many pages were `empty` (no posting text: say so, it may mean LinkedIn changed something), and how many are `unread`.

## 7. Judge

Open `descriptions.json` in the run folder (`run_dir`) and read every entry that has a `desc`. Judge each one against A1 and the A2, and write `verdicts.json` in the same folder, following `${CLAUDE_SKILL_DIR}/references/verdetti.md` exactly. A role without a read description gets no verdict.

## 8. Show, ask, then write

Run `JOB publish --master "<Master>" --run "<run>"`. This writes `Roles.xlsx` and stops before `Review.xlsx`. Show the colleague:

- how many roles and companies are in the result, and how many were excluded and why;
- the companies in `would_append`, by name: these are the new rows;
- anything in `deferred`: companies whose name resembles one already in Review.xlsx. They are **not** added. List them and say they need a person's decision; do not resolve them yourself.

Then ask, in these words: **«Scrivo queste aziende in Review.xlsx?»**

Only on a clear yes, run `JOB publish --master "<Master>" --run "<run>" --confirm` and read `state`:

- `written`: the rows are in Review.xlsx.
- `refused_to_sidecar`: nothing was written to Review.xlsx, because it was open in Excel or not downloaded. The rows are safe in the `Review-additions-…csv` file named in `sidecar`. Ask the colleague to close Excel and set the file to stay on the device, then offer to run this step again.

If the answer is no, or unclear, write nothing and say that Roles.xlsx is ready to look at.

## 9. Report

Get the Indeed line by running, from `ENGINE`: `node lib/cli.js indeed --status Unavailable --x 0 --y 0 --z 0 --note "non integrato in questa versione del plugin"`. Use its output as printed.

Write `report.md` in the run folder, in Italian, following A4: date; new roles and companies; Milano / resto d'Italia / resto UE; up to three priorities; the limited sources; the Indeed line; the areas not searched; the roles not read; the companies deferred. Then tell the colleague the same in a short message, and which files to open: `Roles.xlsx` for the roles, `Review.xlsx` for the companies.

End by saying when it makes sense to run again: today or tomorrow if areas were not searched, otherwise next week.
