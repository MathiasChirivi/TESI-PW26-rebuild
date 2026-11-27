"""Crea la base dati del magazzino e la popola con dati sintetici.

Uso:
    python scripts/popola_db.py                  # crea data/magazzino.db
    python scripts/popola_db.py --db altro.db    # percorso diverso
    python scripts/popola_db.py --oggi 2027-01-15

Tutti i dati sono inventati: aziende fittizie, indirizzi email sul dominio
riservato .example, nessuna persona fisica. Il seme casuale è fisso, quindi a
parità di data di riferimento ogni esecuzione produce gli stessi dati.

Le giacenze sono coerenti con i movimenti: per ogni articolo la giacenza è
uguale alla somma dei carichi meno la somma degli scarichi, e non scende mai
sotto zero lungo lo storico.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
SCHEMA = RADICE / "db" / "schema.sql"
DB_DEFAULT = RADICE / "data" / "magazzino.db"

GIORNI_STORICO = 180
NUM_SOTTO_SCORTA = 10

# Articoli citati negli scenari di test: devono esistere e non finire sotto scorta per caso.
ARTICOLI_SCENARI = {"FE-102", "TA-103", "VI-103", "NS-101"}

# (prefisso codice, categoria, fornitore, email, giorni consegna, prezzo min-max in euro)
FORNITORI = [
    ("VI", "viteria", "Viteria Collebianco S.r.l.", "ordini@collebianco.example", 5, (3.0, 12.0)),
    ("BU", "bulloneria", "Bulloneria Altavalle S.r.l.", "acquisti@altavalle.example", 6, (2.0, 15.0)),
    ("TA", "tasselli e ancoranti", "Fissaggi Rocca Nera S.r.l.", "ordini@roccanera.example", 4, (4.0, 20.0)),
    ("CH", "chiodi e graffe", "Chioderia Pianalto S.r.l.", "vendite@pianalto.example", 7, (3.0, 10.0)),
    ("FE", "ferramenta", "Ferramenta Industriale Valmora S.r.l.", "ordini@valmora.example", 5, (1.0, 15.0)),
    ("UT", "utensili", "Utensilerie Monte Carso S.r.l.", "ordini@montecarso.example", 8, (4.0, 25.0)),
    ("NS", "nastri e sigillanti", "Sigillanti Borgofranco S.r.l.", "ordini@borgofranco.example", 4, (2.0, 9.0)),
    ("AB", "abrasivi", "Abrasivi Ripalta S.r.l.", "ordini@ripalta.example", 6, (1.0, 8.0)),
    ("CA", "catene e funi", "Catenificio Selvapiana S.r.l.", "vendite@selvapiana.example", 10, (1.0, 6.0)),
    ("LU", "lubrificanti e spray", "Chimica Pratoalto S.r.l.", "ordini@pratoalto.example", 5, (3.0, 12.0)),
]

# Catalogo per prefisso: (descrizione, unità di misura). I codici sono assegnati
# in ordine da 101: ad esempio la seconda voce di "FE" diventa FE-102.
CATALOGO = {
    "VI": [(f"Viti autofilettanti testa svasata {m} zincate, conf. 200 pz", "conf")
           for m in ("3.5x30", "4x30", "4x40", "4x50", "5x50", "5x60", "6x80")]
          + [(f"Viti metriche testa esagonale M{m}, conf. 100 pz", "conf")
             for m in ("5x20", "6x20", "6x30", "8x30", "8x40", "10x50")]
          + [("Viti per cartongesso 3.5x25 fosfatate, conf. 1000 pz", "conf")],
    "BU": [(f"Dado esagonale M{n} zincato, conf. 100 pz", "conf") for n in (5, 6, 8, 10, 12)]
          + [(f"Rondella piana M{n} zincata, conf. 200 pz", "conf") for n in (5, 6, 8, 10, 12)]
          + [(f"Bullone completo M{m} zincato", "pz") for m in ("8x60", "10x80", "12x100")]
          + [(f"Barra filettata M{n} da 1 m", "pz") for n in (8, 10, 12)],
    "TA": [(f"Tassello universale FX-{d} in nylon, conf. 100 pz", "conf") for d in (5, 6, 8, 10)]
          + [(f"Tassello per cartongesso {d} mm, conf. 50 pz", "conf") for d in (8, 10)]
          + [(f"Tassello metallico ad espansione M{n}, conf. 25 pz", "conf") for n in (6, 8, 10)]
          + [("Ancorante chimico vinilestere 300 ml", "pz"), ("Tassello a farfalla 10 mm, conf. 50 pz", "conf"),
             ("Tassello per laterizio forato 8 mm, conf. 100 pz", "conf"),
             ("Fascetta di fissaggio con tassello, conf. 50 pz", "conf"), ("Gancio a vite con tassello, conf. 25 pz", "conf")],
    "CH": [(f"Chiodi testa piana {l} mm, conf. 1 kg", "conf") for l in (20, 30, 40, 50, 60, 80, 100)]
          + [(f"Graffe per sparapunti {h} mm, conf. 1000 pz", "conf") for h in (6, 8, 10, 12, 14)]
          + [("Chiodi per cartongesso 25 mm, conf. 1 kg", "conf")],
    "FE": [("Staffa angolare zincata 30x30x30", "pz"), ("Staffa angolare zincata 40x40x40", "pz"),
           ("Staffa angolare rinforzata 60x60x60", "pz"), ("Piastra forata zincata 100x35", "pz"),
           ("Cerniera piana in acciaio 40 mm", "pz"), ("Cerniera piana in acciaio 60 mm", "pz"),
           ("Cerniera per mobili 35 mm", "pz"), ("Maniglia in alluminio interasse 128 mm", "pz"),
           ("Catenaccio a molla 120 mm", "pz"), ("Chiavistello zincato 80 mm", "pz"),
           ("Gancio a occhiolo 8x60, conf. 50 pz", "conf"), ("Reggimensola bianco 200 mm", "pz"),
           ("Fermaporta a pavimento in gomma", "pz"), ("Lucchetto in ottone 40 mm", "pz")],
    "UT": [("Cacciavite a taglio 5x100", "pz"), ("Cacciavite a croce PH2", "pz"), ("Set inserti 32 pz", "pz"),
           ("Martello da carpentiere 500 g", "pz"), ("Pinza universale 180 mm", "pz"),
           ("Chiave inglese regolabile 250 mm", "pz"), ("Metro a nastro 5 m", "pz"), ("Livella a bolla 60 cm", "pz"),
           ("Seghetto per metalli 300 mm", "pz"), ("Cutter con lame 18 mm", "pz"),
           ("Set chiavi a brugola 9 pz", "pz"), ("Punta per muro 6 mm", "pz"), ("Punta per muro 8 mm", "pz"),
           ("Punta per ferro 5 mm", "pz")],
    "NS": [("Nastro americano grigio 50 mm x 25 m", "rotolo"), ("Nastro di carta 30 mm x 50 m", "rotolo"),
           ("Nastro isolante nero 19 mm", "rotolo"), ("Nastro in PTFE per filetti", "rotolo"),
           ("Nastro biadesivo 19 mm x 5 m", "rotolo"), ("Silicone acetico trasparente 280 ml", "pz"),
           ("Silicone acetico bianco 280 ml", "pz"), ("Sigillante acrilico bianco 310 ml", "pz"),
           ("Schiuma poliuretanica 750 ml", "pz"), ("Colla di montaggio 310 ml", "pz"),
           ("Pistola per silicone", "pz"), ("Stucco per legno 250 g", "pz")],
    "AB": [(f"Disco lamellare 115 mm grana {g}", "pz") for g in (40, 60, 80, 120)]
          + [("Disco da taglio ferro 115 mm", "pz"), ("Disco da taglio ferro 230 mm", "pz"),
             ("Disco diamantato 115 mm", "pz"), ("Spazzola a tazza 75 mm", "pz")]
          + [(f"Carta abrasiva grana {g}, conf. 10 fogli", "conf") for g in (80, 120, 180, 240)],
    "CA": [(f"Catena zincata {d} mm", "m") for d in (3, 4, 5, 6)]
          + [(f"Fune in acciaio {d} mm", "m") for d in (3, 5)]
          + [(f"Moschettone zincato {d} mm", "pz") for d in (6, 8)]
          + [(f"Tenditore a occhio M{n}", "pz") for n in (6, 8)]
          + [(f"Morsetto per fune {d} mm", "pz") for d in (3, 5)]
          + [("Corda in polipropilene 8 mm", "m")],
    "LU": [("Sbloccante spray 400 ml", "pz"), ("Lubrificante al silicone spray 400 ml", "pz"),
           ("Grasso al litio 1 kg", "pz"), ("Olio per macchine 250 ml", "pz"), ("Vernice spray nera opaca 400 ml", "pz"),
           ("Vernice spray zincante 400 ml", "pz"), ("Antiruggine 750 ml", "pz"),
           ("Sgrassatore 750 ml", "pz"), ("Pulitore contatti spray 200 ml", "pz"),
           ("Lubrificante secco PTFE spray 400 ml", "pz")],
}

# Quantità tipica di uno scarico per unità di misura (minimo, massimo).
SCARICO_PER_UNITA = {"conf": (1, 10), "pz": (2, 30), "rotolo": (2, 24), "m": (5, 50)}


def istante_casuale(rng: random.Random, giorno: date) -> str:
    minuti = rng.randint(7 * 60 + 30, 17 * 60 + 30)
    return datetime.combine(giorno, time(minuti // 60, minuti % 60, rng.randint(0, 59))).isoformat()


def genera(rng: random.Random, oggi: date) -> dict:
    """Genera tutti i dati in memoria; nessuna scrittura su disco."""
    inizio = oggi - timedelta(days=GIORNI_STORICO)
    fornitori, articoli, ordini, movimenti = [], [], [], []

    for id_f, (prefisso, categoria, nome, email, giorni, (pmin, pmax)) in enumerate(FORNITORI, start=1):
        fornitori.append((id_f, nome, email, giorni))
        for n, (descrizione, unita) in enumerate(CATALOGO[prefisso], start=101):
            articoli.append({
                "codice": f"{prefisso}-{n}", "descrizione": descrizione, "categoria": categoria,
                "unita_misura": unita, "prezzo_acquisto": round(rng.uniform(pmin, pmax), 2), "id_fornitore": id_f,
            })

    per_fornitore: dict[int, list[dict]] = {}
    for a in articoli:
        per_fornitore.setdefault(a["id_fornitore"], []).append(a)

    eventi: dict[str, list[tuple[str, str, int, str]]] = {a["codice"]: [] for a in articoli}

    # Scarichi: ordini dei clienti nel periodo.
    for a in articoli:
        qmin, qmax = SCARICO_PER_UNITA[a["unita_misura"]]
        a["_scarico_max"] = qmax
        for _ in range(rng.randint(4, 14)):
            giorno = inizio + timedelta(days=rng.randint(1, GIORNI_STORICO - 1))
            eventi[a["codice"]].append((istante_casuale(rng, giorno), "scarico", rng.randint(qmin, qmax), ""))

    # Carichi: ordini ai fornitori, circa uno ogni 45 giorni, ricevuti dopo i giorni di consegna.
    for id_f, nome, _email, giorni in fornitori:
        for giorni_fa in (170, 125, 80, 35):
            data_ordine = oggi - timedelta(days=giorni_fa + rng.randint(-5, 5))
            scelti = rng.sample(per_fornitore[id_f], k=max(2, len(per_fornitore[id_f]) * rng.randint(4, 7) // 10))
            righe = [(a["codice"], a["_scarico_max"] * rng.randint(1, 3)) for a in scelti]
            ordini.append({"id_fornitore": id_f, "data_ordine": data_ordine, "righe": righe, "giorni": giorni})

    ordini.sort(key=lambda o: (o["data_ordine"], o["id_fornitore"]))
    for id_o, ordine in enumerate(ordini, start=1):
        ordine["id_ordine"] = id_o
        arrivo = ordine["data_ordine"] + timedelta(days=ordine["giorni"])
        for codice, quantita in ordine["righe"]:
            eventi[codice].append((istante_casuale(rng, arrivo), "carico", quantita, f"DDT ordine fornitore n. {id_o}"))

    # Giacenze finali coerenti con lo storico.
    candidati = [a for a in articoli if a["codice"] not in ARTICOLI_SCENARI]
    sotto_scorta = {a["codice"] for a in rng.sample(candidati, NUM_SOTTO_SCORTA)}

    for a in articoli:
        storico = sorted(eventi[a["codice"]])
        progressivo, minimo = 0, 0
        for _, tipo, quantita, _ in storico:
            progressivo += quantita if tipo == "carico" else -quantita
            minimo = min(minimo, progressivo)
        giacenza_minima_possibile = progressivo + max(0, -minimo)

        if a["codice"] in sotto_scorta:
            giacenza = giacenza_minima_possibile
            scorta = giacenza + rng.randint(5, 3 * a["_scarico_max"])
        else:
            scorta = 2 * a["_scarico_max"]
            giacenza = max(giacenza_minima_possibile, scorta + rng.randint(1, 3 * a["_scarico_max"]))

        iniziale = giacenza - progressivo
        if iniziale > 0:
            storico.insert(0, (istante_casuale(rng, inizio), "carico", iniziale, "Inventario iniziale"))
        a["giacenza"], a["scorta_minima"] = giacenza, scorta
        for istante, tipo, quantita, rif in storico:
            movimenti.append((istante, a["codice"], tipo, quantita, rif))

    # Numerazione degli ordini clienti in ordine cronologico.
    movimenti.sort()
    numerati, progressivo_oc = [], 1000
    for istante, codice, tipo, quantita, rif in movimenti:
        if tipo == "scarico":
            progressivo_oc += 1
            rif = f"Ordine cliente n. {progressivo_oc}"
        numerati.append((codice, tipo, quantita, istante, rif))

    return {"fornitori": fornitori, "articoli": articoli, "ordini": ordini, "movimenti": numerati}


def scrivi(percorso: Path, dati: dict) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    if percorso.exists():
        percorso.unlink()
    conn = sqlite3.connect(percorso)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        with conn:
            conn.executemany("INSERT INTO fornitore VALUES (?, ?, ?, ?)", dati["fornitori"])
            conn.executemany(
                "INSERT INTO articolo (codice, descrizione, categoria, unita_misura, giacenza, scorta_minima, "
                "prezzo_acquisto, id_fornitore) VALUES (:codice, :descrizione, :categoria, :unita_misura, "
                ":giacenza, :scorta_minima, :prezzo_acquisto, :id_fornitore)",
                dati["articoli"],
            )
            for o in dati["ordini"]:
                conn.execute(
                    "INSERT INTO ordine_fornitore VALUES (?, ?, ?, 'ricevuto')",
                    (o["id_ordine"], o["id_fornitore"], o["data_ordine"].isoformat()),
                )
                conn.executemany(
                    "INSERT INTO riga_ordine VALUES (?, ?, ?)", [(o["id_ordine"], c, q) for c, q in o["righe"]]
                )
            conn.executemany(
                "INSERT INTO movimento (codice_articolo, tipo, quantita, data_ora, riferimento) VALUES (?, ?, ?, ?, ?)",
                dati["movimenti"],
            )
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea e popola la base dati del magazzino con dati sintetici.")
    parser.add_argument("--db", type=Path, default=DB_DEFAULT, help=f"percorso del file (default: {DB_DEFAULT})")
    parser.add_argument("--seme", type=int, default=42, help="seme casuale (default: 42)")
    parser.add_argument("--oggi", type=date.fromisoformat, default=date.today(),
                        help="data di riferimento AAAA-MM-GG (default: oggi)")
    args = parser.parse_args()

    dati = genera(random.Random(args.seme), args.oggi)
    scrivi(args.db, dati)

    sotto = sum(1 for a in dati["articoli"] if a["giacenza"] < a["scorta_minima"])
    print(f"Base dati creata: {args.db}")
    print(f"  fornitori: {len(dati['fornitori'])}")
    print(f"  articoli:  {len(dati['articoli'])} (sotto scorta: {sotto})")
    print(f"  ordini:    {len(dati['ordini'])}")
    print(f"  movimenti: {len(dati['movimenti'])}")


if __name__ == "__main__":
    main()
