"""Conversion dossier <-> tableaux et échange local entre l'application et le serveur MCP.

Les fichiers d'échange sont stockés dans %LOCALAPPDATA%\\AssistantHD (hors du dossier OneDrive,
pour ne pas synchroniser de données patient dans le cloud).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import schema

EXCHANGE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AssistantHD"
FICHIER_APP_VERS_CLAUDE = EXCHANGE_DIR / "dossier_en_cours.json"   # écrit par l'appli, lu par le MCP
FICHIER_CLAUDE_VERS_APP = EXCHANGE_DIR / "depuis_claude.json"      # écrit par le MCP, lu par l'appli


def to_dict(bio: pd.DataFrame, tx: pd.DataFrame, rx: pd.DataFrame, ctx: dict) -> dict:
    return {
        "version": 1,
        "biologie": schema.df_to_records(bio),
        "traitements": schema.df_to_records(tx),
        "prescription_hd": schema.df_to_records(rx),
        "contexte": {k: v for k, v in ctx.items() if v not in (None, "")},
    }


def from_dict(d: dict):
    """-> (bio, tx, rx, ctx) normalisés."""
    ctx = {**schema.CTX_DEFAULT, **{k: v for k, v in (d.get("contexte") or {}).items() if k in schema.CTX_DEFAULT and v is not None}}
    return (
        schema.normalize(pd.DataFrame(d.get("biologie") or []), schema.BIO_FIELDS),
        schema.normalize(pd.DataFrame(d.get("traitements") or []), schema.TX_FIELDS),
        schema.normalize(pd.DataFrame(d.get("prescription_hd") or []), schema.RX_FIELDS),
        ctx,
    )


def fusionner(bio: pd.DataFrame, tx: pd.DataFrame, rx: pd.DataFrame, ctx: dict, extraction) -> tuple:
    """Fusionne une extraction (modeles.Extraction) avec le dossier affiché -> (bio, tx, rx, ctx).

    Biologie et prescriptions : fusion par date (les nouvelles valeurs complètent / remplacent).
    Traitements : mise à jour par molécule, ajout sinon.
    """
    new_bio = schema.normalize(pd.DataFrame([b.model_dump() for b in extraction.bilans]), schema.BIO_FIELDS)
    merged = pd.concat([schema.normalize(bio, schema.BIO_FIELDS), new_bio], ignore_index=True)
    if len(merged):
        merged = merged.groupby("date", dropna=False, sort=True).last().reset_index()

    txm = schema.normalize(tx, schema.TX_FIELDS)
    new_tx = schema.normalize(pd.DataFrame([t.model_dump() for t in extraction.traitements]), schema.TX_FIELDS)
    for _, row in new_tx.iterrows():
        m = str(row["molecule"] or "").strip().lower()
        idx = txm.index[txm["molecule"].fillna("").astype(str).str.strip().str.lower() == m] if m else []
        if len(idx):
            for col in txm.columns:
                v = row[col]
                if v is not None and not pd.isna(v):
                    txm.at[idx[0], col] = v
        else:
            txm = pd.concat([txm, row.to_frame().T], ignore_index=True)

    new_rx = schema.normalize(pd.DataFrame([p.model_dump() for p in extraction.prescriptions]), schema.RX_FIELDS)
    rxm = pd.concat([schema.normalize(rx, schema.RX_FIELDS), new_rx], ignore_index=True)
    if len(rxm):
        rxm = rxm.groupby("date", dropna=False, sort=True).last().reset_index()

    newctx = dict(ctx)
    if extraction.poids_kg:
        newctx["poids_kg"] = extraction.poids_kg
    if extraction.recirculation_pct:
        newctx["recirculation"] = extraction.recirculation_pct
    if extraction.hypotensions_intradialytiques is not None:
        newctx["hypotensions_id"] = "Oui" if extraction.hypotensions_intradialytiques else "Non"
    for src, dst in (("pas_pre_moyenne", "pas_pre"), ("poids_fin_moyen", "poids_fin_moyen"),
                     ("ppid_moyenne", "ppid_moyenne"), ("ktv_ionique_moyen", "ktv_ionique_moyen")):
        v = getattr(extraction, src, None)
        if v:
            newctx[dst] = v
    return (schema.normalize(merged, schema.BIO_FIELDS), schema.normalize(txm, schema.TX_FIELDS),
            schema.normalize(rxm, schema.RX_FIELDS), newctx)


def ecrire(path: Path, data: dict, source: str) -> None:
    EXCHANGE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {**data, "_source": source, "_horodatage": datetime.now().isoformat(timespec="seconds")}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def lire(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
