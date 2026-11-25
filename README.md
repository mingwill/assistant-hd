# Assistant bilans mensuels hémodialyse – HUS Strasbourg

Application pilote d'aide à l'interprétation des bilans mensuels (BM) des patients hémodialysés,
construite à partir des règles calibrées avec le néphrologue (KDIGO 2026 anémie, KDIGO 2017 CKD-MBD,
KDOQI 2015, UK Renal Association, règles du service).

> ⚠️ Pilote : données **fictives ou réellement anonymisées** uniquement. Les propositions sont une aide
> à la décision, toujours soumises à la validation du néphrologue.

## Fonctionnement

| Onglet | Contenu |
|---|---|
| 📷 Import captures | Captures d'écran / PDF → l'IA (Claude) préremplit Biologie, Traitements, Prescription ; incertitudes signalées |
| 🧪 Biologie | Bilans datés (cinétiques) : Hb, fer, CRP, Na, K début/fin, BBNa, Ca, P, PTH, PAL osseuses, albumine, préalbumine, nPCR, NT-proBNP, Kt/V… |
| 💊 Traitements | ASE, HIF-PHI, fer IV, calcium, vit D native/active, calcimimétiques, chélateurs P et K, antihypertenseurs, NP, CNO… avec statut et modifications datées |
| 🩸 Prescription HD | Bain K/Ca, NaD, bicarbonate, poids sec, technique, durée, Qb, Qd, abord (historique daté) |
| 🧾 Contexte clinique | Antécédents thrombotiques, hypotensions, FEVG, observance des chélateurs… |
| 📋 Synthèse BM | Analyse du **moteur de règles** (fonctionne sans IA) + synthèse rédigée par Claude + discussion pour corriger |
| 📖 Protocole | Règles appliquées (`hd/protocole.md`) |

Le moteur de règles (`hd/rules.py`) est déterministe et auditable ; l'IA vérifie son analyse,
rédige la synthèse au format du service et permet d'apporter des précisions.

## Installation (Windows)

```powershell
py -3.15 -m pip install -r requirements.txt
```

Configuration : copier `.streamlit/secrets.example.toml` en `.streamlit/secrets.toml`, puis y mettre
le mot de passe et la clé API Anthropic (console.anthropic.com).

```powershell
Copy-Item .streamlit\secrets.example.toml .streamlit\secrets.toml
```

Lancer :

```powershell
py -3.15 -m streamlit run app.py
```

Sans clé API, l'application fonctionne en saisie manuelle avec le moteur de règles.
Sans `APP_PASSWORD`, elle tourne en « mode local » sans mot de passe (à ne pas partager ainsi).

## Connexion à Claude Desktop / Claude Code (MCP)

`mcp_server.py` expose l'assistant à Claude via MCP (utilise l'abonnement Claude, sans clé API) :

| Outil | Rôle |
|---|---|
| `protocole_hd` | Règles du service |
| `analyser_bilan` | Moteur de règles sur des données lues par Claude (ex. captures collées dans la conversation) |
| `lire_dossier_application` | Lit le dossier envoyé depuis l'appli (bouton « 📤 Envoyer à Claude ») |
| `envoyer_dossier_application` | Préremplit l'appli (bouton « 📥 Importer » dans la barre latérale) |

Le serveur MCP fonctionne uniquement en local (version installée sur l'ordinateur) ; il n'est pas inclus
dans la version en ligne, qui utilise la clé API configurée dans les secrets.

## Mise en ligne (Streamlit Community Cloud)

Fichier principal : `app.py`. Secrets à définir dans Settings → Secrets : `APP_PASSWORD` et `ANTHROPIC_API_KEY`.
En ligne, le mot de passe est obligatoire.

## Données

Rien n'est stocké côté serveur : utiliser « Exporter le dossier (JSON) » puis « Réouvrir un dossier ».
Le paramétrage du service (LSN PTH 74,1 pg/mL, seuils) est en tête de `hd/rules.py`.

## Tests

```powershell
py -3.15 -m pytest tests
```
