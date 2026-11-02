# Test di ambiente per la ricerca stage

Questo test serve a capire se la ricerca stage può funzionare sul tuo computer. Non tocca i file di lavoro: scrive solo in una cartella di prova. La parte iniziale richiede circa 15 minuti.

## Cosa ti serve (te lo prepara Yuwei)

- Il tuo account Claude del team e il file `talent-placement-probe.zip`.
- Sul tuo computer, sincronizzate con OneDrive, due cartelle: `talent-place/config` e `jobSearch_outPut/TEST-probe`.

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

Manda a Yuwei il file `probe-report.jsonl`, che trovi nella cartella `TEST-probe`, e compila il foglio dei risultati.

**La prova completa** dura qualche ora e usa parte del tuo credito Claude. Falla solo quando te lo chiede Yuwei, con il computer collegato alla corrente e senza chiuderlo.

## Se Cowork non funziona

Yuwei ti dirà come installare Node e Python e come ripetere il test dalla scheda **Code** della stessa app.
