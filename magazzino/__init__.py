"""Back-end del magazzino: accesso alla base dati SQLite."""

from .backend import (
    ArticoloNonTrovato,
    ErroreMagazzino,
    FornitoreNonTrovato,
    GiacenzaInsufficiente,
    Magazzino,
    ParametroNonValido,
)

__all__ = [
    "Magazzino",
    "ErroreMagazzino",
    "ParametroNonValido",
    "ArticoloNonTrovato",
    "FornitoreNonTrovato",
    "GiacenzaInsufficiente",
]
