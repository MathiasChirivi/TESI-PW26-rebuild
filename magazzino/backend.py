"""Back-end del magazzino.

Espone le cinque operazioni che il server MCP (Fase 2) trasformerà in tool:
tre di lettura e due di scrittura. Ogni metodo restituisce dati semplici
(dizionari e liste), già pronti per essere serializzati in JSON.

Gli errori sono eccezioni con un messaggio in italiano comprensibile
all'utente: il server MCP li girerà all'agente così come sono.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

TIPI_MOVIMENTO = ("carico", "scarico")
MAX_RISULTATI_RICERCA = 20
GIORNI_MOVIMENTI_DEFAULT = 30


class ErroreMagazzino(Exception):
    """Errore generico del back-end."""


class ParametroNonValido(ErroreMagazzino):
    """Un parametro ha un valore non ammesso."""


class ArticoloNonTrovato(ErroreMagazzino):
    """Il codice articolo non esiste."""


class FornitoreNonTrovato(ErroreMagazzino):
    """L'identificativo del fornitore non esiste."""


class GiacenzaInsufficiente(ErroreMagazzino):
    """Lo scarico supera la quantità disponibile."""


def _riga_a_dict(riga: sqlite3.Row) -> dict:
    return {chiave: riga[chiave] for chiave in riga.keys()}


def _controlla_data(valore: str, nome: str) -> str:
    try:
        return date.fromisoformat(valore).isoformat()
    except (TypeError, ValueError):
        raise ParametroNonValido(
            f"Il parametro '{nome}' deve essere una data nel formato AAAA-MM-GG, ricevuto: {valore!r}."
        ) from None


def _controlla_quantita(valore, nome: str = "quantita") -> int:
    # bool è una sottoclasse di int: va escluso esplicitamente.
    if isinstance(valore, bool) or not isinstance(valore, int) or valore <= 0:
        raise ParametroNonValido(f"Il parametro '{nome}' deve essere un numero intero maggiore di zero, ricevuto: {valore!r}.")
    return valore


class Magazzino:
    """Accesso alla base dati del magazzino."""

    def __init__(self, percorso_db: str | Path):
        percorso_db = Path(percorso_db)
        if not percorso_db.exists():
            raise ErroreMagazzino(
                f"Base dati non trovata: {percorso_db}. Creala con 'python scripts/popola_db.py'."
            )
        self._conn = sqlite3.connect(percorso_db)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def chiudi(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Magazzino":
        return self

    def __exit__(self, *exc) -> None:
        self.chiudi()

    # ------------------------------------------------------------------ utilità

    def _articolo(self, codice: str) -> sqlite3.Row:
        if not isinstance(codice, str) or not codice.strip():
            raise ParametroNonValido("Il parametro 'codice' deve essere un codice articolo non vuoto, es. FE-102.")
        riga = self._conn.execute(
            "SELECT * FROM articolo WHERE codice = ? COLLATE NOCASE", (codice.strip(),)
        ).fetchone()
        if riga is None:
            raise ArticoloNonTrovato(f"Nessun articolo con codice {codice.strip()!r}.")
        return riga

    # ------------------------------------------------------------------ lettura

    def giacenza_articolo(self, ricerca: str) -> list[dict]:
        """Cerca articoli per codice esatto o per parole della descrizione.

        Con un codice esistente restituisce solo quell'articolo; altrimenti
        restituisce gli articoli la cui descrizione contiene tutte le parole
        cercate (al massimo MAX_RISULTATI_RICERCA). Lista vuota se non trova nulla.
        """
        if not isinstance(ricerca, str) or not ricerca.strip():
            raise ParametroNonValido("Il parametro 'ricerca' deve contenere un codice o qualche parola della descrizione.")
        ricerca = ricerca.strip()
        colonne = (
            "a.codice, a.descrizione, a.categoria, a.unita_misura, a.giacenza, a.scorta_minima, "
            "a.giacenza < a.scorta_minima AS sotto_scorta, f.ragione_sociale AS fornitore"
        )
        base = f"SELECT {colonne} FROM articolo a JOIN fornitore f USING (id_fornitore)"

        riga = self._conn.execute(f"{base} WHERE a.codice = ? COLLATE NOCASE", (ricerca,)).fetchone()
        if riga is not None:
            return [self._formatta_giacenza(riga)]

        parole = [p for p in re.split(r"\s+", ricerca) if p]
        condizioni = " AND ".join("(a.descrizione LIKE ? OR a.codice LIKE ?)" for _ in parole)
        parametri: list[str] = []
        for parola in parole:
            parametri += [f"%{parola}%", f"%{parola}%"]
        righe = self._conn.execute(
            f"{base} WHERE {condizioni} ORDER BY a.codice LIMIT ?", (*parametri, MAX_RISULTATI_RICERCA)
        ).fetchall()
        return [self._formatta_giacenza(r) for r in righe]

    @staticmethod
    def _formatta_giacenza(riga: sqlite3.Row) -> dict:
        dati = _riga_a_dict(riga)
        dati["sotto_scorta"] = bool(dati["sotto_scorta"])
        return dati

    def articoli_sotto_scorta(self) -> list[dict]:
        """Articoli con giacenza inferiore alla scorta minima, con il fornitore abituale."""
        righe = self._conn.execute(
            """
            SELECT a.codice, a.descrizione, a.unita_misura, a.giacenza, a.scorta_minima,
                   a.scorta_minima - a.giacenza AS mancanti,
                   f.id_fornitore, f.ragione_sociale AS fornitore
            FROM articolo a JOIN fornitore f USING (id_fornitore)
            WHERE a.giacenza < a.scorta_minima
            ORDER BY f.ragione_sociale, a.codice
            """
        ).fetchall()
        return [_riga_a_dict(r) for r in righe]

    def movimenti_articolo(self, codice: str, data_da: str | None = None, data_a: str | None = None) -> dict:
        """Carichi e scarichi di un articolo tra due date (estremi inclusi).

        Senza date restituisce gli ultimi GIORNI_MOVIMENTI_DEFAULT giorni.
        """
        articolo = self._articolo(codice)
        fine = _controlla_data(data_a, "data_a") if data_a else date.today().isoformat()
        inizio = (
            _controlla_data(data_da, "data_da")
            if data_da
            else (date.fromisoformat(fine) - timedelta(days=GIORNI_MOVIMENTI_DEFAULT)).isoformat()
        )
        if inizio > fine:
            raise ParametroNonValido(f"La data iniziale ({inizio}) è successiva alla data finale ({fine}).")

        righe = self._conn.execute(
            """
            SELECT id_movimento, tipo, quantita, data_ora, riferimento
            FROM movimento
            WHERE codice_articolo = ? AND substr(data_ora, 1, 10) BETWEEN ? AND ?
            ORDER BY data_ora
            """,
            (articolo["codice"], inizio, fine),
        ).fetchall()
        movimenti = [_riga_a_dict(r) for r in righe]
        return {
            "codice": articolo["codice"],
            "descrizione": articolo["descrizione"],
            "periodo": {"da": inizio, "a": fine},
            "totale_carichi": sum(m["quantita"] for m in movimenti if m["tipo"] == "carico"),
            "totale_scarichi": sum(m["quantita"] for m in movimenti if m["tipo"] == "scarico"),
            "giacenza_attuale": articolo["giacenza"],
            "movimenti": movimenti,
        }

    # ------------------------------------------------------------------ scrittura

    def registra_movimento(self, codice: str, tipo: str, quantita: int, riferimento: str | None = None) -> dict:
        """Registra un carico o uno scarico e aggiorna la giacenza nella stessa transazione.

        Uno scarico superiore alla giacenza viene rifiutato e non modifica nulla.
        """
        if tipo not in TIPI_MOVIMENTO:
            raise ParametroNonValido(f"Il parametro 'tipo' deve essere 'carico' o 'scarico', ricevuto: {tipo!r}.")
        quantita = _controlla_quantita(quantita)
        if riferimento is not None and not isinstance(riferimento, str):
            raise ParametroNonValido("Il parametro 'riferimento' deve essere un testo.")

        with self._conn:  # transazione: commit se tutto va bene, rollback altrimenti
            articolo = self._articolo(codice)
            prima = articolo["giacenza"]
            if tipo == "scarico" and quantita > prima:
                raise GiacenzaInsufficiente(
                    f"Impossibile scaricare {quantita} {articolo['unita_misura']} di {articolo['codice']}: "
                    f"la giacenza è {prima}."
                )
            dopo = prima + quantita if tipo == "carico" else prima - quantita
            istante = datetime.now().isoformat(timespec="seconds")
            cursore = self._conn.execute(
                "INSERT INTO movimento (codice_articolo, tipo, quantita, data_ora, riferimento) VALUES (?, ?, ?, ?, ?)",
                (articolo["codice"], tipo, quantita, istante, riferimento),
            )
            self._conn.execute("UPDATE articolo SET giacenza = ? WHERE codice = ?", (dopo, articolo["codice"]))

        return {
            "id_movimento": cursore.lastrowid,
            "codice": articolo["codice"],
            "descrizione": articolo["descrizione"],
            "tipo": tipo,
            "quantita": quantita,
            "data_ora": istante,
            "riferimento": riferimento,
            "giacenza_precedente": prima,
            "giacenza_attuale": dopo,
            "sotto_scorta": dopo < articolo["scorta_minima"],
        }

    def crea_ordine_fornitore(self, id_fornitore: int, righe: list[dict]) -> dict:
        """Crea un ordine (stato 'creato') a un fornitore.

        `righe` è una lista di {"codice": str, "quantita": int}. Ogni articolo
        deve avere come fornitore abituale quello indicato e comparire una sola volta.
        """
        if isinstance(id_fornitore, bool) or not isinstance(id_fornitore, int):
            raise ParametroNonValido(f"Il parametro 'id_fornitore' deve essere un numero intero, ricevuto: {id_fornitore!r}.")
        if not isinstance(righe, list) or not righe:
            raise ParametroNonValido("Il parametro 'righe' deve essere una lista non vuota di {codice, quantita}.")

        with self._conn:
            fornitore = self._conn.execute(
                "SELECT id_fornitore, ragione_sociale FROM fornitore WHERE id_fornitore = ?", (id_fornitore,)
            ).fetchone()
            if fornitore is None:
                raise FornitoreNonTrovato(f"Nessun fornitore con id {id_fornitore}.")

            controllate: list[tuple[sqlite3.Row, int]] = []
            visti: set[str] = set()
            for indice, riga in enumerate(righe, start=1):
                if not isinstance(riga, dict) or "codice" not in riga or "quantita" not in riga:
                    raise ParametroNonValido(f"La riga {indice} deve avere i campi 'codice' e 'quantita'.")
                articolo = self._articolo(riga["codice"])
                quantita = _controlla_quantita(riga["quantita"], f"righe[{indice}].quantita")
                if articolo["codice"] in visti:
                    raise ParametroNonValido(f"L'articolo {articolo['codice']} compare più volte nell'ordine.")
                if articolo["id_fornitore"] != id_fornitore:
                    raise ParametroNonValido(
                        f"L'articolo {articolo['codice']} non è fornito da {fornitore['ragione_sociale']}."
                    )
                visti.add(articolo["codice"])
                controllate.append((articolo, quantita))

            oggi = date.today().isoformat()
            cursore = self._conn.execute(
                "INSERT INTO ordine_fornitore (id_fornitore, data_ordine, stato) VALUES (?, ?, 'creato')",
                (id_fornitore, oggi),
            )
            id_ordine = cursore.lastrowid
            self._conn.executemany(
                "INSERT INTO riga_ordine (id_ordine, codice_articolo, quantita) VALUES (?, ?, ?)",
                [(id_ordine, a["codice"], q) for a, q in controllate],
            )

        righe_ordine = [
            {
                "codice": a["codice"],
                "descrizione": a["descrizione"],
                "quantita": q,
                "prezzo_acquisto": a["prezzo_acquisto"],
                "importo": round(q * a["prezzo_acquisto"], 2),
            }
            for a, q in controllate
        ]
        return {
            "id_ordine": id_ordine,
            "fornitore": fornitore["ragione_sociale"],
            "data_ordine": oggi,
            "stato": "creato",
            "righe": righe_ordine,
            "totale_stimato": round(sum(r["importo"] for r in righe_ordine), 2),
        }
