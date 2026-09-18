# A4 · Proposta di modifica: vocabolario di stato

**Stato: CHIUSA — esito misto. Non è più una proposta da approvare.** Il testo qui
sotto è conservato come traccia del ragionamento, non come lavoro da fare.

Data: 2026-09-16 · Contesto: passaggio dalla review manuale su Excel al file
`Review.xlsx` condiviso. · Esito registrato il 2026-09-18.

## Esito

| Parte | Esito |
|---|---|
| **Modifica 1** — `Outreach Decision` da costante a enumerazione | **Recepita.** Era già la realtà: `Review` / `Yes` / `No` esiste in codice dalle prime versioni, e A4 lo prescriveva già. Nessuna modifica necessaria. |
| **Modifica 2** — stato *derivato*, calcolato da Excel, non memorizzato | **Superata, non recepita.** La revisione ha scelto l'opposto: uno stato **memorizzato** in `Contact Search Status`, con cinque valori scelti dalla persona, e l'intera riga colorata da quello. La proposta argomentava che un campo di stato manuale sarebbe "un terzo campo da mantenere"; la scelta è stata di accettarlo, perché il colore derivato non distingue «non ho ancora cercato il referente» da «il ruolo non è adatto». |
| **Conseguenze tecniche, punto 1** — `Notes` diviso in due colonne | **Recepita.** `Matching Notes` (macchina) e `Reviewer Notes` (persona) esistono in `Review.xlsx` da `init-review`. |

Il vocabolario effettivo è ora in `A4-regole-registrazione.md`, sezione «Contatti e
decisioni»: `Not started`, `Job not suitable`, `Potential contact`, `Contact found`,
`Job found`. Le regole di colore in codice citavano questo file (`COLOR_RULES_SPEC`); ora citano
A4. Il riferimento a un documento chiuso non proteggeva niente — quella stringa viene
solo stampata, non scritta nel foglio — ed era solo un modo per rimandare a una
proposta respinta.

---

## Perché serve una modifica

Le regole di colore richieste dalla review umana ("颜色区分不同 status") **oggi non
sono derivabili da nessuna colonna**, per due motivi misurati sul canonical CSV:

| Fatto misurato | Conseguenza |
|---|---|
| `Outreach Decision` = `Review` in **118 righe su 118** | è il valore di default scritto da `io.py:540`; non porta informazione |
| `Contact Search Status` ha 3 valori (`Contacted` 32, `Not started` 77, `No suitable contact` 9) | unico campo informativo |
| `First Contact Date` popolata in **60 righe su 118** | secondo campo informativo |
| `Contact Search Status` e `First Contact Date` **si contraddicono in 48 righe su 118 (41%)** | nessuno dei due è affidabile da solo |
| `Recall` popolata in **0 righe** | campo nuovo, mai usato finora |

Quindi servono due cose: **un vocabolario minimo nuovo** (per il colore primario) e
**uno stato derivato** che renda visibili le contraddizioni esistenti invece di
nasconderle.

---

## Modifica 1 — `Outreach Decision` da costante a enumerazione

Oggi il campo ha un solo valore effettivo (`Review`). Si propone:

| Valore | Significato | Chi lo scrive |
|---|---|---|
| `Review` | non ancora deciso — **default per ogni riga nuova** | la macchina |
| `Yes` | approvato per l'outreach | la persona |
| `No` | scartato | la persona |

Questo è **l'unico vocabolario realmente nuovo** introdotto dalla proposta, ed è la
fonte del colore primario. La macchina continua a scrivere `Review` e non avanza mai
questo campo da sola — coerente con A4 ("Le proposte entrano nel bacino da valutare,
con `Outreach Decision = Review`, anche se il matching è alto").

## Modifica 2 — stato derivato, calcolato e non memorizzato

Si propone di **non** aggiungere una colonna di stato compilata a mano: sarebbe un
terzo campo da mantenere, in contraddizione con i due già esistenti. Lo stato è
invece **calcolato da Excel** a partire dalle colonne già presenti, con il primo
criterio che matcha:

| # | Stato derivato | Regola | Colore |
|---|---|---|---|
| 1 | `INCONSISTENT` | `Contact Search Status` contraddice `First Contact Date` | ambra |
| 2 | `RECALL DUE` | `Recall` non vuota e `<= TODAY()` | arancio |
| 3 | `RECALL SCHEDULED` | `Recall` non vuota e futura | turchese |
| 4 | `CONTACTED` | `First Contact Date` non vuota | blu |
| 5 | `NO CONTACT FOUND` | `Contact Search Status = No suitable contact` | grigio |
| 6 | `TO CONTACT` | `Contact Search Status = Not started` senza data | nessuno |
| 7 | `EXCLUDED` | `Outreach Decision = No` | grigio + barrato |

La regola 1 è in prima posizione di proposito: rende le **48 righe contraddittorie
esistenti** una lista di lavoro che si accorcia da sola man mano che la review le
sistema, a costo zero per la macchina. È un problema di qualità del dato che esiste
già e che oggi non è visibile in nessuna vista.

I colori sono implementati come **regole di formattazione condizionale** installate
una volta dal comando `color`, non come riempimenti scritti dalla macchina. Motivo:
la macchina non scrive mai uno stile nel file delle persone, quindi il suo impatto
ricorrente resta "aggiungere valori in righe vuote". Inoltre il colore si aggiorna
nell'istante in cui la persona cambia il menù a tendina, senza eseguire nulla.

---

## Conseguenze tecniche da recepire in A4

1. **`Notes` va diviso in due colonne.** `Notes` è oggi l'unica colonna che *sia* la
   macchina *sia* la persona scrivono: `add_verified.py:158` concatena il testo della
   macchina a quello della persona con `" | "`, in modo irreversibile. Al momento è
   latente (0 celle su 49 contengono il separatore), ma è irrecuperabile al primo
   caso. Si propone `Matching Notes` (macchina) e `Reviewer Notes` (persona), portando
   la tabella A4 da 22 a 23 colonne prima di `Company ID`.

2. **`Company ID` come colonna di identità.** L'identità per nome è già rotta: 5
   nomi (`JAKALA`, `KPMG`, `NTT DATA`, `PwC`, `TeamViewer`) compaiono su due righe
   ciascuno, e i due writer storici li risolvevano in direzioni **opposte**
   (`history.ts` li univa, `add_verified.py` teneva l'ultima riga rendendo la prima
   irraggiungibile). L'ID è `polids-<sha1(nome normalizzato)[:8]>`, **assegnato una
   volta e memorizzato, mai ricalcolato**: un hash sul contenuto sopravvive a
   `"Loro Piana"` → `"Loro Piana S.p.A."` ma non a `"Moncler"` → `"Moncler Group"`.
   Le 5 coppie duplicate **non vengono unite automaticamente**: unirle
   richiederebbe di scegliere fra due insiemi di campi di contatto, entrambi di
   proprietà umana. Sono segnalate in `index/duplicate-names-report.csv`.

3. **Le date vanno scritte come date reali, non come testo.** Una formula di
   formattazione condizionale come `$W2<=TODAY()` confronta **stringhe** se la cella
   contiene `"03/09/2026"`, e restituisce silenziosamente la risposta sbagliata
   mentre la cella sembra corretta. Formato di visualizzazione: `DD/MM/YYYY`.

4. **Due righe del canonical CSV sono corrotte da un incolla errato** e vanno
   corrette a mano: `Bain & Company` e `Moncler` hanno `Verification Status` e
   `Last Checked` spostati di +1 (contengono rispettivamente testo di intestazione e
   il nome dell'azienda della riga successiva). Sono segnalate da `doctor` e da
   `init-review`. **Non corrette automaticamente**: la correzione richiede di sapere
   quali fossero i valori veri.

5. **Una riga orfana** (indice 82) contiene solo `First Contact Date = 03/09/2026`
   senza nome azienda, fra `Logotel` e `Doctolib`. È una data inserita da una persona
   il cui proprietario è andato perso. **Non attribuita automaticamente** e non
   cancellata: da risolvere a mano.

---

## Cosa NON cambia

- `Verification Status` mantiene l'insieme chiuso già definito in A4.
- La macchina non invia mai email e non avanza mai `Outreach Decision` da sola.
- `First Contact Date` e `Recall` restano di proprietà umana: la macchina le lascia
  vuote sulle righe nuove e le conserva su quelle esistenti.
- Nessuna scrittura nel CSV canonico da parte della macchina, salvo `backfill-ids`
  (una tantum, solo aggiunta di colonna) e `pull` (che riporta le decisioni umane).
