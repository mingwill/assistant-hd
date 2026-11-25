"""Assistant bilans mensuels hémodialyse – HUS Strasbourg (pilote).

Lancer :  py -3.15 -m streamlit run app.py
"""
from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from hd import ai, dossier, exemple, masquage, rules, schema

st.set_page_config(page_title="Assistant HD – HUS", page_icon="🩺", layout="wide")


# ------------------------------------------------------------------ config
def secret(name: str):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


APP_PASSWORD = secret("APP_PASSWORD")
API_KEY = secret("ANTHROPIC_API_KEY")
# En ligne (serveur Linux, ex. Streamlit Community Cloud) : mot de passe obligatoire, pas de MCP local
EN_LIGNE = os.name != "nt"

# ------------------------------------------------------------------ accès
if EN_LIGNE and not APP_PASSWORD:
    st.title("🩺 Assistant HD – HUS Strasbourg")
    st.error("Application en ligne sans mot de passe : définir APP_PASSWORD dans les secrets du serveur.")
    st.stop()
if APP_PASSWORD and not st.session_state.get("auth"):
    st.title("🩺 Assistant HD – HUS Strasbourg")
    pwd = st.text_input("Mot de passe du pilote", type="password")
    if pwd:
        if hmac.compare_digest(pwd, str(APP_PASSWORD)):
            st.session_state.auth = True
            st.rerun()
        st.error("Mot de passe incorrect.")
    st.stop()

# ------------------------------------------------------------------ état
CTX_KEYS = list(schema.CTX_DEFAULT)


def _apply_case(bio, tx, rx, ctx):
    st.session_state.bio_base = schema.normalize(bio, schema.BIO_FIELDS)
    st.session_state.tx_base = schema.normalize(tx, schema.TX_FIELDS)
    st.session_state.rx_base = schema.normalize(rx, schema.RX_FIELDS)
    for k in CTX_KEYS:
        st.session_state[f"ctx_{k}"] = ctx.get(k, schema.CTX_DEFAULT[k])
    st.session_state.ver = st.session_state.get("ver", 0) + 1
    st.session_state.chat = []


def set_case(bio, tx, rx, ctx):
    """Programme le chargement d'un dossier ; appliqué au début de la prochaine exécution (avant les widgets)."""
    st.session_state.pending_case = (bio, tx, rx, ctx)
    st.session_state.incertitudes = []


if "bio_base" not in st.session_state:
    _apply_case(schema.empty_bio(), schema.empty_tx(), schema.empty_rx(), schema.CTX_DEFAULT)
if st.session_state.get("pending_case") is not None:
    _apply_case(*st.session_state.pending_case)
    st.session_state.pending_case = None

ver = st.session_state.ver


def current_ctx() -> dict:
    return {k: st.session_state.get(f"ctx_{k}", schema.CTX_DEFAULT[k]) for k in CTX_KEYS}


def lab(fields, key):
    for k, label, unit, _ in fields:
        if k == key:
            return f"{label} ({unit})" if unit else label
    return key


def num_cfg(fields):
    cfg = {}
    for k, label, unit, typ in fields:
        title = f"{label} ({unit})" if unit else label
        if typ == "date":
            cfg[k] = st.column_config.DateColumn(title, format="DD/MM/YYYY")
        elif typ == "num":
            cfg[k] = st.column_config.NumberColumn(title, format="%g")
        else:
            cfg[k] = st.column_config.TextColumn(title)
    return cfg


@st.cache_data(show_spinner="Préparation des pages…", max_entries=20)
def preparer_pages(fichiers: tuple, masquer_pdf: bool) -> list:
    return masquage.preparer(list(fichiers), masquer_pdf)


def zip_pages(pages: list) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, data, _ in pages:
            z.writestr(nom, data)
    return buf.getvalue()


# ------------------------------------------------------------------ en-tête
st.title("🩺 Assistant bilans mensuels hémodialyse")
st.caption("HUS Strasbourg – pilote. Données fictives ou réellement anonymisées uniquement. "
           "Les propositions sont une aide à la décision, soumises à la validation du néphrologue.")

tabs = st.tabs(["📷 Import captures", "🧪 Biologie", "💊 Traitements", "🩸 Prescription HD",
                "🧾 Contexte clinique", "📋 Synthèse BM", "📖 Protocole"])

# ------------------------------------------------------------------ biologie
with tabs[1]:
    st.subheader("Biologie – bilans datés")
    st.caption("Une ligne par date de prélèvement. Valeurs de DÉBUT de dialyse, sauf colonnes « fin ». "
               "Saisir plusieurs dates pour l'analyse des cinétiques. NT-proBNP et Kt/V sont ici.")
    bio = st.data_editor(st.session_state.bio_base, key=f"bio_{ver}", num_rows="dynamic", hide_index=True,
                         column_config=num_cfg(schema.BIO_FIELDS), width="stretch")
    bio = schema.normalize(bio, schema.BIO_FIELDS)
    plot_cols = [k for k, _l, _u, t in schema.BIO_FIELDS if t == "num" and bio[k].notna().sum() >= 2]
    if plot_cols:
        st.markdown("**Cinétique**")
        choix = st.multiselect("Paramètres", plot_cols, default=plot_cols[:1],
                               format_func=lambda k: lab(schema.BIO_FIELDS, k))
        for k in choix:
            d = bio.dropna(subset=["date", k]).sort_values("date").set_index("date")[[k]]
            d.columns = [lab(schema.BIO_FIELDS, k)]
            st.line_chart(d, height=200)

# ------------------------------------------------------------------ traitements
with tabs[2]:
    st.subheader("Traitements en cours")
    st.caption("Une ligne par médicament. Statut : en cours / suspendu / arrêté. Renseigner la date et la dose précédente "
               "en cas de modification récente : l'assistant ne reproposera pas une adaptation déjà faite.")
    tx_cfg = num_cfg(schema.TX_FIELDS)
    tx_cfg["categorie"] = st.column_config.SelectboxColumn("Catégorie", options=schema.TX_CATEGORIES, required=True)
    tx_cfg["frequence"] = st.column_config.SelectboxColumn("Fréquence", options=list(schema.FREQUENCES))
    tx_cfg["statut"] = st.column_config.SelectboxColumn("Statut", options=schema.TX_STATUTS, default="En cours")
    tx = st.data_editor(st.session_state.tx_base, key=f"tx_{ver}", num_rows="dynamic", hide_index=True,
                        column_config=tx_cfg, width="stretch")
    tx = schema.normalize(tx, schema.TX_FIELDS)
    with st.expander("Aide – catégories"):
        st.markdown(
            "- **ASE** : Mircera, Aranesp · **HIF-PHI** : roxadustat · **Fer IV** : Venofer…\n"
            "- **Vitamine D native** : cholécalciférol (Zymad) · **Vitamine D active** : calcitriol (Rocaltrol), alfacalcidol\n"
            "- **Calcimimétique** : cinacalcet (per os, mg/j), ételcalcétide / Parsabiv (IV, mg/séance)\n"
            "- **Chélateur du phosphore** : Velphoro, Renvela… · **Chélateur du potassium** : Lokelma, Veltassa, Resikali, Kayexalate\n"
            "- La dose d'ASE est convertie en µg/kg/4 semaines grâce à la fréquence (ex. Mircera mensuel = « toutes les 4 semaines / mensuel »).")

# ------------------------------------------------------------------ prescription HD
with tabs[3]:
    st.subheader("Prescription d'hémodialyse")
    st.caption("Une ligne par prescription datée (historique des modifications de poids sec, bains…). La dernière ligne = prescription actuelle. "
               "Bains potassium disponibles : K2 et K3.")
    rx_cfg = num_cfg(schema.RX_FIELDS)
    rx_cfg["technique"] = st.column_config.SelectboxColumn("Technique", options=schema.TECHNIQUES)
    rx_cfg["bain_k"] = st.column_config.SelectboxColumn("Bain K (mmol/L)", options=schema.BAINS_K)
    rx = st.data_editor(st.session_state.rx_base, key=f"rx_{ver}", num_rows="dynamic", hide_index=True,
                        column_config=rx_cfg, width="stretch")
    rx = schema.normalize(rx, schema.RX_FIELDS)
    if len(rx):
        cur = rx.sort_values("date").iloc[-1]
        f = rules.fmt
        st.info(f"**Récapitulatif** — Bain K {f(cur['bain_k'])} / Ca {f(cur['bain_ca'])} / NaD {f(cur['nad'])} / HCO3 {f(cur['bain_hco3'])} mmol/L · "
                f"PS {f(cur['poids_sec'], 1)} kg · {cur['technique'] or '?'} {f(cur['duree_h'], 1)} h × {f(cur['seances_sem'], 0)}/sem · "
                f"Qb {f(cur['qb'], 0)} · Qd {f(cur['qd'], 0)} · {cur['abord'] or 'abord ?'}")

# ------------------------------------------------------------------ contexte
with tabs[4]:
    st.subheader("Contexte clinique")
    st.caption("Informations nécessaires à certaines règles (antécédents thrombotiques avant majoration d'ASE, tolérance des séances "
               "avant modification du poids sec, observance des chélateurs avant majoration…).")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.number_input("Poids pour le calcul des doses (kg)", min_value=0.0, step=0.5, key="ctx_poids_kg",
                        help="Vide = poids sec de la prescription actuelle")
        st.selectbox("Type d'abord vasculaire", schema.ABORDS, key="ctx_abord_type")
        st.number_input("Recirculation (%) – Fresenius 6008", min_value=0.0, step=1.0, key="ctx_recirculation")
        st.selectbox("Diurèse résiduelle", schema.OUI_NON, key="ctx_diurese_residuelle")
        st.number_input("Poids de fin de séance moyen (kg)", min_value=0.0, step=0.1, key="ctx_poids_fin_moyen")
        st.number_input("Prise de poids interdialytique moyenne (kg)", min_value=0.0, step=0.1, key="ctx_ppid_moyenne")
        st.number_input("Kt/V ionique moyen du mois", min_value=0.0, step=0.05, key="ctx_ktv_ionique_moyen")
    with c2:
        st.selectbox("Antécédents thrombotiques", schema.OUI_NON, key="ctx_thrombose")
        st.checkbox("dont thrombose de FAV", key="ctx_thrombose_fav")
        st.selectbox("Cancer actif", schema.OUI_NON, key="ctx_cancer_actif")
        st.selectbox("Événement cardiovasculaire récent", schema.OUI_NON, key="ctx_evt_cv_recent")
        st.selectbox("Saignement récent", schema.OUI_NON, key="ctx_saignement")
        st.selectbox("Infection active", schema.OUI_NON, key="ctx_infection_active")
    with c3:
        st.selectbox("Hypotensions intradialytiques", schema.OUI_NON, key="ctx_hypotensions_id")
        st.number_input("PAS prédialyse habituelle (mmHg)", min_value=0.0, step=5.0, key="ctx_pas_pre")
        st.number_input("FEVG (%)", min_value=0.0, max_value=90.0, step=5.0, key="ctx_fevg")
        st.selectbox("Observance des chélateurs (phosphore)", schema.OBSERVANCE, key="ctx_observance_chelateurs")
        st.selectbox("Symptômes d'anémie / besoin transfusionnel", schema.OUI_NON, key="ctx_symptomes_anemie")
        st.selectbox("Hospitalisation récente", schema.OUI_NON, key="ctx_hospitalisation_recente")
    st.text_area("Notes / précisions pour l'assistant", key="ctx_notes",
                 placeholder="ex. Mircera réduit de 150 à 75 µg en septembre devant une Hb trop haute…")

ctx = current_ctx()
for k in ("poids_kg", "pas_pre", "fevg", "recirculation", "poids_fin_moyen", "ppid_moyenne", "ktv_ionique_moyen"):
    if not ctx.get(k):
        ctx[k] = None

# ------------------------------------------------------------------ import captures
with tabs[0]:
    st.subheader("Importer des documents")
    st.caption("PDF MedWare (bilan mensuel, prescription de dialyse, synthèse des séances, traitements) ou captures d'écran. "
               "L'IA préremplit les onglets ; **vérifiez chaque valeur** avant la synthèse.")
    files = st.file_uploader("Documents PDF ou captures (PNG, JPG)", type=["png", "jpg", "jpeg", "webp", "pdf"],
                             accept_multiple_files=True, key=f"up_{ver}")
    masquer_pdf = st.checkbox("Masquer l'en-tête patient des PDF MedWare (nom, naissance, adresse, téléphone, IPP)", value=True)
    pages, verifie = [], False
    if files:
        try:
            pages = preparer_pages(tuple((f.name, f.getvalue()) for f in files), masquer_pdf)
        except Exception as e:
            st.error(f"Lecture des fichiers impossible ({type(e).__name__}) : {e}")
        if pages:
            with st.expander(f"👁️ Aperçu de ce qui sera envoyé à l'IA ({len(pages)} page(s)) – à vérifier", expanded=True):
                cols = st.columns(3)
                for i, (nom, img, masque) in enumerate(pages):
                    cols[i % 3].image(img, caption=nom + (" – en-tête masqué" if masque else " – NON masqué"), width="stretch")
            if any(not m for _, _, m in pages):
                st.warning("Les captures d'écran (et les PDF si le masquage est décoché) ne sont pas masquées : "
                           "vérifiez qu'aucun nom, date de naissance ou IPP n'est visible.")
            verifie = st.checkbox("J'ai vérifié l'aperçu : aucune donnée identifiante n'est visible")
            st.download_button("⬇️ Télécharger les pages masquées (pour Claude Desktop)", zip_pages(pages),
                               file_name="pages_masquees.zip", mime="application/zip")
    note = st.text_input("Précision éventuelle (ex. « prendre en compte le bilan du 07/10 »)")
    if not API_KEY:
        st.warning("Clé ANTHROPIC_API_KEY non configurée : l'import automatique est indisponible (saisie manuelle possible).")
    if st.button("Extraire et préremplir les cases", type="primary", disabled=not (pages and verifie and API_KEY)):
        with st.spinner("Lecture des documents…"):
            try:
                ex = ai.extract(ai.make_client(API_KEY), [(n, d) for n, d, _ in pages], note)
            except ai.AIError as e:
                st.error(str(e))
            except Exception as e:  # toute autre erreur : afficher en clair (Streamlit Cloud masque les tracebacks)
                st.error(f"Erreur inattendue pendant l'extraction ({type(e).__name__}) : {e}")
            else:
                if not (ex.bilans or ex.traitements or ex.prescriptions):
                    st.warning("Aucune donnée reconnue sur ces captures."
                               + (" Remarques : " + " ; ".join(ex.incertitudes) if ex.incertitudes else ""))
                else:
                    set_case(*dossier.fusionner(bio, tx, rx, ctx, ex))
                    st.session_state.incertitudes = ex.incertitudes
                    st.session_state.import_msg = (f"{len(ex.bilans)} bilan(s), {len(ex.traitements)} traitement(s), "
                                                   f"{len(ex.prescriptions)} prescription(s) extraits.")
                    st.rerun()
    if st.session_state.get("import_msg"):
        st.success(st.session_state.import_msg + " Vérifiez les onglets Biologie, Traitements et Prescription HD.")
    if st.session_state.get("incertitudes"):
        st.warning("**À vérifier :**\n" + "\n".join(f"- {i}" for i in st.session_state.incertitudes))

# ------------------------------------------------------------------ synthèse
with tabs[5]:
    st.subheader("Synthèse BM")
    dates = sorted(bio["date"].dropna().unique(), reverse=True)
    if not dates:
        st.info("Saisissez au moins un bilan daté (onglet Biologie), importez des captures, ou chargez le cas fictif (barre latérale).")
    else:
        ref = st.selectbox("Bilan de référence", dates, format_func=lambda d: pd.Timestamp(d).strftime("%d/%m/%Y"),
                           help="Les bilans postérieurs sont ignorés.", key=f"ref_{ver}")
        ref = pd.Timestamp(ref)
        case = rules.Case(bio, tx, rx, ctx, ref_date=ref)
        results = rules.analyse(case)
        draft = rules.bm_draft(results, ref)

        icons = {rules.OK: "🟢", rules.MODIF: "🟠", rules.MANQUE: "🔵", rules.ALERTE: "🔴"}
        st.markdown("🟢 aucune modification · 🟠 modification proposée · 🔵 information manquante · 🔴 alerte")
        cols = st.columns(2)
        for i, res in enumerate(results):
            with cols[i % 2].container(border=True):
                st.markdown(f"**{icons[res.status]} {res.title}**")
                if res.summary:
                    st.caption(res.summary)
                for fnd in res.findings:
                    st.markdown(f"{icons[fnd.level]} {fnd.text}")

        with st.expander("Brouillon BM (moteur de règles, sans IA) – à copier"):
            st.markdown(draft)
            st.code(draft, language=None)

        st.divider()
        st.markdown("### Synthèse rédigée par l'assistant IA")
        if not API_KEY:
            st.warning("Configurer ANTHROPIC_API_KEY pour la synthèse rédigée et la discussion.")
        else:
            case_json = {
                "bilan_de_reference": ref.strftime("%Y-%m-%d"),
                "biologie": schema.df_to_records(bio[bio["date"] <= ref]),
                "traitements": schema.df_to_records(tx),
                "prescription_hd": schema.df_to_records(rx),
                "contexte": {k: v for k, v in ctx.items() if v not in (None, "", "Non renseigné", False)},
            }
            if st.button("Générer la synthèse BM", type="primary"):
                msgs = [{"role": "user", "content": ai.case_message(case_json, draft)}]
                with st.spinner("Rédaction de la synthèse…"):
                    try:
                        msgs.append({"role": "assistant", "content": ai.chat(ai.make_client(API_KEY), msgs)})
                        st.session_state.chat = msgs
                    except ai.AIError as e:
                        st.error(str(e))

            chat = st.session_state.get("chat", [])
            for m in chat[1:]:
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])
            if chat:
                with st.expander("Copier la dernière synthèse"):
                    st.code(chat[-1]["content"], language=None)
                q = st.chat_input("Précision ou correction (ex. « le Mircera a été baissé de 150 à 75 le mois dernier »)")
                if q:
                    chat = chat + [{"role": "user", "content": q}]
                    with st.spinner("Réflexion…"):
                        try:
                            chat.append({"role": "assistant", "content": ai.chat(ai.make_client(API_KEY), chat)})
                            st.session_state.chat = chat
                            st.rerun()
                        except ai.AIError as e:
                            st.error(str(e))

# ------------------------------------------------------------------ protocole
with tabs[6]:
    st.markdown(ai.PROTOCOLE)

# ------------------------------------------------------------------ barre latérale
with st.sidebar:
    st.header("Dossier")
    if not APP_PASSWORD:
        st.warning("Mode local : aucun mot de passe (APP_PASSWORD) n'est défini. À configurer avant tout partage.")
    st.markdown(f"IA : {'✅ Claude configuré' if API_KEY else '⚠️ clé ANTHROPIC_API_KEY absente'}")
    if st.button("Nouveau patient (vider)"):
        set_case(schema.empty_bio(), schema.empty_tx(), schema.empty_rx(), schema.CTX_DEFAULT)
        st.session_state.import_msg = ""
        st.rerun()
    if st.button("Charger le cas fictif"):
        set_case(*exemple.load())
        st.rerun()

    export = dossier.to_dict(bio, tx, rx, ctx)
    ref_sel = st.session_state.get(f"ref_{ver}")
    if ref_sel is not None:
        export["bilan_de_reference"] = pd.Timestamp(ref_sel).strftime("%Y-%m-%d")

    if not EN_LIGNE:  # échange avec Claude Desktop / Claude Code : uniquement sur l'ordinateur local
        st.divider()
        st.subheader("🤝 Claude (MCP)")
        st.caption("Échange direct avec Claude Desktop / Claude Code via le serveur MCP « assistant-hd », "
                   "sans clé API (utilise ton abonnement Claude).")
        if st.button("📤 Envoyer à Claude", disabled=bio.empty,
                     help="Claude pourra lire ce dossier avec l'outil « lire_dossier_application »."):
            dossier.ecrire(dossier.FICHIER_APP_VERS_CLAUDE, export, source="application")
            st.success("Dossier envoyé. Dans Claude, demande : « Analyse le dossier de l'Assistant HD ».")
        recu = dossier.lire(dossier.FICHIER_CLAUDE_VERS_APP)
        if recu:
            st.info(f"Dossier préparé par Claude le {str(recu.get('_horodatage', '?')).replace('T', ' à ')} "
                    f"({len(recu.get('biologie', []))} bilan(s), {len(recu.get('traitements', []))} traitement(s)).")
            c_a, c_b = st.columns(2)
            if c_a.button("📥 Importer", type="primary", help="Remplace le dossier affiché par celui envoyé par Claude"):
                set_case(*dossier.from_dict(recu))
                st.session_state.incertitudes = recu.get("incertitudes", [])
                st.session_state.import_msg = "Dossier importé depuis Claude."
                dossier.FICHIER_CLAUDE_VERS_APP.unlink(missing_ok=True)
                st.rerun()
            if c_b.button("Ignorer"):
                dossier.FICHIER_CLAUDE_VERS_APP.unlink(missing_ok=True)
                st.rerun()

    st.divider()
    st.download_button("💾 Exporter le dossier (JSON)", json.dumps(export, ensure_ascii=False, indent=1),
                       file_name="dossier_hd.json", mime="application/json")
    up = st.file_uploader("📂 Réouvrir un dossier (JSON)", type=["json"], key=f"json_{ver}")
    if up is not None:
        try:
            set_case(*dossier.from_dict(json.loads(up.getvalue().decode("utf-8"))))
            st.rerun()
        except (ValueError, KeyError, TypeError) as e:
            st.error(f"Fichier invalide : {e}")
    st.caption("Aucune donnée n'est conservée sur le serveur : exportez le dossier pour le reprendre plus tard.")
