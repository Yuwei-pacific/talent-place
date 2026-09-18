# Talent Placement — Job Search

Sistema di ricerca stage per i Master POLI.design. Il metodo è in `config/`, il motore in `engine/`.

`config/` contiene **solo input dell'agent**: A1 e A4 (comuni), un A2 e un A3 per Master. Questo file è la guida umana — come lavoriamo, chi aggiorna cosa, come si avvia un giro — e non è un input dell'agent.

## Struttura

```
talent-place/
├── README.md                    # questa guida (umana, non input agent)
├── config/                      # solo input dell'agent
│   ├── A1-regole-ricerca.md               # comune a tutti i Master
│   ├── A4-regole-registrazione.md         # comune a tutti i Master
│   ├── Strategic design ED.28/
│   │   ├── A2-profilo-strategic-design.md # uno per Master
│   │   └── A3-cohort.yaml                 # uno per edizione (history_file -> il Review.xlsx del Master)
│   └── Accessory design ED.14/            # stesso schema
├── archive/                     # chiusi/ritirati: niente qui è un input dell'agent
│   ├── 2026-09-16-status-vocabulary-proposal.md
│   ├── Strategic_Design_Company_Index.csv   # vecchio canonical, fermo a 118 aziende
│   ├── Accessory_Design_Company_Index.csv
│   ├── company-aliases.csv                  # stava dove nessuno lo leggeva
│   ├── duplicate-names-report.csv
│   └── run-2026-09-17-strategic-design-ED28.tsv
├── engine/                      # job-engine
│   ├── src/
│   │   ├── cli.ts               # `discover` (ricerca) e `verify` (sito datore)
│   │   ├── pipeline.ts          # fan-out query -> geo -> dedup -> prefilter
│   │   ├── ratelimit.ts         # limite di velocità per fonte + pool
│   │   ├── verify.ts            # sonda del sito datore, prima del browser
│   │   ├── discovery/           # linkedin-guest, ats, aggregators, employer, http
│   │   └── ...                  # normalize, dedup-cards, geo, prefilter, history
│   ├── test/                    # 15 test node (uno tocca la rete)
│   ├── python/
│   │   ├── sync_export.py       # pubblica un giro nella cartella sincronizzata
│   │   ├── reconcile.py         # lettura canonical, ownership colonne, matching
│   │   ├── synced_fs.py         # guardie di scrittura sul mount OneDrive
│   │   └── (niente altro: lo storico si legge da Review.xlsx)
│   └── package.json (npm test)
```

## Il metodo: cinque file, quattro input per l'agent

| File | Domanda a cui risponde | Ambito |
|---|---|---|
| [A1 · Ricerca](config/A1-regole-ricerca.md) | Dove cercare e come verificare e valutare? | Comune a tutti i Master |
| [A2 · Profilo](config/Strategic%20design%20ED.28/A2-profilo-strategic-design.md) | A quali attività prepara questo Master? | Uno per Master |
| [A3 · Coorte](config/Strategic%20design%20ED.28/A3-cohort.yaml) | Quali esigenze, capacità e disponibilità hanno questi studenti? | Uno per edizione/gruppo |
| [A4 · Registrazione](config/A4-regole-registrazione.md) | Come conservare prove, storico e decisioni? | Comune a tutti i Master |

Per eseguire una ricerca bastano A1, l'A2 e l'A3 selezionati, e A4, insieme alla richiesta del momento e allo storico disponibile. Questo file non è un quinto input. Leggere le versioni aggiornate senza compilare o mantenere una copia concatenata.

Il risultato di una ricerca è un bacino di opportunità documentate: le persone selezionano aziende e ruoli, confermano i contatti e rivedono le email prima dell'invio.

## Manutenzione e conferma

La ripartizione è una proposta operativa: il team assegna i referenti effettivi.

| Contenuto | Chi aggiorna / conferma | Quando |
|---|---|---|
| A1 e A4 | Talent Placement | Quando cambia il metodo o emerge un problema verificato |
| A2: presenza delle aree, attività, risultati e limiti | Direttore e team didattico; Talent Placement aiuta a redigere | Prima del primo uso e quando cambia il percorso |
| A2: termini di ricerca | Talent Placement | Quando i risultati suggeriscono termini migliori |
| A3: esigenze, lingue e prove delle capacità | Coordinamento, sulla base di risposte e materiali degli studenti | A ogni edizione e quando cambiano i dati |
| A3: calendario e condizioni didattiche | Coordinamento con il team didattico | Prima di confermare la compatibilità delle opportunità |
| Aziende, ruoli, contatti e invio | Talent Placement / referente incaricato | Nei punti di revisione umana indicati in A4 |
| Contributi a un Lab e fattibilità | BD con direzione e coordinamento dei Master | Per ogni brief aziendale |

La validazione del percorso e le preferenze degli studenti sono due verifiche diverse. L'agent propone: non attribuisce da solo una conferma al direttore e non modifica automaticamente i file di configurazione.

### Come aggiornare A2 e A3

In A2 il direttore rivede una scheda per area: presenza nel percorso, ruolo formativo, attività, elaborati, limiti e riferimento didattico. "Complementare" non significa "esclusa". Confermare anche chi ha revisionato il documento e quando. Le keyword restano nella stessa scheda, a cura di Talent Placement.

In A3 mantenere soltanto dati reali. `null` indica un valore sconosciuto; `[]` indica nessuna voce registrata. Gli esempi nei commenti sono fittizi e non vanno copiati come risposte effettive. Distinguere condizioni operative di ricerca, preferenze, vincoli e capacità dimostrate. Le lingue ammesse per gli annunci non certificano quelle parlate dagli studenti.

Riutilizzare questionari, CV, portfolio e tabelle già disponibili. Indicare fonte e data; per informazioni individuali collegare la tabella esistente anziché duplicarla. Le sintesi di gruppo non descrivono automaticamente ogni studente.

### Riutilizzo per un altro Master e per BD

Per un altro Master preparare il suo A2 e il suo A3, assegnare lo stesso `master_id` ai due file e riusare A1 e A4. Non modificare le regole comuni per inserire nomi, keyword o preferenze specifiche di un Master.

Il flusso A1–A4 riguarda stage e opportunità per studenti, non genericamente tutti i lavori junior. Per BD riusare A2 e A3 con un brief aziendale e una richiesta dedicata: confrontare Master, contributi, risultati attesi, parti non coperte e calendario. Non applicare al Lab il requisito di una vacancy di stage. Il riconoscimento didattico del Lab va verificato con il team.

## Uso settimanale

Non si incolla più niente in SharePoint: `sync_export.py` scrive direttamente nella cartella sincronizzata. Nessun permesso Microsoft Graph, nessuna app registration: sono scritture di file normali, che OneDrive carica.

**Una volta sola, in preparazione**

1. In SharePoint, aprire la libreria di destinazione e scegliere *Aggiungi collegamento a File personali*. Serve per avere un percorso locale.
2. `doctor` per verificare che il percorso sia davvero dentro il mount OneDrive:
   ```
   python3 engine/python/sync_export.py doctor --dir "<percorso locale>"
   ```
3. `init-review` crea `Review.xlsx` (una volta; poi rifiuta di sovrascrivere), `color` installa le regole di colore, `backfill-ids` aggiunge `Company ID`.

**Se cambiano le colonne di `Review.xlsx`** (non i valori: le colonne), serve una migrazione, perché `stage` e `append` scrivono nella posizione dettata da `REVIEW_COLUMNS`: senza migrazione ogni valore dopo la modifica finisce nella colonna sbagliata.

```
python3 engine/python/sync_export.py migrate-review --dir "<percorso>" --dry-run
python3 engine/python/sync_export.py migrate-review --dir "<percorso>"
```

Ogni cella viene trasferita **per nome di colonna**, quindi una colonna spostata, aggiunta o rimossa non fa scivolare niente. Le colonne che non esistono più vengono riportate, non cancellate in silenzio. Un valore di stato che non è né attuale né noto viene **rifiutato** (`--force` per procedere comunque): indovinare l'intenzione di un collega è come si perde una decisione. Il comando fa il backup da sé prima di scrivere.

**Ogni settimana**

1. **La ricerca.** Il giro è guidato da Claude Code, che legge A1–A4 e il Master. La parte meccanica è in `engine/`.

   Prima si esporta lo storico **dal file che i colleghi mantengono**, non da una copia:
   ```
   python3 engine/python/sync_export.py export-history \
       --dir "<cartella del Master>" --out <cartella del giro>/history.csv
   ```
   Poi la ricerca, che usa quel CSV per la deduplicazione:
   ```
   cd engine
   npm run discover -- --config <run.json> --out <cartella del giro> \
       --history <cartella del giro>/history.csv
   ```
   Scrive `cards.json` (i ruoli da leggere), `role-evidence.csv` (data di pubblicazione, query, link alternativi) e `run-report.json` (cosa ha fatto ogni fonte e perché si è fermata).

   Segue la parte che resta umana: leggere le descrizioni, applicare A1 e l'A2, e comporre il TSV.

2. **Verifica dei siti datore.** Prima di aprire un browser, sondare:
   ```
   npm run discover -- verify --urls <lista.txt> --out <cartella del giro>
   ```
   Un URL per riga, opzionalmente `etichetta;url`. Risponde a "la pagina è viva / parla di uno stage / c'è un percorso di candidatura" e scrive uno stato A4 per URL. Nel giro del 17/09 ha risposto per 9 pagine su 9 in 10,9 secondi, contro ~72 secondi a pagina col browser: **il browser è l'eccezione**, per i pochi URL che la sonda non risolve.

3. **Pubblicare il giro.** Salvare il TSV nella cartella del giro, accanto a `cards.json` ed `evidence` (A4: la cartella di output la indica la richiesta). Poi:
   ```
   python3 engine/python/sync_export.py doctor --dir "<percorso>"
   python3 engine/python/sync_export.py stage  --dir "<percorso>" \
       --history <cartella del giro>/history.csv \
       --tsv <cartella del giro>/run.tsv \
       --evidence <cartella del giro>
   python3 engine/python/sync_export.py append --dir "<percorso>"
   ```
   `--evidence` accetta la cartella del giro (o un singolo file, riconosciuto dall'intestazione) e riempie le colonne che il TSV a 22 colonne non può portare: data di pubblicazione, query di ricerca, link alternativi, e — per i ruoli effettivamente sondati — uno stato di verifica proprio invece di quello dell'azienda. Senza `--evidence` quelle colonne restano vuote e il manifest lo dichiara.

4. I colleghi lavorano su `Review.xlsx`: decidono, scrivono note, registrano il contatto e il recall. Il colore si aggiorna da sé.

5. **Non c'è niente da risincronizzare.** `Review.xlsx` *è* la registrazione: le
   decisioni dei colleghi restano dove le scrivono. `export-history` del punto 1 le
   rilegge al giro successivo.

   Per un controllo di sola lettura su dove Review e il canonical di allora
   divergevano (utile durante la transizione):
   ```
   python3 engine/python/sync_export.py harvest --dir "<percorso>" \
       --history <cartella del giro>/history.csv
   ```

**Due file, due proprietari.** `Review.xlsx` è dei colleghi: la macchina ci aggiunge solo righe nuove in fondo, dietro guardie, e non lo rigenera mai. `Roles.xlsx` è della macchina: si rigenera ogni giro e contiene una riga per ruolo. Nessuno deve unire niente a mano.

Un Master diverso = una cartella sincronizzata diversa (`--dir`) e il suo `history_file` da A3. Non serve altro.

## Regole chiave (dettagli in A1/A4)

- Output TSV con Tab reali, 22 colonne; `First Contact Date`/`Recall` vuoti sui nuovi.
  **Ogni riga deve avere esattamente lo stesso numero di Tab dell'header**, usando
  campi vuoti per le colonne senza valore: non omettere i Tab finali e non
  inserirne a metà riga. I due campioni in `engine/test/fixtures/` violano questa
  regola in due modi diversi (`tsv-short-2026-09-10.tsv` è corto di due colonne,
  `tsv-shifted-2026-09-11.tsv` ha la coda spostata di +2) e `stage` li rifiuta
  entrambi. Sono la prova che `stage` rifiuta input sbagliati: **cancellarli fa
  diventare 6 test degli skip mentre la suite continua a dire OK** (misurato; la
  documentazione precedente diceva tre).
- Oltre al numero di Tab, `stage` verifica che i **valori** stiano nella colonna
  giusta (insiemi chiusi di A4 e colonne data): una riga spostata di lato ha il
  numero di Tab corretto e passerebbe comunque.
- `Contact Search Status` (in `Review.xlsx`) è l'asse con cui si colora **l'intera riga**: `Not started` bianco, `Job not suitable` grigio, `Potential contact` giallo, `Contact found` blu, `Job found` verde. Il bianco non ha una regola: è lo sfondo del foglio.
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
  Dettagli in `archive/duplicate-names-report.csv`.
- **Due righe corrotte da un incolla** (`Bain & Company`, `Moncler`): le colonne
  `Verification Status` e `Last Checked` contengono i valori della riga
  successiva o testo di intestazione. Segnalate da `doctor` e da `init-review`.
- **`Moncler Group`** (da un giro) contro **`Moncler`** (canonical): stessa
  azienda? Si decide in `company-aliases.csv` nella radice di `jobSearch_outPut/` (dove il codice lo cerca), non con una euristica.
- *(risolto il 2026-09-18)* La proposta sul vocabolario è **chiusa** e spostata in
  `archive/2026-09-16-status-vocabulary-proposal.md`: la Modifica 1 era già in
  vigore, la Modifica 2 (stato derivato) è stata superata dalla scelta di uno
  stato memorizzato. Il vocabolario sta ora in A4. Il file resta per il
  ragionamento sulle alternative scartate, non per le regole.

## Test

Da `engine/`:

```bash
npm test                              # build + 15 test node + suite Python (99 test)
python3 python/test_sync_export.py    # sola suite Python
```

`npm test` è una catena `&&`: se un test fallisce, quelli dopo non girano.
**Un solo test node tocca la rete, `employer-smoke`** — fallisce senza connessione
o se cambia il markup di una pagina di terzi, e in quel caso blocca anche la suite
Python. Tutti gli altri, comprese le prove sui tempi (che usano un server locale),
girano offline.

Per aggiungere un test node bisogna **appenderlo a mano** alla catena in
`package.json`: non c'è scoperta automatica. Stessa cosa per un nuovo file in
`src/`: `tsconfig.json` ha una lista esplicita, e un file non elencato non viene
compilato.
