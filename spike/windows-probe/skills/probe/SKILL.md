---
name: probe
description: Run the one-off Talent Placement environment test on this computer. Use when someone asks to run the Talent Placement probe, the environment test, or the test di ambiente.
---

# Talent Placement environment test

You are helping a non-technical colleague, in Italian, run a test. The results decide how a tool gets built, so a wrong result costs more than a failed one.

## Rules

- Show each result line exactly as `probe.py` prints it, then say in one plain Italian sentence what happened. Do not soften, reinterpret or retry a `FAIL`.
- If a command errors, show the error as it is. Never edit the scripts, and never work around a failure to make a test pass.
- Do not read `Review.xlsx` or `history.csv`: they hold real contacts. The scripts open them; you do not.
- Write only inside the test folder.
- Never retry LinkedIn by hand after a 429. When `net` says `INCONCLUSIVE`, wait at least 20 minutes before running it again.

## Before starting

The colleague must have attached two folders:

1. `talent-place/config`, called CONFIG below.
2. A test folder whose own name contains `TEST`, holding a copy of `Review.xlsx`, called TEST below.

If either is missing, ask for it. If the probe answers `REFUSED`, that is the safety check working: ask for the right folder and do not rename anything.

For Python, use the first of `python3`, `python`, `py -3` that runs. Below it is written `python3`.

## The test

Run these in order, one at a time:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/probe.py" env --master "TEST"
python3 "${CLAUDE_SKILL_DIR}/scripts/probe.py" net --master "TEST"
python3 "${CLAUDE_SKILL_DIR}/scripts/probe.py" fs --master "TEST" --config "CONFIG"
python3 "${CLAUDE_SKILL_DIR}/scripts/probe.py" state --master "TEST" --label normal
```

Then the steps that need the colleague. Wait for their confirmation before each command:

1. Ask them to open `Review.xlsx` from the test folder in Excel and leave it open. Run `state --master "TEST" --label excel-open`. Ask them to close it.
2. Ask them to right-click `Review.xlsx` in the test folder and choose *Libera spazio* (Free up space). Run `state --master "TEST" --label online-only`. Then ask them to choose *Mantieni sempre su questo dispositivo* (Always keep on this device), which the full run needs.
3. Ask them to check two things and note them on the results sheet: `probe-roundtrip.xlsx` opens in Excel, and `probe-marker-*.txt` appears on the OneDrive website.

## Indeed connector

If you have tools from an Indeed connector, search once for `stage design` in `Milano`. Tell the colleague the tool's name and whether it returned results, for the results sheet. If you have none, tell them to write `Unavailable`.

## Finishing

Summarise every line in a short table, and ask them to send `probe-report.jsonl` from the test folder to Yuwei.

## The full run

Start this only when the colleague explicitly asks, because it takes hours and uses their Claude allowance. Read `references/full-run.md`.
