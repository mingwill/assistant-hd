"""Tests des règles validées lors de la calibration (chaque test = une correction du néphrologue)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hd import exemple, rules, schema  # noqa: E402


def case(bio=(), tx=(), rx=(), **ctx):
    return rules.Case(
        schema.normalize(pd.DataFrame(list(bio)), schema.BIO_FIELDS),
        schema.normalize(pd.DataFrame(list(tx)), schema.TX_FIELDS),
        schema.normalize(pd.DataFrame(list(rx)), schema.RX_FIELDS),
        {**schema.CTX_DEFAULT, **ctx},
    )


def texts(res, level=None):
    return " | ".join(f.text for f in res.findings if level is None or f.level == level)


RX_K2 = {"date": "2026-10-01", "bain_k": 2, "nad": 139, "bain_hco3": 32, "poids_sec": 70}
RX_K3 = {**RX_K2, "bain_k": 3}
MIRCERA = {"categorie": "ASE", "molecule": "Mircera", "dose": 75, "unite": "µg",
           "frequence": "toutes les 4 semaines / mensuel", "statut": "En cours"}


def test_exemple_tourne():
    b, t, r, c = exemple.load()
    res = rules.analyse(rules.Case(b, t, r, c))
    assert len(res) == 8
    assert "## BM" in rules.bm_draft(res)


def test_hb_haute_sans_ase_pas_un_probleme():
    r = rules.anemie(case([{"date": "2026-10-07", "hb": 14.8, "ferritine": 300, "cst": 25}]))
    assert r.status in (rules.OK,)
    assert "pas de cible" in texts(r)


def test_mircera_hb_haute_baisse_75_vers_50():
    r = rules.anemie(case([{"date": "2026-10-07", "hb": 11.6, "ferritine": 133, "cst": 28}], [MIRCERA], [RX_K3], thrombose="Non"))
    assert "75 → 50" in texts(r, rules.MODIF)


def test_thrombose_non_renseignee_demandee():
    r = rules.anemie(case([{"date": "2026-10-07", "hb": 10.5, "ferritine": 300, "cst": 25}], [MIRCERA], [RX_K3]))
    assert "thrombose de FAV" in texts(r, rules.MANQUE)


def test_mircera_plus_de_2_ugkg_discuter_roxadustat():
    big = {**MIRCERA, "dose": 200}
    r = rules.anemie(case([{"date": "2026-10-07", "hb": 10.5, "crp": 40, "ferritine": 600, "cst": 25}], [big], [RX_K3], thrombose="Non"))
    t = texts(r, rules.ALERTE)
    assert "roxadustat" in t and "inflammatoire" in t


def test_pas_de_cible_sous_hif_phi():
    roxa = {"categorie": "HIF-PHI", "molecule": "Roxadustat", "dose": 100, "unite": "mg", "frequence": "3 fois/semaine", "statut": "En cours"}
    r = rules.anemie(case([{"date": "2026-10-07", "hb": 10.1, "ferritine": 300, "cst": 25}], [roxa], [RX_K3]))
    assert "pas de cible" in texts(r, rules.OK)


def test_fer_pas_suspendu_si_ferritine_655_cst_30():
    fer = {"categorie": "Fer IV", "molecule": "Venofer", "dose": 100, "unite": "mg", "frequence": "toutes les 4 semaines / mensuel", "statut": "En cours"}
    r = rules.anemie(case([{"date": "2026-10-07", "hb": 11.5, "ferritine": 655, "cst": 30, "crp": 1.9}], [fer]))
    assert "suspendre" not in texts(r).lower()


def test_fer_suspendu_si_ferritine_845():
    fer = {"categorie": "Fer IV", "molecule": "Venofer", "dose": 100, "unite": "mg", "frequence": "toutes les 2 semaines", "statut": "En cours"}
    r = rules.anemie(case([{"date": "2026-10-07", "hb": 14.8, "ferritine": 845, "cst": 35}], [fer]))
    assert "suspendre temporairement" in texts(r, rules.MODIF)


def test_jamais_de_bain_k4():
    bio = [{"date": d, "k_pre": k} for d, k in [("2026-08-01", 3.6), ("2026-09-01", 3.5), ("2026-10-01", 3.7)]]
    r = rules.potassium(case(bio, [], [RX_K3]))
    assert "K4" not in texts(r)
    assert "maintenir K3" in texts(r)


def test_k_inferieur_5_sous_k2_retour_k3():
    r = rules.potassium(case([{"date": "2026-10-07", "k_pre": 4.7}], [], [RX_K2]))
    assert "bain K3" in texts(r, rules.MODIF)


def test_k_5_5_5_sous_k2_k3_plus_resine():
    r = rules.potassium(case([{"date": "2026-10-07", "k_pre": 5.3}], [], [RX_K2]))
    assert "K3 + chélateur" in texts(r, rules.MODIF)


def test_k_5_4_sous_k3_pas_inquietant():
    r = rules.potassium(case([{"date": "2026-10-07", "k_pre": 5.4}], [], [RX_K3]))
    assert r.status == rules.OK


def test_k_eleve_sous_k3_sans_resine_introduire_chelateur():
    r = rules.potassium(case([{"date": "2026-10-07", "k_pre": 5.9}], [], [RX_K3]))
    assert "introduire un chélateur" in texts(r, rules.MODIF)


def test_nad_isonatrique_moyenne_3_mois():
    bio = [{"date": d, "na": v} for d, v in [("2026-08-01", 135), ("2026-09-01", 136), ("2026-10-01", 134)]]
    r = rules.sodium(case(bio, [], [RX_K3]))  # NaD 139
    assert "139 → 135" in texts(r, rules.MODIF)


def test_bicar_21_8_ok():
    r = rules.bicarbonates(case([{"date": "2026-10-07", "bicar": 21.8}], [], [RX_K3]))
    assert r.status == rules.OK


def test_observance_verifiee_avant_majoration_chelateur():
    velph = {"categorie": "Chélateur du phosphore", "molecule": "Velphoro", "dose": 500, "unite": "mg", "frequence": "2 fois/jour", "statut": "En cours"}
    r = rules.phosphocalcique(case([{"date": "2026-10-07", "phos": 2.62, "ca": 2.2, "pth": 900}], [velph]))
    assert "observance" in texts(r, rules.MANQUE)


def test_hypocalcemie_moderee_toleree_sous_cinacalcet_et_pal_elevees():
    cina = {"categorie": "Calcimimétique (agoniste CaSR)", "molecule": "Cinacalcet", "dose": 60, "unite": "mg", "frequence": "par jour", "statut": "En cours"}
    bio = [{"date": "2026-08-01", "pth": 847, "pal_os": 70, "ca": 2.1}, {"date": "2026-10-07", "ca": 2.01, "phos": 1.26, "pth": 285, "pal_os": 66.4}]
    r = rules.phosphocalcique(case(bio, [cina]))
    assert "réduction du calcimimétique" not in texts(r)
    assert "tolérée" in texts(r)


def test_pal_osseuses_en_hausse_malgre_pth_dans_la_plage():
    bio = [{"date": "2026-04-01", "pth": 300, "pal_os": 26.9}, {"date": "2026-07-01", "pth": 390, "pal_os": 56.7},
           {"date": "2026-10-07", "pth": 457, "pal_os": 102, "ca": 2.22, "phos": 1.4}]
    r = rules.phosphocalcique(case(bio))
    assert "PAL osseuses" in texts(r, rules.MODIF)


def test_nt_probnp_hypotensions_antihypertenseurs_avant_poids_sec():
    ahtn = {"categorie": "Antihypertenseur", "molecule": "Lercanidipine", "dose": 10, "unite": "mg", "frequence": "par jour", "statut": "En cours"}
    bio = [{"date": "2026-09-01", "ntprobnp": 4000}, {"date": "2026-10-07", "ntprobnp": 7738}]
    r = rules.volemie(case(bio, [ahtn], [RX_K3], hypotensions_id="Oui"))
    assert "AVANT toute baisse du poids sec" in texts(r, rules.MODIF)


def test_albumine_35_alerte_meme_si_inflammation():
    r = rules.nutrition(case([{"date": "2026-09-01", "albumine": 41}, {"date": "2026-10-07", "albumine": 35, "crp": 37}]))
    assert "signal d'alerte" in texts(r, rules.ALERTE)


def test_pas_de_denutrition_sur_albumine_seule():
    bio = [{"date": "2026-09-01", "albumine": 33, "prealbumine": 0.31}, {"date": "2026-10-07", "albumine": 34, "prealbumine": 0.32}]
    rx = [{"date": "2026-07-01", "poids_sec": 95.5}, {"date": "2026-10-01", "poids_sec": 97}]
    r = rules.nutrition(case(bio, [], rx))
    assert rules.MODIF not in [f.level for f in r.findings]


def test_nutrition_basse_mais_en_amelioration_pas_d_escalade():
    bio = [{"date": d, "albumine": a, "prealbumine": p} for d, a, p in
           [("2026-05-06", 26, 0.11), ("2026-07-01", 29, 0.10), ("2026-09-02", 31, 0.13), ("2026-10-07", 33, 0.11), ("2026-11-04", 33, 0.13)]]
    r = rules.nutrition(case(bio))
    assert rules.MODIF not in [f.level for f in r.findings]
    assert "en amélioration" in texts(r, rules.OK)
    assert "signal d'alerte" in texts(r, rules.ALERTE)  # albumine ≤ 35 reste un signal


def test_pth_basse_sans_freinateur_os_adynamique_bain_ca():
    r = rules.phosphocalcique(case([{"date": "2026-10-07", "pth": 16.6, "ca": 2.2, "phos": 1.6, "pal_os": 25.9}], [],
                                   [{"date": "2026-10-01", "bain_ca": 1.5}]))
    t = texts(r, rules.ALERTE)
    assert "os adynamique" in t and "bain calcium à 1,25" in t and "discordance" in t
    assert "pmol" not in texts(r)


def test_pth_basse_sous_calcimimetique_reduire():
    cina = {"categorie": "Calcimimétique (agoniste CaSR)", "molecule": "Cinacalcet", "dose": 30, "unite": "mg", "frequence": "par jour", "statut": "En cours"}
    r = rules.phosphocalcique(case([{"date": "2026-10-07", "pth": 100, "ca": 2.2, "phos": 1.4, "pal_os": 12}], [cina]))
    assert "réduire Cinacalcet" in texts(r, rules.MODIF)


def test_recirculation_catheter_pas_d_alerte():
    r = rules.epuration(case([{"date": "2026-10-07", "ktv_daug": 1.71}], [], [], abord_type="Cathéter tunnelisé", recirculation=20))
    assert r.status in (rules.OK,)


def test_bilan_de_reference_ignore_bilans_posterieurs():
    c = case([{"date": "2026-10-07", "hb": 11.0}, {"date": "2026-10-13", "hb": 8.0}])
    c.ref_date = pd.Timestamp("2026-10-07")
    assert rules.last(c, "hb")[1] == 11.0
