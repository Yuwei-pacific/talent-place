# Talent Placement — Job Search

Sistema di ricerca stage per i Master POLI.design. Metodo in `workflow/`, motore in `engine/`.

## Struttura

```
talent-place/
├── config/                      # A1–A4: unico metodo per tutti i Master
│   ├── 00-Talent placement&Design Lab.md   # guida umana (non input agent)
│   ├── A1-regole-ricerca.md               # comune a tutti i Master
│   ├── A4-regole-registrazione.md         # comune a tutti i Master
│   └── Strategic design ED.28/
│       ├── A2-profilo-strategic-design.md # uno per Master
│       └── A3-cohort.yaml                 # uno per edizione (history_file -> ../../index/..csv)
├── engine/                      # job-engine: discovery + dedup + TSV (no DSH)
│   ├── src/ test/ python/ lib/
│   └── package.json (npm test)
├── outputs/                     # output-YYYY-MM-DD.tsv per ogni ricerca
└── index/
    └── Strategic_Design_Company_Index.csv # canonical history (113 aziende)
```

## Uso settimanale

1. Lanciare la ricerca (Claude Code): «Usa A1, A2/A3 di Strategic Design ED.28 e A4, fai un giro completo e scrivi `outputs/output-YYYY-MM-DD.tsv`».
2. Incollare il TSV in SharePoint, review umana.
3. Righe confermate → `add-verified` nel CSV canonico:
   `engine/python/add_verified.py ../Strategic_Design_Company_Index.csv < payload.json`
4. GPT+Indeed connector gira in parallelo (posti Indeed-only); incrocio via `checkDup`.

## Regole chiave (dettagli in A1/A4)

- Output TSV con Tab reali, 22 colonne; `First Contact Date`/`Recall` vuoti sui nuovi.
- Notes: `[NEW COMPANY|UPDATE EXISTING ROW] [pertinente|adiacente] Match score: NN/100; motivo`.
- Verification: `Employer verified active` / `Portal verified` / `Legacy result — recheck` / `Blocked — motivo` / `To verify — campo`.
- Indeed riga obbligatoria `X = Y + Z + P`; connector assente → `Unavailable (motivo)`.
- Mai inventare score senza descrizione letta; mai toccare colonne contatti/storico.
