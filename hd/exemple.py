"""Cas FICTIF de démonstration (repris de la maquette discutée lors de la calibration)."""
import pandas as pd

from .schema import BIO_FIELDS, RX_FIELDS, TX_FIELDS, CTX_DEFAULT, normalize

BIO = [
    {"date": "2026-04-07", "hb": 12.8, "ferritine": 410, "cst": 27, "crp": 4.1, "na": 137, "k_pre": 4.9, "bicar": 21.0,
     "ca": 2.24, "phos": 1.41, "pth": 310, "pal_os": 26.9, "albumine": 41, "prealbumine": 0.34, "npcr": 1.10,
     "ntprobnp": 21500, "ktv_daug": 1.41, "commentaire": "bilan mensuel"},
    {"date": "2026-07-07", "hb": 12.1, "ferritine": 380, "cst": 25, "crp": 5.0, "na": 136, "k_pre": 4.6, "bicar": 20.9,
     "ca": 2.20, "phos": 1.48, "pth": 390, "pal_os": 56.7, "albumine": 40, "prealbumine": 0.32, "npcr": 1.05,
     "ntprobnp": 28800, "ktv_daug": 1.38, "commentaire": "bilan mensuel"},
    {"date": "2026-10-06", "hb": 11.5, "hb_post": 12.3, "ferritine": 352, "cst": 24, "crp": 6.2, "na": 136, "k_pre": 4.7, "k_post": 3.1,
     "bicar": 20.6, "ca": 2.22, "phos": 1.52, "pth": 457, "pal_os": 102, "albumine": 39, "prealbumine": 0.31, "npcr": 1.02,
     "ntprobnp": 34031, "ktv_daug": 1.34, "ktv_ionique": 1.45, "uree_pre": 21.4, "uree_post": 6.3, "commentaire": "bilan mensuel"},
]

TX = [
    {"categorie": "ASE", "molecule": "Mircera", "dose": 75, "unite": "µg", "frequence": "toutes les 4 semaines / mensuel",
     "statut": "En cours", "motif": "IV en dialyse"},
    {"categorie": "Fer IV", "molecule": "Venofer", "dose": 100, "unite": "mg", "frequence": "toutes les 2 semaines", "statut": "En cours"},
    {"categorie": "Calcimimétique (agoniste CaSR)", "molecule": "Cinacalcet", "dose": 60, "unite": "mg", "frequence": "2 fois/jour",
     "statut": "En cours", "date_modif": "2026-10-14", "dose_precedente": 30, "motif": "majoré devant la hausse des PAL osseuses"},
    {"categorie": "Chélateur du phosphore", "molecule": "Renvela", "dose": 2400, "unite": "mg", "frequence": "3 fois/jour", "statut": "En cours",
     "motif": "aux repas"},
    {"categorie": "Vitamine D native", "molecule": "Zymad", "dose": 80000, "unite": "UI", "frequence": "toutes les 4 semaines / mensuel",
     "statut": "En cours"},
    {"categorie": "Antihypertenseur", "molecule": "Amlodipine", "dose": 10, "unite": "mg", "frequence": "par jour", "statut": "En cours"},
    {"categorie": "Antihypertenseur", "molecule": "Métoprolol", "dose": 50, "unite": "mg", "frequence": "par jour", "statut": "Suspendu"},
]

RX = [
    {"date": "2026-07-01", "bain_k": 2, "bain_ca": 1.5, "nad": 138, "bain_hco3": 32, "poids_sec": 79.0, "technique": "HDF",
     "duree_h": 4, "seances_sem": 3, "qb": 320, "qd": 500, "abord": "FAV radio-céphalique gauche"},
    {"date": "2026-10-01", "bain_k": 2, "bain_ca": 1.5, "nad": 138, "bain_hco3": 32, "poids_sec": 78.5, "technique": "HDF",
     "duree_h": 4, "seances_sem": 3, "qb": 320, "qd": 500, "abord": "FAV radio-céphalique gauche"},
]

CTX = {**CTX_DEFAULT, "poids_kg": 78.5, "abord_type": "FAV", "thrombose": "Non renseigné", "hypotensions_id": "Non",
       "pas_pre": 150, "observance_chelateurs": "Non vérifiée",
       "notes": "Cas fictif de démonstration."}


def load():
    return (
        normalize(pd.DataFrame(BIO), BIO_FIELDS),
        normalize(pd.DataFrame(TX), TX_FIELDS),
        normalize(pd.DataFrame(RX), RX_FIELDS),
        dict(CTX),
    )
