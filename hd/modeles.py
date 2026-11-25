"""Modèles de données structurés (partagés par l'extraction IA et le serveur MCP)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Bilan(BaseModel):
    date: str = Field(description="Date du prélèvement au format AAAA-MM-JJ")
    hb: Optional[float] = Field(None, description="Hémoglobine DÉBUT de dialyse, g/dL")
    hb_post: Optional[float] = Field(None, description="Hémoglobine FIN de dialyse, g/dL")
    ferritine: Optional[float] = Field(None, description="µg/L")
    cst: Optional[float] = Field(None, description="Coefficient de saturation de la transferrine, %")
    crp: Optional[float] = Field(None, description="mg/L")
    na: Optional[float] = Field(None, description="Natrémie DÉBUT, mmol/L")
    k_pre: Optional[float] = Field(None, description="Kaliémie DÉBUT, mmol/L")
    k_post: Optional[float] = Field(None, description="Kaliémie FIN, mmol/L")
    bicar: Optional[float] = Field(None, description="Bicarbonates DÉBUT (BBNa), mmol/L")
    ca: Optional[float] = Field(None, description="Calcium total DÉBUT, mmol/L")
    phos: Optional[float] = Field(None, description="Phosphate DÉBUT, mmol/L")
    pth: Optional[float] = Field(None, description="PTH, pg/mL (= ng/L)")
    pal_os: Optional[float] = Field(None, description="Phosphatases alcalines osseuses, µg/L")
    albumine: Optional[float] = Field(None, description="g/L")
    prealbumine: Optional[float] = Field(None, description="g/L")
    npcr: Optional[float] = Field(None, description="g/kg/j")
    ntprobnp: Optional[float] = Field(None, description="pg/mL")
    ktv_daug: Optional[float] = Field(None, description="Kt/V Daugirdas")
    ktv_ionique: Optional[float] = Field(None, description="Kt/V par dialysance ionique")
    uree_pre: Optional[float] = Field(None, description="Urée DÉBUT, mmol/L")
    uree_post: Optional[float] = Field(None, description="Urée FIN, mmol/L")
    commentaire: Optional[str] = Field(None, description="ex. 'bilan mensuel' ou 'bilan intermédiaire'")


class Traitement(BaseModel):
    categorie: str = Field(description="Une des catégories : ASE, HIF-PHI, Fer IV, Calcium, Vitamine D native, Vitamine D active, "
                                       "Calcimimétique (agoniste CaSR), Chélateur du phosphore, Chélateur du potassium, Antihypertenseur, "
                                       "Diurétique, Nutrition parentérale, Compléments nutritionnels oraux, Autre")
    molecule: str
    dose: Optional[float] = Field(None, description="Dose par administration (nombre seul)")
    unite: Optional[str] = Field(None, description="µg, mg, UI, mL…")
    frequence: Optional[str] = Field(None, description="Une des valeurs : par séance (3/sem), par semaine, toutes les 2 semaines, "
                                                       "toutes les 4 semaines / mensuel, par jour, 2 fois/jour, 3 fois/jour, 3 fois/semaine, autre / à préciser")
    statut: str = Field("En cours", description="En cours, Suspendu ou Arrêté (rouge sur l'ordonnance = Suspendu)")
    date_modif: Optional[str] = Field(None, description="Date de début ou de dernière modification, AAAA-MM-JJ")
    dose_precedente: Optional[float] = None
    motif: Optional[str] = Field(None, description="Posologie textuelle complète, horaires, motif de modification")


class Prescription(BaseModel):
    date: Optional[str] = Field(None, description="AAAA-MM-JJ")
    bain_k: Optional[float] = Field(None, description="Potassium du bain : 2 ou 3 mmol/L (seuls disponibles)")
    bain_ca: Optional[float] = None
    nad: Optional[float] = Field(None, description="Sodium du dialysat prescrit (NaD), mmol/L")
    bain_hco3: Optional[float] = Field(None, description="Bicarbonate du dialysat prescrit, mmol/L")
    poids_sec: Optional[float] = Field(None, description="kg")
    technique: Optional[str] = Field(None, description="HD ou HDF")
    duree_h: Optional[float] = None
    seances_sem: Optional[float] = None
    qb: Optional[float] = None
    qd: Optional[float] = None
    abord: Optional[str] = Field(None, description="Descriptif de l'accès vasculaire (« AV » = accès vasculaire, pas forcément une FAV)")


class Contexte(BaseModel):
    poids_kg: Optional[float] = Field(None, description="Poids pour le calcul des doses ; vide = poids sec")
    abord_type: Optional[str] = Field(None, description="Non renseigné, FAV, Pontage prothétique, Cathéter tunnelisé, Cathéter non tunnelisé")
    thrombose: Optional[str] = Field(None, description="Antécédents thrombotiques : Non renseigné, Non, Oui")
    thrombose_fav: Optional[bool] = Field(None, description="Antécédent de thrombose de FAV")
    cancer_actif: Optional[str] = Field(None, description="Non renseigné, Non, Oui")
    evt_cv_recent: Optional[str] = Field(None, description="Événement cardiovasculaire récent : Non renseigné, Non, Oui")
    saignement: Optional[str] = Field(None, description="Non renseigné, Non, Oui")
    infection_active: Optional[str] = Field(None, description="Non renseigné, Non, Oui")
    hospitalisation_recente: Optional[str] = Field(None, description="Non renseigné, Non, Oui")
    hypotensions_id: Optional[str] = Field(None, description="Hypotensions intradialytiques : Non renseigné, Non, Oui")
    pas_pre: Optional[float] = Field(None, description="PAS prédialyse habituelle, mmHg")
    fevg: Optional[float] = Field(None, description="FEVG, %")
    observance_chelateurs: Optional[str] = Field(None, description="Non vérifiée, Bonne, Mauvaise / partielle")
    symptomes_anemie: Optional[str] = Field(None, description="Non renseigné, Non, Oui")
    diurese_residuelle: Optional[str] = Field(None, description="Non renseigné, Non, Oui")
    recirculation: Optional[float] = Field(None, description="Recirculation mesurée (Fresenius 6008), %")
    poids_fin_moyen: Optional[float] = Field(None, description="Poids de fin de séance moyen du mois, kg (synthèse des séances)")
    ppid_moyenne: Optional[float] = Field(None, description="Prise de poids interdialytique moyenne, kg")
    ktv_ionique_moyen: Optional[float] = Field(None, description="Kt/V ionique de fin de séance moyen du mois")
    notes: Optional[str] = None


class Extraction(BaseModel):
    bilans: list[Bilan]
    traitements: list[Traitement]
    prescriptions: list[Prescription]
    poids_kg: Optional[float] = None
    recirculation_pct: Optional[float] = None
    hypotensions_intradialytiques: Optional[bool] = None
    pas_pre_moyenne: Optional[float] = Field(None, description="PAS de début de séance moyenne du mois, mmHg")
    poids_fin_moyen: Optional[float] = Field(None, description="Poids de fin de séance moyen, kg")
    ppid_moyenne: Optional[float] = Field(None, description="Prise de poids interdialytique moyenne, kg")
    ktv_ionique_moyen: Optional[float] = Field(None, description="Kt/V ionique de fin de séance moyen")
    incertitudes: list[str] = Field(description="Valeurs ambiguës, illisibles ou à vérifier (ex. fréquences d'administration)")
