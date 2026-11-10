# Stop codes

When a `JOB` command prints `{"stop": "<code>", "detail": "..."}`, find the code here. Tell the colleague the middle column in Italian, in your own plain words, then do the last column. If the last column says to tell Yuwei, give the colleague the code and the `detail` to pass on, and stop the run there.

| Code | What it means for the colleague | What to do |
|---|---|---|
| `config_not_found` | The session is not open in the right folder, so the search rules cannot be found. | Ask them to open the Code session in the OneDrive folder `talent-place` or `jobSearch_outPut`. |
| `master_unknown` | There is no Master with that name. | Show the names listed in the detail and ask which one. |
| `a2_missing` | That Master's folder has no profile (A2), or more than one. | Tell Yuwei or whoever maintains the profiles. |
| `master_id_mismatch` | The Master's profile (A2) and its cohort file (A3) name different Masters. | Do not continue and do not pick one. Tell whoever maintains them. |
| `history_file_missing` | The cohort file (A3) does not say where the Master's Review.xlsx is. | Tell whoever maintains A3. |
| `master_dir_missing` | The Master's folder in `jobSearch_outPut` is not on this computer. | Ask them to check that OneDrive has synced that folder. Never create it. |
| `history_failed` | Review.xlsx could not be read: it may be online-only, open in Excel, or have changed columns. | Ask them to close Excel and set the folder to stay on this device, then try once more. If it stops again, tell Yuwei with the detail. |
| `discover_failed` | The search itself did not run. | Check Node is installed (`node --version`). Otherwise tell Yuwei with the detail. |
| `run_unknown` | That run does not exist for this Master. | Use the `run` name printed by `prepare`. |
| `cards_missing` | The search has not produced its list yet. | Run the search step first, and wait for it to end. |
| `card_unknown` | One of the chosen ids is not in this run's list. | Choose again from `JOB cards`; ids are copied, not typed. |
| `shortlist_missing` | Nothing has been chosen to read yet. | Do step 5. |
| `read_failed` | Reading the postings did not run. | Tell Yuwei with the detail. |
| `verdicts_missing` | The roles have not been judged yet. | Do step 7. |
| `verdicts_refused` | One judgement does not match what was read. Nothing was written. | The detail names the id and why. Correct that verdict from its description and run the step again. |
| `admit_refused` | A field in a judgement has a value the rules do not know. Nothing was written. | The detail lists every problem. Correct the verdicts and run again. |
| `stage_refused` | The result did not pass the checks before publishing. Nothing reached Review.xlsx. | If the detail mentions a file in use, ask them to close Roles.xlsx in Excel and run again. Otherwise tell Yuwei with the detail. |
| `role_count_mismatch` | Two counts of the same roles disagree. Nothing reached Review.xlsx. | Do not continue. Tell Yuwei with the detail. |
| `evidence_incomplete` | Some roles lost their publication date or search query on the way. Nothing reached Review.xlsx. | Do not continue. Tell Yuwei with the detail. |
| `append_refused` | The last step before Review.xlsx failed. Review.xlsx was not changed. | Tell Yuwei with the detail. |
