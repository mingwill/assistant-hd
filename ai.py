"""Appels à Claude : extraction des captures d'écran, synthèse BM, discussion."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from typing import Optional

import anthropic
from pydantic import ValidationError

from .modeles import Bilan, Extraction, Prescription, Traitement

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

Format du tableau de biologie du service (le plus fréquent) :
- Les DATES sont en COLONNES (la plus récente à gauche, format JJ/MM/AA, année dans l'en-tête), les EXAMENS en LIGNES.
- Une ligne « … après » / « … apr » / « … ap. » est la valeur de FIN de dialyse de l'examen au-dessus (ex. « Urée après » → uree_post, « K après » → k_post). Les autres lignes sont les valeurs de DÉBUT.
- Correspondances : Urée → uree_pre ; Na → na ; K → k_pre ; Calcémie → ca ; Phosphatémie → phos ; Parathormone → pth ; Albumine sérique → albumine ; Préalbumine → prealbumine ; Phosphatases alc. osseuses → pal_os ; Hémoglobine → hb ; Coeff. de saturation → cst ; Ferritine → ferritine ; CRP → crp ; NT-pro BNP → ntprobnp ; Réserve alcaline → bicar (BBNa). Ignore les autres lignes (créatinine, VGM, plaquettes, vitamines…).
- « Coeff. de saturation » est souvent une FRACTION (0.38) : convertis en pourcentage (38).
- « Parathormone 2 » est en pg/mL (unité confirmée par le service) : reporter la valeur telle quelle.
- Une colonne ne contenant que quelques valeurs (ex. seulement K ou Hb) est un bilan intermédiaire : mets commentaire = « bilan intermédiaire ». Une colonne complète = « bilan mensuel ».
- Si deux colonnes ont la même date, fusionne-les en une seule ligne en gardant les valeurs de la colonne la plus complète, et signale les valeurs divergentes dans « incertitudes ».
- Lis chaque valeur dans la bonne colonne : vérifie l'alignement vertical avec la date en en-tête.
- Page « suite » : « KT/V Daugirdas » → ktv_daug (ignorer « KT/V eq. Daugirdas ») ; « nPCR » → npcr.

Documents MedWare du service (pages d'images ; l'en-tête patient est masqué par une bande noire, ou à IGNORER s'il est visible) :
- La bande noire peut aussi cacher le titre et sa date (ex. date de la prescription, mois de la synthèse) : laisse alors la date vide
  ou déduis le mois des dates du tableau, et signale-le dans « incertitudes ».
1. « Examens biologiques – Bilan mensuel » : tableau décrit ci-dessus, sur une ou plusieurs pages.
2. « Prescription Dialyse du : JJ/MM/AAAA » → une prescription datée de ce jour :
   - poids_sec = « Poids sec » ; technique = HDF si « Hémodiafiltration », sinon HD ;
     duree_h et seances_sem depuis « Temps dialyse : 3 x 4:00 » (→ 3 séances, 4 h) ;
   - bain_k = « K : » (ou « Bain à 3 K+ ») ; bain_ca = « Ca : » ;
     nad = « Conc. Na » (ATTENTION : le « Na : 100.30 » de la ligne Dialysat est un code de bain, PAS le NaD) ;
     bain_hco3 = « Conc. HCO3 » ; qb = « Débit sang » ; qd = « Débit » de la rubrique dialysat ;
     abord = texte après « AV : » (ex. « FAV - Radio-céphalique D ») ;
   - « Traitement ID » = traitements administrés en dialyse (à ajouter aux traitements, date = « A partir du »).
3. « Synthèse des séances de dialyse – MOIS » : utiliser la ligne « moy. » et la colonne incidents :
   pas_pre_moyenne = PAS de « Pression art. début » moyenne ; poids_fin_moyen = « Poids fin » moyen ;
   ppid_moyenne = « Prise poids » moyenne ; ktv_ionique_moyen = « KT/V fin » moyen ;
   hypotensions_intradialytiques = vrai si incidents « Chute TA » ou PAS de fin < 90 mmHg à plusieurs séances.
4. « Traitement ambulatoire / Traitement intradialytique » (récapitulatif médicaments) :
   une ligne par médicament ; date_modif = « Début prescr. » ; statut « En cours » sauf mention d'arrêt/suspension ;
   convertir les flacons en dose (ex. VENOFER 20 mg/ml, flacon 5 ml → dose 100 mg) ;
   « /quinz. » → toutes les 2 semaines ; « chaque /séance » → par séance (3/sem) ; « /3 mois » → autre / à préciser (préciser dans motif) ;
   catégories : Roxadustat → HIF-PHI ; Mircera/Aranesp → ASE ; Venofer → Fer IV ; Lokelma/Veltassa/Résikali/Kayexalate → Chélateur du potassium ;
   Uvedose/Zymad (cholécalciférol) → Vitamine D native ; Rocaltrol/Un-Alfa → Vitamine D active ; Mimpara/cinacalcet, Parsabiv → Calcimimétique ;
   Renvela/Velphoro/Phosphosorb/carbonate de calcium chélateur → Chélateur du phosphore ; Delical/Fortimel/Renutryl → Compléments nutritionnels oraux ;
   Olimel/Clinimix perdialytique → Nutrition parentérale ; IEC/ARA2/bêtabloquants/inhibiteurs calciques/alpha-bloquants → Antihypertenseur ;
   furosémide (Lasilix) → Diurétique ; le reste (Lovenox, paracétamol, IPP, Emla…) → Autre.
"""


MAX_IMAGE_BYTES = 4_500_000  # l'API refuse les images > 5 Mo (base64 compris : marge)


def _reduire_image(data: bytes) -> tuple[bytes, str]:
    """Recompresse une capture trop lourde en JPEG (et la réduit si besoin) pour respecter la limite de l'API."""
    from PIL import Image  # fourni avec Streamlit

    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    for max_side in (None, 3000, 2400, 2000, 1600):
        im = img
        if max_side and max(img.size) > max_side:
            im = img.copy()
            im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88)
        if buf.tell() * 4 / 3 < MAX_IMAGE_BYTES:
            return buf.getvalue(), "image/jpeg"
    return buf.getvalue(), "image/jpeg"


def _image_block(name: str, data: bytes) -> dict:
    ext = name.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        b64 = base64.standard_b64encode(data).decode("utf-8")
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    media = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
    if len(data) * 4 / 3 >= MAX_IMAGE_BYTES:
        data, media = _reduire_image(data)
    b64 = base64.standard_b64encode(data).decode("utf-8")
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


def _schema_compact() -> str:
    """Description compacte des champs attendus (le schéma strict complet dépasse la limite de grammaire de l'API)."""
    lignes = []
    for nom, modele in (("bilans[]", Bilan), ("traitements[]", Traitement), ("prescriptions[]", Prescription)):
        champs = []
        for k, f in modele.model_fields.items():
            ann = f.annotation
            typ = "nombre" if ann in (float, Optional[float]) else "texte"
            champs.append(f"{k} ({typ}{' – ' + f.description if f.description else ''})")
        lignes.append(f"- {nom} : " + " ; ".join(champs))
    for k, f in Extraction.model_fields.items():
        if k not in ("bilans", "traitements", "prescriptions"):
            lignes.append(f"- {k}{' : ' + f.description if f.description else ''}")
    return "\n".join(lignes)


FORMAT_REPONSE = """
Format de réponse : UNIQUEMENT un objet JSON valide, sans texte avant ou après, de la forme
{"bilans": [...], "traitements": [...], "prescriptions": [...], "poids_kg": null, "recirculation_pct": null,
 "hypotensions_intradialytiques": null, "pas_pre_moyenne": null, "poids_fin_moyen": null, "ppid_moyenne": null,
 "ktv_ionique_moyen": null, "incertitudes": ["..."]}
Omets les champs sans valeur (ou mets null). Nombres avec un point décimal (12.3), dates AAAA-MM-JJ.
Champs disponibles :
"""


def parse_extraction(text: str) -> Extraction:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    debut, fin = t.find("{"), t.rfind("}")
    if debut < 0 or fin <= debut:
        raise AIError("Extraction impossible : la réponse ne contient pas de données structurées.")
    try:
        return Extraction.model_validate_json(t[debut:fin + 1])
    except ValidationError as e:
        raise AIError(f"Extraction mal formée ({e.error_count()} erreur(s)) : réessayer, éventuellement avec moins de documents à la fois.") from e


def extract(client: anthropic.Anthropic, files: list[tuple[str, bytes]], note: str = "") -> Extraction:
    content = [_image_block(n, d) for n, d in files]
    content.append({"type": "text", "text": "Extrais les données de ces documents." + (f"\nPrécision du médecin : {note}" if note else "")})
    try:
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=32000,
            betas=BETAS,
            fallbacks="default",
            system=EXTRACT_INSTRUCTIONS + FORMAT_REPONSE + _schema_compact(),
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": content}],
        ) as stream:
            resp = stream.get_final_message()
    except anthropic.APIError as e:
        raise AIError(_api_error_msg(e)) from e
    _check(resp)
    return parse_extraction(_text(resp))


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
