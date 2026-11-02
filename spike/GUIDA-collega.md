# Test di ambiente per la ricerca stage

Questo test serve a capire se la ricerca stage può funzionare sul tuo computer. Non tocca i file di lavoro: scrive solo in una cartella di prova. La parte iniziale richiede circa 15 minuti.

## Cosa ti serve (te lo prepara Yuwei)

- Il tuo account Claude del team, il file `talent-placement-probe.zip` e il foglio `FOGLIO-risultati.md`.
- Sul tuo computer, sincronizzate con OneDrive, due cartelle: `talent-place/config` e `jobSearch_outPut/TEST-probe`.
- Clicca con il tasto destro su `TEST-probe` e scegli **Mantieni sempre su questo dispositivo**. Aspetta che la sincronizzazione finisca.

## Come si fa

1. Installa e apri l'app **Claude** per desktop, poi accedi con il tuo account.
2. Vai su **Customize > Plugins > Add > Upload plugin** e scegli il file zip.
3. Apri **Cowork** e inizia una nuova attività.
4. Aggiungi le due cartelle: `config` e `TEST-probe`.
5. Scrivi `/talent-placement-probe:probe` e premi Invio.
6. Segui le istruzioni di Claude. A volte ti chiederà di aprire un file in Excel o di cliccare su un file: fallo e rispondi quando hai finito.

## Cosa aspettarti

- `PASS` vuol dire che la prova è riuscita. `FAIL` vuol dire che non è riuscita, e anche questo è un'informazione utile: **non è un errore tuo**.
- `INCONCLUSIVE` vuol dire che LinkedIn ha chiesto di rallentare. Aspetta almeno 20 minuti e chiedi a Claude di ripetere quella prova.
- `REFUSED` vuol dire che è stata scelta la cartella sbagliata. Controlla di aver aggiunto `TEST-probe`.

## Alla fine

Compila `FOGLIO-risultati.md` e manda a Yuwei il foglio e il file `probe-report.jsonl`, che trovi nella cartella `TEST-probe`.

## La prova completa

Dura circa 3 ore e usa parte del tuo credito Claude. Falla solo quando te lo chiede Yuwei: scrivi a Claude «avvia la prova completa». Tieni il computer collegato alla corrente, con l'app Claude aperta. **Non impostare nulla per evitare la sospensione:** se il computer va in sospensione lo vogliamo sapere, quindi scrivilo sul foglio.

Alla fine manda a Yuwei anche `run-report.json` e `read-report.json`, che trovi in `TEST-probe/_probe-run`.

## Se Cowork non funziona

Yuwei ti dirà come installare Node e Python e come ripetere il test dalla scheda **Code** della stessa app.
