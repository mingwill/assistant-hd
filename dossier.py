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
