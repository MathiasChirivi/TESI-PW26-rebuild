-- Schema della base dati del magazzino (Minuterie Valdora S.r.l., azienda fittizia).
-- Corrisponde allo schema ER della Fase 1: 5 tabelle, relazioni 1:N.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS fornitore (
    id_fornitore    INTEGER PRIMARY KEY,
    ragione_sociale TEXT    NOT NULL UNIQUE,
    email           TEXT,
    giorni_consegna INTEGER NOT NULL CHECK (giorni_consegna > 0)
);

CREATE TABLE IF NOT EXISTS articolo (
    codice          TEXT    PRIMARY KEY,
    descrizione     TEXT    NOT NULL,
    categoria       TEXT    NOT NULL,
    unita_misura    TEXT    NOT NULL,
    giacenza        INTEGER NOT NULL CHECK (giacenza >= 0),
    scorta_minima   INTEGER NOT NULL CHECK (scorta_minima >= 0),
    prezzo_acquisto REAL    NOT NULL CHECK (prezzo_acquisto > 0),
    id_fornitore    INTEGER NOT NULL REFERENCES fornitore (id_fornitore)
);

CREATE TABLE IF NOT EXISTS movimento (
    id_movimento    INTEGER PRIMARY KEY,
    codice_articolo TEXT    NOT NULL REFERENCES articolo (codice),
    tipo            TEXT    NOT NULL CHECK (tipo IN ('carico', 'scarico')),
    quantita        INTEGER NOT NULL CHECK (quantita > 0),
    data_ora        TEXT    NOT NULL,
    riferimento     TEXT
);

CREATE TABLE IF NOT EXISTS ordine_fornitore (
    id_ordine    INTEGER PRIMARY KEY,
    id_fornitore INTEGER NOT NULL REFERENCES fornitore (id_fornitore),
    data_ordine  TEXT    NOT NULL,
    stato        TEXT    NOT NULL CHECK (stato IN ('creato', 'inviato', 'ricevuto'))
);

CREATE TABLE IF NOT EXISTS riga_ordine (
    id_ordine       INTEGER NOT NULL REFERENCES ordine_fornitore (id_ordine),
    codice_articolo TEXT    NOT NULL REFERENCES articolo (codice),
    quantita        INTEGER NOT NULL CHECK (quantita > 0),
    PRIMARY KEY (id_ordine, codice_articolo)
);

CREATE INDEX IF NOT EXISTS idx_movimento_articolo_data ON movimento (codice_articolo, data_ora);
CREATE INDEX IF NOT EXISTS idx_articolo_fornitore ON articolo (id_fornitore);
