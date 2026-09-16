# Talent Placement e Design Lab · Guida di lavoro

Questa proposta usa Strategic Design come primo caso per un metodo riutilizzabile tra Master. Il risultato della ricerca è un bacino di opportunità documentate: le persone selezionano aziende e ruoli, confermano i contatti e rivedono le email prima dell’invio.

## Cinque file, quattro input per l’Agent

| File | Domanda a cui risponde | Ambito |
|---|---|---|
| 00 · Questa guida | Come lavoriamo e chi aggiorna cosa? | Spiegazione per il team |
| [A1 · Ricerca](A1-regole-ricerca.md) | Dove cercare e come verificare e valutare? | Comune a tutti i Master |
| [A2 · Profilo](Strategic%20design%20ED.28/A2-profilo-strategic-design.md) | A quali attività prepara questo Master? | Uno per Master |
| [A3 · Coorte](Strategic%20design%20ED.28/A3-cohort.yaml) | Quali esigenze, capacità e disponibilità hanno questi studenti? | Uno per edizione/gruppo |
| [A4 · Registrazione](A4-regole-registrazione.md) | Come conservare prove, storico e decisioni? | Comune a tutti i Master |

Per eseguire una ricerca bastano A1, l'A2 e l'A3 selezionati, e A4, insieme alla richiesta del momento e allo storico disponibile. 00 non è un quinto input obbligatorio. Leggere le versioni aggiornate senza compilare o mantenere una copia concatenata.

## Manutenzione e conferma

La seguente ripartizione è una proposta operativa: il team assegna i referenti effettivi.

| Contenuto | Chi aggiorna / conferma | Quando |
|---|---|---|
| A1 e A4 | Talent Placement | Quando cambia il metodo o emerge un problema verificato |
| A2: presenza delle aree, attività, risultati e limiti | Direttore e team didattico; Talent Placement aiuta a redigere | Prima del primo uso e quando cambia il percorso |
| A2: termini di ricerca | Talent Placement | Quando i risultati suggeriscono termini migliori |
| A3: esigenze, lingue e prove delle capacità | Coordinamento, sulla base di risposte e materiali degli studenti | A ogni edizione e quando cambiano i dati |
| A3: calendario e condizioni didattiche | Coordinamento con il team didattico | Prima di confermare la compatibilità delle opportunità |
| Aziende, ruoli, contatti e invio | Talent Placement / referente incaricato | Nei punti di revisione umana indicati in A4 |
| Contributi a un Lab e fattibilità | BD con direzione e coordinamento dei Master | Per ogni brief aziendale |

La validazione del percorso e le preferenze degli studenti sono due verifiche diverse. L’Agent propone: non attribuisce da solo una conferma al direttore e non modifica automaticamente i file di configurazione.

## Come aggiornare A2 e A3

In A2 il direttore rivede una scheda per area: presenza nel percorso, ruolo formativo, attività, elaborati, limiti e riferimento didattico. “Complementare” non significa “esclusa”. Confermare anche chi ha revisionato il documento e quando. Le keyword restano nella stessa scheda, a cura di Talent Placement.

In A3 mantenere soltanto dati reali. `null` indica un valore sconosciuto; `[]` indica nessuna voce registrata. Gli esempi nei commenti sono fittizi e non vanno copiati come risposte effettive. Distinguere condizioni operative di ricerca, preferenze, vincoli e capacità dimostrate. Le lingue ammesse per gli annunci non certificano quelle parlate dagli studenti.

Riutilizzare questionari, CV, portfolio e tabelle già disponibili. Indicare fonte e data; per informazioni individuali collegare la tabella esistente anziché duplicarla. Le sintesi di gruppo non descrivono automaticamente ogni studente.

## Avviare una ricerca

Esempio di richiesta: «Cerca opportunità di stage per Strategic Design usando A1, A2-profilo-strategic-design.md, A3-cohort.yaml e A4. Usa lo storico indicato in A3, se disponibile. Restituisci risultati in italiano nel task corrente, con prove e limiti della verifica. Non scrivere in Excel e non inviare email.»

L’Agent verifica che gli identificativi del Master coincidano. Se mancano dati della coorte può cercare per il Master con condizioni dichiarate, senza confermare idoneità individuale o disponibilità. Se lo storico manca, dichiara la deduplicazione parziale. Le prove vanno conservate come indicato in A4.

## Riutilizzo per un altro Master e per BD

Per un altro Master preparare il suo A2 e il suo A3, assegnare lo stesso `master_id` ai due file e riusare A1 e A4. Non modificare le regole comuni per inserire nomi, keyword o preferenze specifiche di un Master.

Il flusso A1–A4 riguarda stage e opportunità per studenti, non genericamente tutti i lavori junior. Per BD riusare A2 e A3 con un brief aziendale e una richiesta dedicata: confrontare Master, contributi, risultati attesi, parti non coperte e calendario. Non applicare al Lab il requisito di una vacancy di stage. Il riconoscimento didattico del Lab va verificato con il team.

## Stato del caso pilota

Struttura pronta per la revisione; contenuti del Master ancora da confermare e coorte incompleta. Il passo successivo è una ricerca reale: valutare pertinenza, correttezza delle prove, copertura, duplicati e lavoro umano necessario. L’organizzazione dei file non equivale alla validazione del metodo sul campo.
