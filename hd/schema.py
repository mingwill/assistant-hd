"""Structure des données saisies : biologie datée, traitements, prescription HD, contexte."""
from __future__ import annotations

import pandas as pd

# --- Biologie : une ligne par bilan daté (valeurs prédialyse sauf mention) ---
# (clé, libellé, unité, type)  type: date | num | text
BIO_FIELDS = [
    ("date", "Date", "", "date"),
    ("hb", "Hb début", "g/dL", "num"),
    ("hb_post", "Hb fin", "g/dL", "num"),
    ("ferritine", "Ferritine", "µg/L", "num"),
    ("cst", "CST", "%", "num"),
    ("crp", "CRP", "mg/L", "num"),
    ("na", "Na début", "mmol/L", "num"),
    ("k_pre", "K début", "mmol/L", "num"),
    ("k_post", "K fin", "mmol/L", "num"),
    ("bicar", "BBNa (HCO3 début)", "mmol/L", "num"),
    ("ca", "Calcium", "mmol/L", "num"),
    ("phos", "Phosphate", "mmol/L", "num"),
    ("pth", "PTH", "pg/mL", "num"),
    ("pal_os", "PAL osseuses", "µg/L", "num"),
    ("albumine", "Albumine", "g/L", "num"),
    ("prealbumine", "Préalbumine", "g/L", "num"),
    ("npcr", "nPCR", "g/kg/j", "num"),
    ("ntprobnp", "NT-proBNP", "pg/mL", "num"),
    ("ktv_daug", "Kt/V Daugirdas", "", "num"),
    ("ktv_ionique", "Kt/V ionique", "", "num"),
    ("uree_pre", "Urée début", "mmol/L", "num"),
    ("uree_post", "Urée fin", "mmol/L", "num"),
    ("commentaire", "Commentaire", "", "text"),
]

# --- Traitements ---
TX_CATEGORIES = [
    "ASE",
    "HIF-PHI",
    "Fer IV",
    "Calcium",
    "Vitamine D native",
    "Vitamine D active",
    "Calcimimétique (agoniste CaSR)",
    "Chélateur du phosphore",
    "Chélateur du potassium",
    "Antihypertenseur",
    "Diurétique",
    "Nutrition parentérale",
    "Compléments nutritionnels oraux",
    "Autre",
]

TX_STATUTS = ["En cours", "Suspendu", "Arrêté"]

# Nombre d'administrations par 4 semaines (utilisé pour le calcul des doses d'ASE)
FREQUENCES = {
    "par séance (3/sem)": 12,
    "par semaine": 4,
    "toutes les 2 semaines": 2,
    "toutes les 4 semaines / mensuel": 1,
    "par jour": 28,
    "2 fois/jour": 56,
    "3 fois/jour": 84,
    "3 fois/semaine": 12,
    "autre / à préciser": None,
}

TX_FIELDS = [
    ("categorie", "Catégorie", "", "select"),
    ("molecule", "Molécule", "", "text"),
    ("dose", "Dose", "", "num"),
    ("unite", "Unité", "", "text"),
    ("frequence", "Fréquence", "", "select"),
    ("statut", "Statut", "", "select"),
    ("date_modif", "Dernière modif.", "", "date"),
    ("dose_precedente", "Dose précédente", "", "num"),
    ("motif", "Motif / commentaire", "", "text"),
]

# --- Prescription d'hémodialyse : une ligne par prescription datée ---
RX_FIELDS = [
    ("date", "Date", "", "date"),
    ("bain_k", "Bain K", "mmol/L", "num"),
    ("bain_ca", "Bain Ca", "mmol/L", "num"),
    ("nad", "NaD", "mmol/L", "num"),
    ("bain_hco3", "Bicarbonate bain", "mmol/L", "num"),
    ("poids_sec", "Poids sec", "kg", "num"),
    ("technique", "Technique", "", "select"),
    ("duree_h", "Durée", "h", "num"),
    ("seances_sem", "Séances/sem", "", "num"),
    ("qb", "Qb", "mL/min", "num"),
    ("qd", "Qd", "mL/min", "num"),
    ("abord", "Abord vasculaire", "", "text"),
]

TECHNIQUES = ["HD", "HDF"]
BAINS_K = [2.0, 3.0]  # seuls bains disponibles dans l'unité

OUI_NON = ["Non renseigné", "Non", "Oui"]

CTX_DEFAULT = {
    "poids_kg": None,
    "abord_type": "Non renseigné",
    "thrombose": "Non renseigné",
    "thrombose_fav": False,
    "cancer_actif": "Non renseigné",
    "evt_cv_recent": "Non renseigné",
    "saignement": "Non renseigné",
    "infection_active": "Non renseigné",
    "hospitalisation_recente": "Non renseigné",
    "hypotensions_id": "Non renseigné",
    "pas_pre": None,
    "fevg": None,
    "observance_chelateurs": "Non vérifiée",
    "symptomes_anemie": "Non renseigné",
    "diurese_residuelle": "Non renseigné",
    "recirculation": None,
    "notes": "",
}

ABORDS = ["Non renseigné", "FAV", "Pontage prothétique", "Cathéter tunnelisé", "Cathéter non tunnelisé"]
OBSERVANCE = ["Non vérifiée", "Bonne", "Mauvaise / partielle"]


def _empty(fields) -> pd.DataFrame:
    data = {}
    for key, _label, _unit, typ in fields:
        if typ == "date":
            data[key] = pd.Series(dtype="datetime64[ns]")
        elif typ == "num":
            data[key] = pd.Series(dtype="float64")
        else:
            data[key] = pd.Series(dtype="object")
    return pd.DataFrame(data)


def empty_bio() -> pd.DataFrame:
    return _empty(BIO_FIELDS)


def empty_tx() -> pd.DataFrame:
    return _empty(TX_FIELDS)


def empty_rx() -> pd.DataFrame:
    return _empty(RX_FIELDS)


def normalize(df: pd.DataFrame, fields) -> pd.DataFrame:
    """Force les colonnes et les types attendus (après import JSON / IA / édition)."""
    out = pd.DataFrame(index=range(len(df)))
    df = df.reset_index(drop=True)
    for key, _label, _unit, typ in fields:
        col = df[key] if key in df.columns else pd.Series([None] * len(df))
        if typ == "date":
            out[key] = pd.to_datetime(col, errors="coerce", dayfirst=False)
        elif typ == "num":
            out[key] = pd.to_numeric(
                col.astype("object").map(lambda v: str(v).replace(",", ".") if isinstance(v, str) else v),
                errors="coerce",
            ).astype("float64")
        else:
            out[key] = col.astype("object").where(col.notna(), None)
    return out


def df_to_records(df: pd.DataFrame) -> list[dict]:
    recs = []
    for row in df.to_dict(orient="records"):
        clean = {}
        for k, v in row.items():
            if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
                continue
            if isinstance(v, pd.Timestamp):
                if pd.isna(v):
                    continue
                v = v.strftime("%Y-%m-%d")
            clean[k] = v
        if clean:
            recs.append(clean)
    return recs
