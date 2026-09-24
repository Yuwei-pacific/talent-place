# A4 · Regole di registrazione

Modulo comune a tutti i Master. I percorsi di storico, report precedenti e lista contatti sono parametri della richiesta (o indicati in A3), non proprietà di questo file. Usare prima i riferimenti della richiesta, altrimenti `history_file`, `previous_reports` e `previous_contact_list` di A3. Se non sono disponibili o accessibili, dichiarare copertura parziale e non inventare un file di default.

## Storico e deduplicazione

Leggere senza modificare lo storico indicato. Non sostituirlo con un omonimo nel workspace se la richiesta ne indica un altro.

Deduplicare per URL diretto normalizzato (senza rimuovere parametri identificativi dell’annuncio), ID all’interno della relativa fonte e combinazione azienda + titolo normalizzato + luogo. Confermare l’identità prima di fondere record; titoli simili con ID differenti non sono automaticamente lo stesso ruolo. Una pagina Careers generica non è una chiave di deduplicazione di ruolo.

Stesso ruolo già presente: non riproporlo. Stessa azienda con ruolo nuovo: produrre una riga con Notes che inizia `[UPDATE EXISTING ROW]`. Azienda nuova: `[NEW COMPANY]`. Nella riga di aggiornamento elencare solo i nuovi ruoli di questa ricerca; l’integrazione nello storico conserva i ruoli precedenti dopo approvazione umana.

Raggruppare per azienda/unità di contatto. Mantenere brand e business unit; non fondere automaticamente tutte le società di un gruppo senza conferma della referente di contatto comune. Conservare evidenze separate per ciascun ruolo e tutte le fonti realmente consultate.

`Company / Outreach Account` è **l’azienda che assume**. Una pagina aggregata — LinkedIn Jobs, Indeed, BoF Careers, un job board di terzi, una testata o un servizio di collocamento che ripubblica annunci — è una fonte di scoperta e va in `Sources / Portals`, mai qui. Se un ruolo è stato trovato su un aggregatore, risalire all’azienda reale e usarla come account; se non è identificabile con certezza, tenere il candidato fra i non risolti invece di attribuirlo all’aggregatore.

## Contatti e decisioni

Essere presenti nel Company Index non significa essere già stati contattati. `Previously Contacted?` va ricavato da prove storiche esplicite. Assenza di storico o valori contraddittori: `To verify`, con nota sul conflitto. Se due campi dello stesso account si contraddicono (es. `Previously Contacted? = No` e `Contact Search Status = Contact found`), non scegliere un lato: verificare prima dell’outreach.

Non sovrascrivere contatti e stati già presenti con i default. Per nuove aziende senza ricerca contatti: `Contact Search Status = New job found`; nome, ruolo ed email/LinkedIn vuoti. (`Not started` era il valore della macchina fino al 2026-09-23 e questa riga lo diceva ancora: dal cambio di schema significa invece che una persona ha preso in carico la riga, quindi scriverlo qui avrebbe marcato come «già vista» ogni azienda nuova.) Inserire solo referenti supportati da fonti pubbliche affidabili; nessuna email dedotta. L’utente conferma il referente prima dell’outreach.

`Contact Search Status` è una **lista chiusa di sette valori**. La macchina scrive `New job found` su ogni riga nuova; gli altri li imposta la persona in revisione, e ciascuno descrive un momento diverso del rapporto con l’azienda:

- `New job found` — la macchina ha trovato un ruolo nuovo qui e nessuno l’ha ancora guardato. È il default, ed è l’unico valore senza un colore proprio: bianco è lo sfondo del foglio.
- `Job not suitable` — il ruolo non è adatto: la riga resta come traccia, non si contatta nessuno.
- `Not started` — la persona ha **preso in carico** la riga; la ricerca del referente non è ancora iniziata.
- `Potential contact` — il ruolo è adatto, il referente non è ancora identificato.
- `Contact found` — il referente è identificato e verificato.
- `Contacted` — il referente è stato contattato.
- `Job found` — il referente ha confermato che la posizione esiste ed è aperta.

`Not started` era il default della macchina fino al 2026-09-23. Adesso significa che una persona ha accettato la riga, e per questo ha un colore: prima si confondeva con lo sfondo, quindi «nessuno l’ha guardata» e «l’ho presa in carico» erano indistinguibili. Le righe esistenti scritte dalla macchina si spostano su `New job found` con `migrate-review --reinterpret`, che è un gesto esplicito: un valore ancora in vocabolario non passa da `LEGACY_CONTACT_STATUS`.

Un valore fuori da questo elenco fa **rifiutare l’intera riga** da `stage`. La lista è chiusa di proposito: è l’asse su cui `Review.xlsx` colora l’intera riga (bianco / grigio / lilla / giallo / blu / blu scuro / verde, nell’ordine sopra), e un valore improvvisato renderebbe il colore privo di significato. Un valore **senza colore proprio diventa bianco**, cioè indistinguibile dal default: ogni valore aggiunto deve avere il suo, ed è per questo che la lista è chiusa. Il valore storico `No suitable contact` resta nel CSV canonico come traccia di ciò che è già stato fatto, non va usato in output nuovi, e `migrate-review` lo converte quando una cartella viene aggiornata; `Contacted` era storico e dal 2026-09-23 non lo è più.

Le proposte entrano nel bacino da valutare, con `Outreach Decision = Review`, anche se il matching è alto. Nessuna scrittura nel CSV di riferimento. Excel viene aggiornato solo sui record confermati, conservando storico e decisioni. L’AI prepara la mail dopo selezione; la persona rivede e invia. Non inviare automaticamente.

## Destinazione dei risultati

- **TSV principale:** ruoli ammissibili con descrizione affidabile ed etichetta `pertinente` o `adiacente`. I dubbi su campi non dichiarati restano visibili; l’etichetta non certifica curricularità o idoneità individuale. Un’area A2 da confermare è segnalata come `ipotesi operativa`.
- **Esclusioni:** ruoli `fuori profilo` o incompatibili con i vincoli applicabili. Non inserirli nel TSV principale o nel relativo Role Count. Mostrare fino a cinque esempi motivati. L'incompatibilità si stabilisce su ciò che l'annuncio **dichiara**: modalità di lavoro, stato della candidatura, lingua obbligatoria. Un campo non dichiarato mantiene l'incertezza e non esclude (A1) — un ruolo che nessuno ha potuto confermare resta nel bacino da valutare, con il dubbio in evidenza, non fra gli esclusi.
- **Non risolti:** identità o descrizione non affidabile, oppure luogo non classificabile secondo il formato richiesto. Elencare separatamente URL, informazione mancante e verifica necessaria, senza etichetta di pertinenza o score inventati.
- **Duplicati storici:** non riproporli come nuove opportunità; contarli nel riepilogo di ricerca, separatamente dagli esclusi e dai non risolti.

Assenza di storico non prova che un’azienda sia nuova: usare `[HISTORY TO VERIFY]` al posto di NEW/UPDATE finché manca il confronto. Anche l’affermazione “non duplicato” va qualificata come non verificata.

## Dove conservare le prove

Nelle Notes del TSV riportare per ogni ruolo il numero corrispondente a titolo e link, l’etichetta, una breve citazione delle responsabilità e la motivazione. Indicare la fonte della citazione e la data di controllo; la pagina aziendale resta il link principale quando disponibile.

Se le prove non sono leggibili nella cella, aggiungere alla stessa risposta un’appendice “Evidenze per ruolo”, collegata tramite azienda + numero del ruolo + ID/URL. Per ciascun ruolo riportare responsabilità citate, fonte di scoperta, link alternativi, stato della pagina, lingue, date, modalità di lavoro e curricularità, con i dati mancanti espliciti. Nella cella indicare il riferimento all’appendice.

Se la richiesta indica una cartella di output, conservare lì il report e le evidenze come risultati della ricerca, senza alterare lo storico approvato. Altrimenti mantenere tutto nella risposta corrente, dichiarando che non è stato salvato un archivio esterno. Non aggiungere nuovi file di configurazione per ogni ricerca.

## Evidenze e report Indeed

Per ogni ruolo conservare titolo, ID, fonte di scoperta, URL principale e alternative, azienda, luogo, modalità di lavoro, date, stato candidatura, curricularità, lingue, attività pertinenti, motivazione, dubbi e data di verifica. Le informazioni devono essere attribuibili al singolo ruolo, anche quando la riga finale raggruppa un’azienda.

`Sources / Portals` contiene Indeed solo se ha realmente scoperto o incrociato il ruolo; la preferenza per il link ufficiale non cancella la sua provenienza.

Riga obbligatoria (italiano; gli stati Used/Unavailable restano in inglese): `Indeed: Used/Unavailable; candidati unici trovati X; inclusi nel TSV Y; duplicati o esclusi Z`.

X = ruoli unici effettivamente trovati o incrociati via Indeed durante il controllo, deduplicati fra query Indeed. Y = quei ruoli presenti nel TSV finale. Z = quelli esclusi o già presenti nello storico. Stesso ruolo trovato anche su LinkedIn conta una volta e conserva entrambe le fonti. Se restano ruoli non risolti fuori dal TSV, indicare separatamente P in nota; allora X = Y + Z + P. Used se il connettore è stato effettivamente usato; se restituisce un errore senza risultati utilizzabili, Unavailable e motivo. Dichiarare eventuale uso misto connettore/pagine pubbliche e blocchi parziali. Il numero riguarda ruoli, non aziende.

## Sintesi e TSV

Prima del TSV, non più di cinque righe in italiano: data; numero dei ruoli nuovi inclusi; distribuzione Milano / resto d’Italia / resto UE (categorie disgiunte); fino a tre priorità; fonti limitate e report Indeed. Un ruolo con più sedi resta un ruolo: assegnarlo alla prima sede ammessa secondo priorità e dichiarare questa convenzione. Numero di ruoli valutati o in sospeso separato dal numero di nuovi ruoli inclusi.

Il TSV è una proposta da revisionare: un blocco di codice di testo, Tab reali fra campi (non punto e virgola, non virgola), una riga per azienda, nessun Tab o a capo interno alle celle. Per ruoli, link e informazioni correlate usare `1. ... | 2. ...`, mantenendo lo stesso indice. Link aziendale diretto preferito; se non verificabile, conservare il link affidabile disponibile e indicare il limite. Prima di consegnare, verificare che ogni riga abbia esattamente lo stesso numero di Tab dell’header; se una cella contiene `;` è ammesso (testo libero), se contiene un Tab la riga è invalida.

Colonne esatte, nell’ordine del CSV canonico. Le prime 20 sono obbligatorie; le colonne 21–22 (`First Contact Date`, `Recall`) sono estensioni di produzione: l’AI non le compila per i nuovi ruoli (restano vuote), ma deve conservarle quando aggiorna una riga esistente che già le contiene:

```text
Company / Outreach Account	In Italy?	Locations	Master-fit Themes	Matching Job Titles	Matching Score	Job Links	Role Count	Curricular Evidence	Work Modes	Sources / Portals	Previously Contacted?	Contact Search Status	Contact Name	Contact Role	Contact Email / LinkedIn	Outreach Decision	Notes	Verification Status	Last Checked	First Contact Date	Recall
```

`In Italy?`: Yes per sedi dei ruoli inclusi tutte italiane, No se tutte fuori Italia, Mixed se entrambe. È una convenzione del report sui ruoli elencati, non un’affermazione su tutte le sedi aziendali. Se la sede non consente la classificazione, tenere il candidato fra i non risolti senza inventare un valore. `Role Count`: numero dei ruoli unici nella riga. `Last Checked`: YYYY-MM-DD.

`Matching Score`: lo score 0-100 di ogni ruolo, con lo **stesso indice** di `Matching Job Titles`, `Job Links` e `Locations` — `1. 92 | 2. 78 | 3. 62`. Lo score serve solo a ordinare, non sostituisce l’etichetta e **non si inventa**: un ruolo senza descrizione letta lascia la sua posizione vuota, non uno zero. Se un ruolo non ha score, non scriverne uno.

Notes: prefisso NEW/UPDATE (oppure HISTORY TO VERIFY se manca lo storico); per ogni nuovo ruolo l’etichetta A1 (`pertinente` / `adiacente`) e una motivazione breve citando le responsabilità. Formato per ruolo: `[etichetta] motivazione`. Lo score **non** sta qui: vive in `Matching Score`. Se l’area di A2 è ancora da confermare, aggiungere `ipotesi operativa`. Ordinare le aziende: prima chi ha almeno un ruolo `pertinente`, poi `adiacente`; a parità, score più alto, poi più ruoli nuovi. L’etichetta misura la pertinenza, non lo stato delle verifiche.

`Notes` in `Review.xlsx` è l’unica colonna che la macchina **semina** e la persona poi **possiede**: la macchina la scrive solo quando crea la riga, e da quel momento non la tocca più. Serve un solo posto dove annotare, non due.

Se manca una descrizione affidabile, non assegnare etichetta né punteggio: conservare il candidato nei non risolti, fuori dal TSV di opportunità valutate. `Verification Status` usa uno dei valori ammessi, seguito se serve da `;` e un dettaglio libero (max una frase):

- `Employer verified active` — pagina aziendale/ATS aperta con candidatura visibile.
- `Portal verified` — solo pagina portale (LinkedIn/Indeed/altro) verificata, sito aziendale non raggiunto.
- `Legacy result — recheck` — ruolo dallo storico, non riverificato in questa ricerca.
- `Blocked — <motivo>` — accesso bloccato (login, CAPTCHA, 403/410, pagina rimossa); motivo obbligatorio.
- `To verify — <campo>` — pagina aperta ma un campo chiave manca (es. `To verify — curricular status`).

Un semplice “detail_ok” non basta: indicare sempre quale fonte è stata verificata.

Questo elenco vincola **ciò che produce una ricerca**: il TSV, che `stage` verifica riga per riga. La copia della colonna che vive in `Review.xlsx` è invece un testo che legge una persona — nessuna selezione, nessun raggruppamento e nessun filtro la usa. Resta quindi com’è dove non corrisponde all’elenco, e non va allineata a mano per farla combaciare.

La differenza con `Contact Search Status` è voluta, non una svista. Quella è **strutturale**: è l’asse su cui `Review.xlsx` colora l’intera riga, e un valore fuori elenco la rende bianca — cioè indistinguibile da `Not started`. Per questo la macchina lo rifiuta in ingresso e lo segnala. `Verification Status` è **di riferimento**: si legge, non si interroga.

Se nessun nuovo ruolo è ammissibile e valutabile, scrivere “Oggi nessun nuovo stage ammissibile e non duplicato.” e produrre il solo header. Se lo storico non è verificabile, usare invece “Oggi nessuno stage ammissibile tra quelli verificati; deduplicazione storica non verificabile.” Segnalare eventuali candidati non risolti o copertura limitata: zero risultati non prova che non esistano opportunità.

Dopo il TSV elencare fino a cinque ruoli vicini al target ma esclusi, con link e motivo. Non confondere escluso per incompatibilità, duplicato storico e non verificabile: sono esiti diversi.
