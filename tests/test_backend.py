"""Test del back-end su una base dati sintetica temporanea.

Esecuzione dalla cartella del progetto:
    python -m unittest -v
"""

import random
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))
sys.path.insert(0, str(RADICE / "scripts"))

import popola_db  # noqa: E402
from magazzino import (  # noqa: E402
    ArticoloNonTrovato,
    FornitoreNonTrovato,
    GiacenzaInsufficiente,
    Magazzino,
    ParametroNonValido,
)


class TestMagazzino(unittest.TestCase):
    def setUp(self):
        self._cartella = tempfile.TemporaryDirectory()
        self.percorso = Path(self._cartella.name) / "test.db"
        popola_db.scrivi(self.percorso, popola_db.genera(random.Random(42), date.today()))
        self.m = Magazzino(self.percorso)

    def tearDown(self):
        self.m.chiudi()
        self._cartella.cleanup()

    def _conta(self, tabella):
        with sqlite3.connect(self.percorso) as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {tabella}").fetchone()[0]

    # --- dati sintetici

    def test_giacenze_coerenti_con_i_movimenti(self):
        with sqlite3.connect(self.percorso) as conn:
            incoerenti = conn.execute(
                """SELECT a.codice FROM articolo a JOIN movimento m ON m.codice_articolo = a.codice
                   GROUP BY a.codice
                   HAVING SUM(CASE m.tipo WHEN 'carico' THEN m.quantita ELSE -m.quantita END) != a.giacenza"""
            ).fetchall()
        self.assertEqual(incoerenti, [])

    def test_articoli_degli_scenari_presenti(self):
        for codice in popola_db.ARTICOLI_SCENARI:
            self.assertEqual(len(self.m.giacenza_articolo(codice)), 1, codice)
        self.assertLess(self.m.giacenza_articolo("FE-102")[0]["giacenza"], 500)

    # --- lettura

    def test_giacenza_per_codice_e_per_descrizione(self):
        self.assertEqual(self.m.giacenza_articolo("fe-102")[0]["codice"], "FE-102")
        risultati = self.m.giacenza_articolo("viti autofilettanti 4x40")
        self.assertEqual([r["codice"] for r in risultati], ["VI-103"])
        self.assertEqual(self.m.giacenza_articolo("FX-8")[0]["codice"], "TA-103")
        self.assertEqual(self.m.giacenza_articolo("articolo che non esiste"), [])

    def test_articoli_sotto_scorta(self):
        elenco = self.m.articoli_sotto_scorta()
        self.assertEqual(len(elenco), popola_db.NUM_SOTTO_SCORTA)
        self.assertTrue(all(a["giacenza"] < a["scorta_minima"] for a in elenco))

    def test_movimenti_articolo(self):
        risultato = self.m.movimenti_articolo("TA-103", "2000-01-01", date.today().isoformat())
        self.assertGreater(len(risultato["movimenti"]), 0)
        with self.assertRaises(ParametroNonValido):
            self.m.movimenti_articolo("TA-103", "ieri")
        with self.assertRaises(ArticoloNonTrovato):
            self.m.movimenti_articolo("XX-999")

    # --- scrittura

    def test_carico_e_scarico_aggiornano_la_giacenza(self):
        prima = self.m.giacenza_articolo("FE-102")[0]["giacenza"]
        carico = self.m.registra_movimento("FE-102", "carico", 50, "Bolla di prova")
        self.assertEqual(carico["giacenza_attuale"], prima + 50)
        scarico = self.m.registra_movimento("FE-102", "scarico", 20)
        self.assertEqual(scarico["giacenza_attuale"], prima + 30)
        self.assertEqual(self.m.giacenza_articolo("FE-102")[0]["giacenza"], prima + 30)

    def test_scarico_oltre_la_giacenza_non_cambia_nulla(self):
        movimenti_prima = self._conta("movimento")
        giacenza_prima = self.m.giacenza_articolo("FE-102")[0]["giacenza"]
        with self.assertRaises(GiacenzaInsufficiente):
            self.m.registra_movimento("FE-102", "scarico", 500)
        self.assertEqual(self._conta("movimento"), movimenti_prima)
        self.assertEqual(self.m.giacenza_articolo("FE-102")[0]["giacenza"], giacenza_prima)

    def test_parametri_non_validi(self):
        for tipo, quantita in (("reso", 5), ("carico", 0), ("carico", -3), ("carico", "10"), ("carico", True)):
            with self.assertRaises(ParametroNonValido):
                self.m.registra_movimento("FE-102", tipo, quantita)

    def test_crea_ordine_fornitore(self):
        id_fornitore = self.m.articoli_sotto_scorta()[0]["id_fornitore"]
        articoli = [a for a in self.m.articoli_sotto_scorta() if a["id_fornitore"] == id_fornitore]
        ordine = self.m.crea_ordine_fornitore(
            id_fornitore, [{"codice": a["codice"], "quantita": a["mancanti"]} for a in articoli]
        )
        self.assertEqual(ordine["stato"], "creato")
        self.assertEqual(len(ordine["righe"]), len(articoli))

    def test_ordine_non_valido_non_scrive_nulla(self):
        ordini_prima = self._conta("ordine_fornitore")
        with self.assertRaises(FornitoreNonTrovato):
            self.m.crea_ordine_fornitore(999, [{"codice": "FE-102", "quantita": 10}])
        with self.assertRaises(ParametroNonValido):  # NS-101 non è fornito dal fornitore di FE-102
            self.m.crea_ordine_fornitore(5, [{"codice": "FE-102", "quantita": 10}, {"codice": "NS-101", "quantita": 5}])
        with self.assertRaises(ParametroNonValido):
            self.m.crea_ordine_fornitore(5, [])
        self.assertEqual(self._conta("ordine_fornitore"), ordini_prima)


if __name__ == "__main__":
    unittest.main()
