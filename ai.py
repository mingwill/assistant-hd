"""Appels à Claude : extraction des captures d'écran, synthèse BM, discussion."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import anthropic

from .modeles import Extraction

MODEL = "claude-opus-5-5"
BETAS = ["server-side-fallback-2026-07-01"]
PROTOCOLE = (Path(__file__).parent / "protocole.md").read_text(encoding="utf-8")


class AIError(RuntimeError):
    pass


def make_client(api_key: str | None) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()


# ------------------------------------------------------------------ extraction
EXTRACT_INSTRUCTIONS = """Tu extrais des données de captures d'écran de dossiers d'hémodialyse (bilans biologiques, ordonnances, feuilles de prescription et de séances) pour préremplir un formulaire.

Règles :
- Les colonnes DÉBUT et FIN d'une même date sont la même séance : mets la valeur DÉBUT dans le champ principal et la valeur FIN dans le champ *_post / *_fin. Ne crée pas deux bilans.
- Une ligne de bilan par date de prélèvement. Conserve les valeurs antérieures (historique) avec leurs dates : elles servent à la cinétique.
- Ordonnance : jaune = ambulatoire, vert = en dialyse, rouge = SUSPENDU (statut « Suspendu »).
- N'invente rien : si une valeur est illisible ou ambiguë, laisse le champ vide et décris-la dans « incertitudes ». Signale notamment les fréquences d'administration incertaines (ex. Mircera « chaque 2e mercredi du mois » = mensuel).
- Ne reporte AUCUNE donnée identifiante (nom, prénom, date de naissance, IPP) : ignore-les.
- Unités : Hb g/dL, PTH pg/mL, ferritine µg/L, CST %, albumine g/L, préalbumine g/L, électrolytes mmol/L.
- Dates au format AAAA-MM-JJ ; si l'année manque, déduis-la du contexte et signale-le.
"""


def _image_block(name: str, data: bytes) -> dict:
    ext = name.lower().rsplit(".", 1)[-1]
    b64 = base64.standard_b64encode(data).decode("utf-8")
    if ext == "pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    media = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}}


def _check(resp) -> None:
    if resp.stop_reason == "refusal":
        raise AIError("La requête a été refusée par le modèle.")
    if resp.stop_reason == "max_tokens":
        raise AIError("Réponse tronquée (limite de longueur atteinte) : réessayer avec moins de captures à la fois.")


def _api_error_msg(e: anthropic.APIError) -> str:
    if isinstance(e, anthropic.AuthenticationError):
        return "Clé API Anthropic invalide (ANTHROPIC_API_KEY)."
    if isinstance(e, anthropic.RateLimitError):
        return "Limite de débit de l'API atteinte : réessayer dans une minute."
    if isinstance(e, anthropic.APIConnectionError):
        return "Connexion à l'API impossible : vérifier l'accès internet."
    if isinstance(e, anthropic.APIStatusError):
        return f"Erreur API ({e.status_code}) : {e.message}"
    return f"Erreur API : {e}"


def extract(client: anthropic.Anthropic, files: list[tuple[str, bytes]], note: str = "") -> Extraction:
    content = [_image_block(n, d) for n, d in files]
    content.append({"type": "text", "text": "Extrais les données de ces documents." + (f"\nPrécision du médecin : {note}" if note else "")})
    try:
        resp = client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            betas=BETAS,
            fallbacks="default",
            system=EXTRACT_INSTRUCTIONS,
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": content}],
            output_format=Extraction,
        )
    except anthropic.APIError as e:
        raise AIError(_api_error_msg(e)) from e
    _check(resp)
    if resp.parsed_output is None:
        raise AIError("Extraction impossible : réponse non structurée.")
    return resp.parsed_output


# ------------------------------------------------------------------ synthèse
SYSTEM_SYNTHESE = f"""Tu es l'Assistant HD du service de dialyse des HUS (Strasbourg). Tu aides un néphrologue à interpréter le bilan mensuel (BM) d'un patient hémodialysé chronique et à proposer des adaptations thérapeutiques concrètes. Tu appliques strictement le protocole du service ci-dessous. Tu ne prends aucune décision : tes propositions sont soumises à la validation du néphrologue.

Tu reçois : les données saisies (biologie datée, traitements avec statut et historique, prescription d'hémodialyse, contexte clinique) et l'analyse préalable d'un moteur de règles déterministe. Vérifie cette analyse contre les données, corrige-la si besoin, et rédige la synthèse BM au format du service. Ne réinvente pas de valeurs absentes : dis ce qui manque. Réponds en français.

<protocole>
{PROTOCOLE}
</protocole>"""


def _text(resp) -> str:
    return "\n".join(b.text for b in resp.content if b.type == "text").strip()


def case_message(case_json: dict, engine_md: str) -> str:
    return (
        "Données du patient (JSON) :\n```json\n" + json.dumps(case_json, ensure_ascii=False, indent=1) + "\n```\n\n"
        "Analyse du moteur de règles :\n" + engine_md + "\n\n"
        "Rédige la synthèse BM complète avec propositions thérapeutiques pour chaque rubrique, puis « Modifications proposées » et « À préciser »."
    )


def chat(client: anthropic.Anthropic, messages: list[dict]) -> str:
    """messages : historique [{'role': 'user'|'assistant', 'content': str}], dernier message = user."""
    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=BETAS,
            fallbacks="default",
            system=[{"type": "text", "text": SYSTEM_SYNTHESE, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": "high"},
            messages=messages,
        )
    except anthropic.APIError as e:
        raise AIError(_api_error_msg(e)) from e
    _check(resp)
    return _text(resp)
