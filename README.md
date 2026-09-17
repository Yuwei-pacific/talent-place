# Talent Placement — Job Search

Sistema di ricerca stage per i Master POLI.design. Il metodo è in `config/`, il motore in `engine/`.

## Struttura

```
talent-place/
├── config/                      # A1–A4: unico metodo per tutti i Master
│   ├── 00-Talent placement&Design Lab.md   # guida umana (non input agent)
│   ├── A1-regole-ricerca.md               # comune a tutti i Master
│   ├── A4-regole-registrazione.md         # comune a tutti i Master
│   ├── A4-status-vocabulary.proposed.md   # PROPOSTA di modifica ad A4, non applicata
│   ├── Strategic design ED.28/
│   │   ├── A2-profilo-strategic-design.md # uno per Master
│   │   └── A3-cohort.yaml                 # uno per edizione (history_file -> ../../index/..csv)
│   └── Accessory design ED.14/            # stesso schema
├── engine/                      # job-engine
│   ├── src/ test/               # TypeScript: discovery, dedup, normalizzazione
│   ├── python/
│   │   ├── sync_export.py       # pubblica un giro nella cartella sincronizzata
│   │   ├── reconcile.py         # lettura canonical, ownership colonne, matching
│   │   ├── synced_fs.py         # guardie di scrittura sul mount OneDrive
│   │   ├── add_verified.py      # righe confermate -> CSV canonico
│   │   └── io.py                # LEGACY (xlsx), non è nel percorso attuale
│   └── package.json (npm test)
├── outputs/                     # output-YYYY-MM-DD.tsv per ogni ricerca
└── index/
    ├── Strategic_Design_Company_Index.csv   # canonical history
    ├── Accessory_Design_Company_Index.csv   # canonical history (nuovo Master)
    ├── company-aliases.csv                  # alias mantenuti a mano (opzionale)
    └── duplicate-names-report.csv           # problemi da risolvere a mano
```

## Uso settimanale

Non si incolla più niente in SharePoint: `sync_export.py` scrive direttamente
nella cartella sincronizzata. Nessun permesso Microsoft Graph, nessuna app
registration: sono scritture di file normali, che OneDrive carica.

**Una volta sola, in preparazione**

1. In SharePoint, aprire la libreria di destinazione e scegliere
   *Aggiungi collegamento a File personali*. Serve per avere un percorso locale.
2. `doctor` per verificare che il percorso sia davvero dentro il mount OneDrive:
   ```
   python3 engine/python/sync_export.py doctor --dir "<percorso locale>"
   ```
3. `init-review` crea `Review.xlsx` (una volta; poi rifiuta di sovrascrivere),
   `color` installa le regole di colore, `backfill-ids` aggiunge `Company ID`.

**Ogni settimana**

1. Lanciare la ricerca (Claude Code): «Usa A1, A2/A3 di Strategic Design ED.28 e
   A4, fai un giro completo e scrivi `outputs/output-YYYY-MM-DD.tsv`».
2. Pubblicare il giro:
   ```
   python3 engine/python/sync_export.py doctor --dir "<percorso>"
   python3 engine/python/sync_export.py stage  --dir "<percorso>" \
       --history index/Strategic_Design_Company_Index.csv \
       --tsv outputs/output-YYYY-MM-DD.tsv
   python3 engine/python/sync_export.py append --dir "<percorso>"
   ```
3. I colleghi lavorano su `Review.xlsx`: decidono, scrivono note, registrano il
   contatto e il recall. Il colore si aggiorna da sé.
4. Riportare le decisioni nel canonical:
   ```
   python3 engine/python/sync_export.py harvest --dir "<percorso>" \
       --history index/Strategic_Design_Company_Index.csv
   python3 engine/python/sync_export.py pull    --dir "<percorso>" \
       --history index/Strategic_Design_Company_Index.csv --report /tmp/conflitti.csv
   ```

**Due file, due proprietari.** `Review.xlsx` è dei colleghi: la macchina ci
aggiunge solo righe nuove in fondo, dietro guardie, e non lo rigenera mai.
`Roles.xlsx` è della macchina: si rigenera ogni giro e contiene una riga per
role. Nessuno deve unire niente a mano.

Un Master diverso = una cartella sincronizzata diversa (`--dir`) e il suo
`history_file` da A3. Non serve altro.

## Regole chiave (dettagli in A1/A4)

- Output TSV con Tab reali, 22 colonne; `First Contact Date`/`Recall` vuoti sui nuovi.
  **Ogni riga deve avere esattamente lo stesso numero di Tab dell'header**, usando
  campi vuoti per le colonne senza valore: non omettere i Tab finali e non
  inserirne a metà riga. Entrambi i TSV storici in `outputs/` violano questa
  regola, in due modi diversi, e `stage` li rifiuta entrambi.
- Oltre al numero di Tab, `stage` verifica che i **valori** stiano nella colonna
  giusta (insiemi chiusi di A4 e colonne data): una riga spostata di lato ha il
  numero di Tab corretto e passerebbe comunque.
- Notes: `[NEW COMPANY|UPDATE EXISTING ROW] [pertinente|adiacente] Match score: NN/100; motivo`.
- Verification: `Employer verified active` / `Portal verified` / `Legacy result — recheck` / `Blocked — motivo` / `To verify — campo`.
- Indeed riga obbligatoria `X = Y + Z + P`; connector assente → `Unavailable (motivo)`.
- Mai inventare score senza descrizione letta; mai toccare colonne contatti/storico.
- Le date vanno scritte come date vere, non come testo: una formula di
  formattazione condizionale confronta stringhe e sbaglia in silenzio.

## Problemi noti in attesa di una decisione umana

Nessuno di questi viene risolto automaticamente: servono i dati storici.

- **5 nomi su due righe ciascuno** (`JAKALA`, `KPMG`, `NTT DATA`, `PwC`,
  `TeamViewer`), più **una riga orfana** (indice 82: solo
  `First Contact Date = 03/09/2026`, senza azienda, fra `Logotel` e `Doctolib`).
  Dettagli in `index/duplicate-names-report.csv`.
- **Due righe corrotte da un incolla** (`Bain & Company`, `Moncler`): le colonne
  `Verification Status` e `Last Checked` contengono i valori della riga
  successiva o testo di intestazione. Segnalate da `doctor` e da `init-review`.
- **`Moncler Group`** (da un giro) contro **`Moncler`** (canonical): stessa
  azienda? Si decide in `index/company-aliases.csv`, non con una euristica.

## Test

Da `engine/`:

```bash
npm test                              # build + 10 test node + suite Python
python3 python/test_sync_export.py    # sola suite Python
```

Tre test node (`aggregators-smoke`, `employer-smoke`, `prefilter-smoke`) toccano
la rete e falliscono senza connessione o se cambia il markup delle pagine.
