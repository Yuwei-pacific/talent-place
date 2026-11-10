# verdicts.json

A JSON array, UTF-8, one object per description you read. The engine takes the URL, title, company, place and date from the card, so a verdict carries none of them, except where noted.

```json
[
  {
    "id": "4321987650",
    "label": "pertinente",
    "area": ["Service Design / CX"],
    "quotes": ["map customer journeys and run user interviews"],
    "reason": "Mappa i journey e conduce interviste: attività centrali dell'area.",
    "score": 78,
    "workMode": "hybrid"
  }
]
```

| Field | Rule |
|---|---|
| `id` | The `sourceJobId` of the entry in `descriptions.json`. One verdict per id. |
| `label` | `pertinente`, `adiacente`, `fuori profilo`, or `escluso`. Only the first two reach Review.xlsx. |
| `area` | One or more A2 area names, copied exactly from the A2 headings. Required for `pertinente` and `adiacente`. Never an area whose *Presenza nel percorso* is `Non prevista`. |
| `quotes` | One to three short passages copied **character for character** from that entry's `desc`, about responsibilities. Required for `pertinente` and `adiacente`. A paraphrase is refused. |
| `reason` | One or two Italian sentences on why, citing responsibilities and not the title or the company's prestige (A1). |
| `score` | Optional, 0 to 100. It only orders results. |
| `workMode` | Optional: `onsite`, `hybrid`, `fully_remote` or `to_verify`, and only when the posting **states** it. Leave it out when it does not. |
| `requiredLanguages` | Optional: languages the posting makes **mandatory**, as bare English names: `["English"]`, never `"English C1"`. Do not infer a language from the language the posting is written in. |
| `languageRequirement` | With `requiredLanguages`: `all` when every listed language is required, `any` when one of them is enough. |
| `stageNature` | Optional boolean. Set `false` when the read shows the role is not an internship or student role despite its title. |
| `company` | Optional: the employer's name, only when the card shows a job board or agency and the description names the real employer. Copy the name from the description. |
| `location` | Optional, and only when the engine refuses because it cannot tell the country: `"City, Country"`, with the city taken from the posting. |
| `ground` | Required with `escluso`: `senior-without-stage`, `fully-remote`, `closed-ad`, `mandatory-language`, or a short reason in Italian. Use the literal value `admit` only when the fields above (work mode, languages, `stageNature`) are what excludes it, so that the engine's own check decides. |

How to choose a label, in A1's terms:

- `pertinente`: the responsibilities match at least one A2 area and one of its competences.
- `adiacente`: a real connection to an area, but partial or supporting.
- `fuori profilo`: read, and not for this Master. Say why in `reason`.
- `escluso`: inadmissible under A1 (clearly senior with no internship nature, entirely remote, clearly closed, a mandatory language the cohort does not admit, exclusively extracurricular when a curricular internship is required).

An undeclared work mode, language or curricular status never excludes (A1): keep the role and leave the field out.

If `JOB publish` stops with `verdicts_refused`, the detail names the id and the reason. Fix that verdict from the description and run it again. Never change a quote into something the description does not say; pick another passage or lower the label.
