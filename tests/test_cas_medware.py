"""Cas réel anonymisé (valeurs seules, aucune donnée identifiante) issu des 4 documents MedWare :
bilan mensuel, prescription de dialyse, synthèse des séances, récapitulatif des traitements."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hd import dossier, rules, schema  # noqa: E402
from hd.modeles import Extraction  # noqa: E402

EXTRACTION = Extraction.model_validate({
    "bilans": [
        {"date": "2026-11-04", "uree_pre": 16.5, "uree_post": 2.0, "na": 140, "k_pre": 4.36, "k_post": 3.55, "ca": 2.19, "phos": 1.16,
         "albumine": 33, "prealbumine": 0.13, "hb": 12.3, "cst": 0.38, "ferritine": 713, "crp": 20.4, "ntprobnp": 3770, "bicar": 23.1,
         "ktv_daug": 2.48, "npcr": 1.05},
        {"date": "2026-10-07", "uree_pre": 14.1, "uree_post": 1.8, "na": 138, "k_pre": 4.75, "k_post": 3.60, "ca": 2.22, "phos": 1.63,
         "pth": 16.6, "albumine": 33, "prealbumine": 0.11, "pal_os": 25.9, "hb": 12.5, "cst": 0.20, "ferritine": 671, "crp": 18.1,
         "ntprobnp": 3136, "bicar": 22.6, "ktv_daug": 2.45, "npcr": 0.92},
        {"date": "2026-09-02", "uree_pre": 13.3, "na": 138, "k_pre": 5.80, "ca": 2.23, "phos": 1.58, "albumine": 31, "prealbumine": 0.13,
         "hb": 12.0, "cst": 0.23, "ferritine": 447, "crp": 14.1, "ntprobnp": 3212, "bicar": 23.5, "ktv_daug": 2.33, "npcr": 0.86},
        {"date": "2026-08-05", "na": 142, "k_pre": 4.22, "albumine": 29, "prealbumine": 0.10, "hb": 10.9, "cst": 0.19, "ferritine": 452,
         "crp": 13.1, "ntprobnp": 3643, "bicar": 30.3, "ktv_daug": 2.43, "npcr": 0.73},
    ],
    "traitements": [
        {"categorie": "HIF-PHI", "molecule": "Roxadustat", "dose": 50, "unite": "mg", "frequence": "par séance (3/sem)", "statut": "En cours", "date_modif": "2026-11-09"},
        {"categorie": "Fer IV", "molecule": "Venofer", "dose": 100, "unite": "mg", "frequence": "toutes les 2 semaines", "statut": "En cours", "date_modif": "2026-11-10"},
        {"categorie": "Chélateur du potassium", "molecule": "Lokelma", "dose": 10, "unite": "g", "frequence": "par jour", "statut": "En cours", "date_modif": "2026-08-07"},
        {"categorie": "Vitamine D native", "molecule": "Uvedose", "dose": 50000, "unite": "UI", "frequence": "autre / à préciser", "statut": "En cours"},
        {"categorie": "Compléments nutritionnels oraux", "molecule": "Delical HP HC", "dose": 2, "unite": "bouteilles", "frequence": "par jour", "statut": "En cours"},
    ],
    "prescriptions": [{"date": "2026-11-25", "bain_k": 3, "bain_ca": 1.5, "nad": 139, "bain_hco3": 31, "poids_sec": 64, "technique": "HDF",
                       "duree_h": 4, "seances_sem": 3, "qb": 350, "qd": 700, "abord": "FAV radio-céphalique D"}],
    "hypotensions_intradialytiques": True,
    "pas_pre_moyenne": 105, "poids_fin_moyen": 62.83, "ppid_moyenne": 1.86, "ktv_ionique_moyen": 1.82,
    "incertitudes": [],
})


def _analyse():
    bio, tx, rx, ctx = dossier.fusionner(schema.empty_bio(), schema.empty_tx(), schema.empty_rx(), dict(schema.CTX_DEFAULT), EXTRACTION)
    return {r.key: r for r in rules.analyse(rules.Case(bio, tx, rx, ctx))}


def txt(r, level=None):
    return " | ".join(f.text for f in r.findings if level is None or f.level == level)


def test_roxadustat_debute_apres_le_bilan_non_evalue():
    r = _analyse()["anemie"]
    assert "après ce bilan" in txt(r)
    assert "Sous HIF-PHI" not in txt(r)
    assert "38 %" in r.summary  # CST fraction convertie


def test_fer_debute_apres_le_bilan_pas_repropose():
    r = _analyse()["anemie"]
    assert "suspendre" not in txt(r, rules.MODIF)
    assert "décision déjà prise" in txt(r)


def test_poids_de_fin_sous_le_ps_signale():
    r = _analyse()["volemie"]
    assert "sous PS prescrit 64" in txt(r, rules.ALERTE)


def test_potassium_k3_lokelma_ok():
    assert _analyse()["potassium"].status == rules.OK


def test_isonatrique_et_epuration_ok():
    res = _analyse()
    assert "Dialyse quasi isonatrique" in txt(res["sodium"])
    assert "1,82" in res["epuration"].summary and res["epuration"].status == rules.OK


def test_nutrition_en_amelioration_sous_cno():
    r = _analyse()["nutrition"]
    assert "en amélioration" in txt(r) and rules.MODIF not in [f.level for f in r.findings]
