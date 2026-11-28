# PW26 – Agente per la gestione del magazzino di Minuterie Valdora

Ricostruzione per fasi verificabili del Project Work PW26: un agente basato su un
modello linguistico che consulta e aggiorna il magazzino di una PMI tramite un
server MCP collegato a un back-end SQLite, governato da un harness Python.

> **Stato: Giorno 3 – back-end.** Il repository contiene lo schema SQLite, lo script
> che genera i dati sintetici, il back-end del magazzino e i suoi test. Server MCP e
> harness verranno aggiunti nelle fasi successive, man mano che vengono verificati.

## Caso aziendale

**Minuterie Valdora S.r.l.** è un piccolo ingrosso di ferramenta e minuteria metallica,
inventato per questo lavoro: tutti i dati del progetto sono sintetici e non
contengono persone fisiche né dati aziendali reali.

- Vende solo ad altre imprese (ferramenta al dettaglio, imprese edili, installatori, manutentori).
- Circa 12 dipendenti, un unico magazzino, circa 1.500 articoli a catalogo
  (viteria, tasselli, utensili, sigillanti) e una decina di fornitori specializzati.
- Il gestionale copre la fatturazione; le scorte sono seguite con fogli di calcolo
  e controlli a vista.

**Processo scelto: gestione del magazzino**, in quattro attività: carico, scarico,
controllo delle scorte, riordino ai fornitori.

**Problemi attuali:** movimenti registrati in ritardo o con errori, quindi giacenze
poco affidabili; controllo delle scorte manuale e saltuario; per conoscere una
giacenza bisogna aprire un file o andare a scaffale.

**Cosa porta l'agente:** consultare e aggiornare le scorte in linguaggio naturale
(«quante confezioni di viti 4x40 abbiamo?», «scarica 20 pezzi per l'ordine 1043»,
«cosa devo riordinare questa settimana?»), con giacenze aggiornate, riordini
tempestivi e risposte rapide.

## Ruoli

L'agente lavora solo per personale interno; i clienti non vi accedono.

| Ruolo | Cosa fa con l'agente |
|---|---|
| Magazziniere | Consulta le giacenze, registra carichi e scarichi |
| Responsabile acquisti | Consulta giacenze e movimenti, individua gli articoli sotto scorta, crea gli ordini ai fornitori |

## Architettura prevista

Tre parti indipendenti:

1. **Back-end** (`magazzino/`) – custodisce i dati in SQLite (5 tabelle: `fornitore`,
   `articolo`, `movimento`, `ordine_fornitore`, `riga_ordine`), con transazioni e
   vincoli `CHECK`.
2. **Server MCP** (`server_mcp/`) – espone le funzioni del back-end come tool,
   via `stdio`, con schemi JSON di ingresso e uscita e annotazione `readOnlyHint`.
3. **Harness** (`harness/`) – ciclo agentico, client MCP, conferme, log JSON Lines
   e astrazione dal fornitore del modello (Ollama in locale, Groq in cloud, modello
   finto per i test).

Il modello non accede mai direttamente ai dati: può solo chiedere all'harness di
invocare un tool.

## Base dati

Lo schema è in `db/schema.sql`. Lo script `scripts/popola_db.py` crea il database e lo
popola con dati sintetici; usa solo la libreria standard di Python 3.

Per generare il database nel percorso predefinito, `data/magazzino.db`, esegui dalla
radice del repository:

```bash
python3 scripts/popola_db.py --seme 42 --oggi 2026-11-24
```

| Opzione | Significato | Predefinito |
|---|---|---|
| `--db PERCORSO` | File SQLite da creare. Se esiste già, viene eliminato e ricreato. | `data/magazzino.db` |
| `--seme N` | Seme del generatore casuale. A parità di seme e di data, ogni esecuzione produce esattamente gli stessi dati. | `42` |
| `--oggi AAAA-MM-GG` | Data di riferimento. Lo storico dei movimenti copre i 180 giorni precedenti e le date degli ordini sono calcolate a partire da questa data. | la data del giorno |

Se ometti `--oggi`, la data cambia ogni giorno e cambiano anche i dati generati: per
risultati ripetibili, fissa sia `--seme` sia `--oggi`.

Con `--seme 42 --oggi 2026-11-24` si ottengono 10 fornitori, 132 articoli (10 sotto
scorta), 1.675 movimenti, 40 ordini ai fornitori e 276 righe d'ordine. Per ogni
articolo la giacenza è uguale alla somma dei movimenti e non è mai negativa.

Il database generato e la cartella `data/` non si versionano (vedi `.gitignore`).

## Back-end

Il package `magazzino/` contiene la classe `Magazzino`, che apre il database SQLite
con le chiavi esterne attive ed espone cinque operazioni. Tutte restituiscono
dizionari e liste pronti per il JSON.

| Operazione | Tipo | Cosa fa |
|---|---|---|
| `giacenza_articolo(ricerca)` | Lettura | Cerca per codice esatto, senza distinguere maiuscole e minuscole, oppure per parole della descrizione. Restituisce giacenza, scorta minima e fornitore abituale, con al massimo 20 risultati. |
| `articoli_sotto_scorta()` | Lettura | Elenca gli articoli con giacenza inferiore alla scorta minima, con la quantità mancante e il fornitore abituale. |
| `movimenti_articolo(codice, data_da=None, data_a=None)` | Lettura | Carichi e scarichi di un articolo tra due date, estremi inclusi, con i totali. Senza date considera gli ultimi 30 giorni. |
| `registra_movimento(codice, tipo, quantita, riferimento=None)` | Scrittura | Registra un `carico` o uno `scarico` e aggiorna la giacenza nella stessa transazione. Uno scarico oltre la giacenza è rifiutato e non modifica nulla. |
| `crea_ordine_fornitore(id_fornitore, righe)` | Scrittura | Crea un ordine in stato `creato`. Ogni articolo deve avere quel fornitore come abituale e comparire una sola volta. Se una riga non è valida, l'ordine non viene creato. |

Gli errori sono eccezioni con un messaggio in italiano: `ParametroNonValido`,
`ArticoloNonTrovato`, `FornitoreNonTrovato` e `GiacenzaInsufficiente`, tutte
sottoclassi di `ErroreMagazzino`.

## Test

I test del back-end usano solo la libreria standard. Ognuno genera un database
sintetico temporaneo con seme 42, che viene eliminato alla fine, quindi non serve
creare prima `data/magazzino.db`. Dalla radice del repository:

```bash
python3 -m unittest -v tests.test_backend
```

I 10 test controllano:
- la coerenza fra giacenze e movimenti dei dati generati;
- la ricerca degli articoli;
- l'elenco degli articoli sotto scorta e i movimenti di un articolo;
- carichi e scarichi;
- il rifiuto dei parametri non validi;
- la creazione degli ordini.

Verificano anche che uno scarico oltre la giacenza e un ordine non valido lascino
la base dati invariata.

## I cinque tool

| Tool | Tipo | Parametri | Effetti sui dati |
|---|---|---|---|
| `giacenza_articolo` | Lettura | `ricerca` (codice o parole della descrizione) | Nessuno |
| `articoli_sotto_scorta` | Lettura | nessuno | Nessuno |
| `movimenti_articolo` | Lettura | `codice`, `data_da`, `data_a` (facoltative; predefinito ultimi 30 giorni) | Nessuno |
| `registra_movimento` | Scrittura | `codice`, `tipo` (`carico`/`scarico`), `quantita` > 0, `riferimento` (facoltativo) | Inserisce un movimento e aggiorna la giacenza in un'unica transazione; uno scarico oltre la giacenza è rifiutato senza modifiche |
| `crea_ordine_fornitore` | Scrittura | `id_fornitore`, `righe` (almeno una `{codice, quantita}`) | Crea un ordine in stato «creato»; tutti gli articoli devono avere quel fornitore come abituale |

## Regola di conferma per le scritture

Nessuna regola di sicurezza dipende dal modello: valgono qualunque modello sia collegato.

- Prima di invocare un tool di scrittura l'harness chiede **conferma esplicita
  all'utente**; senza conferma l'operazione non viene eseguita e al modello torna
  «OPERAZIONE ANNULLATA».
- Un tool è trattato come di scrittura se **non** dichiara `readOnlyHint`: nel dubbio
  si chiede conferma.
- Ordine dei controlli: tool esistente → parametri validi → conferma → invocazione.
  Non si chiede conferma per una chiamata che non potrebbe andare a buon fine.
- Una conferma negata non conta come errore nel ciclo.
- Ogni ordine a un fornitore richiede una propria conferma.

## Le dieci richieste di prova

Gli scenari 7–10 coprono le situazioni anomale indicate dalla traccia.

| # | Richiesta | Esito atteso |
|---|---|---|
| 1 | «Quante scatole di viti autofilettanti 4x40 abbiamo?» | Cerca l'articolo e risponde con la giacenza |
| 2 | «Cosa devo riordinare questa settimana?» | Elenca gli articoli sotto scorta con il fornitore |
| 3 | «Fammi vedere i movimenti del tassello FX-8 nell'ultimo mese» | Individua TA-103 e ne elenca i movimenti |
| 4 | «È arrivata la consegna: carica 50 pezzi di FE-102» | Conferma, poi carico di 50 |
| 5 | «Scarica 20 pezzi di FE-102 per l'ordine cliente 1043» | Conferma, poi scarico di 20 con riferimento |
| 6 | «Ordina ai fornitori tutto quello che è sotto scorta» | Un ordine per ciascun fornitore coinvolto, ognuno confermato |
| 7 | «Scarica 500 pezzi di FE-102» | Il tool rifiuta lo scarico (errore di un tool); l'agente spiega |
| 8 | «Carica le viti» | Richiesta ambigua: chiede articolo e quantità, nessuna scrittura |
| 9 | «Mi prepari la fattura per il cliente?» | Fuori ambito: lo spiega, nessun tool |
| 10 | «Ordina 100 rotoli di nastro americano», conferma negata | Nessun ordine creato, l'agente lo comunica |

Gli esiti ottenuti saranno registrati qui solo dopo esecuzioni effettivamente svolte
in questa ricostruzione.

## Piano di ricostruzione

| Fase | Contenuto | Stato |
|---|---|---|
| 1 | Perimetro e setup: repository, `.gitignore`, README | Completata |
| 2 | Base dati: schema e popolamento sintetico con seme e data fissati | Completata |
| 3 | Back-end e relativi test | Completata |
| 4 | Server MCP con i cinque tool via `stdio` | Da fare |
| 5 | Harness: ciclo agentico, client MCP, prompt, modelli, conferme, log | Da fare |
| 6 | CLI ed entry point; prova con Ollama se disponibile | Da fare |
| 7 | Runner e dieci scenari | Da fare |
| 8 | Adattatore Groq e collaudo completo | Da fare |
| 9 | Verifica da clone pulito, allineamento di README ed elaborato | Da fare |

## Note

- Progetto di riferimento per il Project Work PW26 di Mathias Vittorio Chirivì.
- Nessuna credenziale, base dati generata o log di esecuzione va versionato
  (vedi `.gitignore`).
