"""Remplissage des onglets à partir d'une extraction de captures (sans appel à l'API)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hd import dossier, exemple, rules, schema  # noqa: E402
from hd.modeles import Extraction  # noqa: E402

EXTRACTION = Extraction.model_validate({
    "bilans": [
        {"date": "2026-10-07", "hb": 10.7, "hb_post": 11.2, "k_pre": 3.63, "k_post": 3.63, "ca": 2.18, "uree_pre": 15.5, "uree_post": 4.7, "pth": 185},
        {"date": "2026-10-05", "hb": 11.2},
    ],
    "traitements": [
        {"categorie": "ASE", "molecule": "Mircera", "dose": 100, "unite": "µg", "frequence": "toutes les 4 semaines / mensuel", "statut": "Suspendu"},
        {"categorie": "Fer IV", "molecule": "Venofer", "dose": 100, "unite": "mg", "frequence": "par semaine", "statut": "En cours"},
    ],
    "prescriptions": [{"date": None, "bain_k": 2, "nad": 139, "poids_sec": 65, "abord": "KT tunnelisé JID"}],
    "poids_kg": 65,
    "recirculation_pct": 18,
    "hypotensions_intradialytiques": True,
    "incertitudes": ["Fréquence du Mircera"],
})


def test_cst_en_fraction_converti_en_pourcentage():
    import pandas as pd
    df = schema.normalize(pd.DataFrame([{"date": "2026-11-04", "cst": 0.38}, {"date": "2026-10-07", "cst": 20}]), schema.BIO_FIELDS)
    assert df["cst"].tolist() == [38.0, 20.0]


def test_fusion_dossier_vide():
    bio, tx, rx, ctx = dossier.fusionner(schema.empty_bio(), schema.empty_tx(), schema.empty_rx(), dict(schema.CTX_DEFAULT), EXTRACTION)
    assert len(bio) == 2 and bio["hb"].tolist() == [11.2, 10.7]  # trié par date
    assert len(tx) == 2 and len(rx) == 1
    assert ctx["poids_kg"] == 65 and ctx["hypotensions_id"] == "Oui" and ctx["recirculation"] == 18
    res = rules.analyse(rules.Case(bio, tx, rx, ctx))
    assert len(res) == 8


def test_fusion_dossier_existant_met_a_jour_par_molecule_et_date():
    b, t, r, c = exemple.load()
    bio, tx, rx, ctx = dossier.fusionner(b, t, r, c, EXTRACTION)
    assert len(bio) == len(b) + 2
    mircera = tx[tx["molecule"] == "Mircera"]
    assert len(mircera) == 1 and mircera.iloc[0]["dose"] == 100 and mircera.iloc[0]["statut"] == "Suspendu"
    assert len(tx) == len(t)  # Venofer existait déjà : mis à jour, pas dupliqué
    rules.analyse(rules.Case(bio, tx, rx, ctx))
