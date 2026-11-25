"""Moteur de règles déterministe de l'Assistant HD.

Applique les règles validées (KDIGO 2026 anémie, KDIGO 2017 CKD-MBD, KDOQI 2015,
UK Renal Association, règles locales du service) aux données saisies et produit,
par rubrique, des constats classés :
  - ok                    : aucune modification nécessaire
  - modification          : adaptation thérapeutique proposée
  - information manquante : ce qu'il faut préciser pour décider
  - alerte                : situation à risque / à vérifier en priorité
Toutes les propositions restent soumises à la validation du néphrologue.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import pandas as pd

from .schema import FREQUENCES

# ---------------------------------------------------------------- constantes
PTH_LSN = 74.1  # pg/mL, limite supérieure de la normale du laboratoire
PTH_MIN, PTH_MAX = 2 * PTH_LSN, 9 * PTH_LSN  # 148,2 – 666,9 pg/mL
PAL_OS_LSN = 20.0  # µg/L, repère de PAL osseuses élevées
HB_MAX_ASE = 11.5
MIRCERA_ALERTE_UGKG = 2.0  # µg/kg/4 semaines (convention interne du service)
MIRCERA_ALERTE_ABS = 360.0  # µg/mois
ARANESP_ALERTE_UGKG_SEM = 1.5  # µg/kg/semaine
MIRCERA_PRES = [30, 40, 50, 60, 75, 100, 120, 150, 200, 250, 360]
ARANESP_PRES = [10, 15, 20, 30, 40, 50, 60, 80, 100, 130, 150, 300, 500]
CRP_INFLAM = 10.0
DELAI_MODIF = 28  # jours : éviter une nouvelle adaptation avant 4 semaines

OK, MODIF, MANQUE, ALERTE = "ok", "modification", "information manquante", "alerte"
_PRIO = {ALERTE: 3, MODIF: 2, MANQUE: 1, OK: 0}


@dataclass
class Finding:
    level: str
    text: str


@dataclass
class DomainResult:
    key: str
    title: str
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, text: str) -> None:
        self.findings.append(Finding(level, text))

    @property
    def status(self) -> str:
        if not self.findings:
            return OK
        return max(self.findings, key=lambda f: _PRIO[f.level]).level


@dataclass
class Case:
    bio: pd.DataFrame
    tx: pd.DataFrame
    rx: pd.DataFrame
    ctx: dict
    ref_date: pd.Timestamp | None = None  # bilan de référence


# ---------------------------------------------------------------- utilitaires
def fmt(v, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "?"
    s = f"{float(v):.{nd}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def fdate(d) -> str:
    return pd.Timestamp(d).strftime("%d/%m/%y") if d is not None and not pd.isna(d) else "?"


def _bio(case: Case) -> pd.DataFrame:
    b = case.bio.dropna(subset=["date"]).sort_values("date")
    if case.ref_date is not None:
        b = b[b["date"] <= case.ref_date]
    return b


def series(case: Case, col: str) -> list[tuple[pd.Timestamp, float]]:
    b = _bio(case)
    s = b[["date", col]].dropna()
    return [(r["date"], float(r[col])) for _, r in s.iterrows()]


def last(case: Case, col: str):
    s = series(case, col)
    return s[-1] if s else (None, None)


def history_txt(s: list, unit: str = "", n: int = 3, nd: int = 2) -> str:
    """'11,5 g/dL (12,1 le 05/07/26 ; 12,8 le 04/04/26)'"""
    if not s:
        return "?"
    d, v = s[-1]
    txt = f"{fmt(v, nd)}{(' ' + unit) if unit else ''}"
    prev = s[-n:-1][::-1]
    if prev:
        txt += " (" + " ; ".join(f"{fmt(pv, nd)} le {fdate(pd_)}" for pd_, pv in prev) + ")"
    return txt


def ref_day(case: Case) -> pd.Timestamp:
    if case.ref_date is not None:
        return case.ref_date
    b = case.bio.dropna(subset=["date"])
    return b["date"].max() if len(b) else pd.Timestamp.today().normalize()


def tx_active(case: Case, categorie: str) -> pd.DataFrame:
    t = case.tx
    if t.empty:
        return t
    return t[(t["categorie"] == categorie) & (t["statut"].fillna("En cours") == "En cours")]


def tx_any(case: Case, categorie: str) -> pd.DataFrame:
    t = case.tx
    return t if t.empty else t[t["categorie"] == categorie]


def tx_label(row) -> str:
    parts = [str(row.get("molecule") or row.get("categorie"))]
    if pd.notna(row.get("dose")):
        parts.append(f"{fmt(row['dose'])}{(' ' + str(row['unite'])) if row.get('unite') else ''}")
    if row.get("frequence"):
        parts.append(str(row["frequence"]))
    return " ".join(parts)


def recent_change(case: Case, row, days: int = DELAI_MODIF) -> bool:
    d = row.get("date_modif")
    if d is None or pd.isna(d):
        return False
    return (ref_day(case) - pd.Timestamp(d)).days <= days


def change_txt(row) -> str:
    d = row.get("date_modif")
    if d is None or pd.isna(d):
        return ""
    prev = row.get("dose_precedente")
    if pd.notna(prev) and pd.notna(row.get("dose")):
        return f"modifié le {fdate(d)} ({fmt(prev)} → {fmt(row['dose'])})"
    return f"modifié le {fdate(d)}"


def rx_current(case: Case):
    r = case.rx.dropna(subset=["date"]).sort_values("date") if not case.rx.empty else case.rx
    if r.empty:
        r = case.rx
    return None if r.empty else r.iloc[-1]


def poids(case: Case):
    p = case.ctx.get("poids_kg")
    if p:
        return float(p)
    rx = rx_current(case)
    if rx is not None and pd.notna(rx.get("poids_sec")):
        return float(rx["poids_sec"])
    return None


def dose_per_4w(row):
    f = FREQUENCES.get(row.get("frequence") or "")
    if f is None or pd.isna(row.get("dose")):
        return None
    return float(row["dose"]) * f


def step_down(dose: float, pres: list, factor: float = 0.75):
    target = dose * factor
    cands = [p for p in pres if p <= target]
    return max(cands) if cands else min(pres)


def step_up(dose: float, pres: list, factor: float = 1.25):
    target = dose * factor
    cands = [p for p in pres if p >= target]
    return min(cands) if cands else max(pres)


def mol(row) -> str:
    return str(row.get("molecule") or "").lower()


def yes(case: Case, key: str) -> bool:
    return case.ctx.get(key) == "Oui"


def unknown(case: Case, key: str) -> bool:
    return case.ctx.get(key) in (None, "", "Non renseigné")


# ================================================================ ANÉMIE
def anemie(case: Case) -> DomainResult:
    r = DomainResult("anemie", "Hb / Fer / ASE")
    s_hb = series(case, "hb")
    if not s_hb:
        r.add(MANQUE, "Hb prédialyse non renseignée.")
        return r
    d_hb, hb = s_hb[-1]
    _, ferr = last(case, "ferritine")
    _, cst = last(case, "cst")
    _, crp = last(case, "crp")
    inflam = crp is not None and crp > CRP_INFLAM
    infection = yes(case, "infection_active")

    parts = [f"Hb {history_txt(s_hb, 'g/dL', nd=1)}"]
    if ferr is not None:
        parts.append(f"ferritine {fmt(ferr, 0)} µg/L")
    if cst is not None:
        parts.append(f"CST {fmt(cst, 0)} %")
    if crp is not None:
        parts.append(f"CRP {fmt(crp, 1)} mg/L")

    # cinétique de l'Hb
    rising_fast = falling_fast = False
    if len(s_hb) >= 2:
        d0, hb0 = s_hb[-2]
        days = max((d_hb - d0).days, 1)
        delta = hb - hb0
        if days <= 42 and delta > 1.0:
            rising_fast = True
        if delta < -1.0:
            falling_fast = True

    _, hb_post = last(case, "hb_post")
    if hb_post is not None and hb_post - hb > 1.5:
        r.add(ALERTE, f"Écart Hb début/fin important ({fmt(hb, 1)} → {fmt(hb_post, 1)} g/dL) : "
                      "hémoconcentration ou problème de prélèvement à vérifier ; ne pas considérer l'Hb de fin comme une correction.")

    ase = tx_active(case, "ASE")
    hif = tx_active(case, "HIF-PHI")
    fer = tx_active(case, "Fer IV")
    ase_any = tx_any(case, "ASE")
    w = poids(case)

    # ---------- traitements en cours
    if not ase.empty:
        parts.append("sous " + ", ".join(tx_label(x) for _, x in ase.iterrows()))
    elif not ase_any.empty:
        st = ase_any.iloc[-1]
        parts.append(f"{st.get('molecule') or 'ASE'} {str(st.get('statut')).lower()} {change_txt(st)}".strip())
    if not hif.empty:
        parts.append("sous " + ", ".join(tx_label(x) for _, x in hif.iterrows()))
    r.summary = ", ".join(parts) + "."

    if not ase.empty and not hif.empty:
        r.add(ALERTE, "ASE et HIF-PHI simultanément actifs : association non recommandée, vérifier la date de relais.")

    # ---------- sous HIF-PHI : pas de cible d'Hb
    if not hif.empty:
        if hb >= 12.0 or rising_fast:
            r.add(MODIF, "Sous HIF-PHI : Hb élevée ou en hausse rapide → réduire la dose selon le RCP (pas de cible d'Hb sous HIF-PHI).")
        elif hb < 9.0 or yes(case, "symptomes_anemie"):
            r.add(MODIF, "Sous HIF-PHI : Hb basse ou symptômes d'anémie → adapter la dose selon le RCP, rechercher carence martiale, saignement, inflammation.")
        else:
            r.add(OK, "Sous HIF-PHI : pas de cible d'Hb à atteindre ; maintien de la dose minimale efficace (éviter transfusions et symptômes).")
        if not tx_active(case, "Chélateur du phosphore").empty:
            r.add(OK, "Rappel : espacer la prise du HIF-PHI des chélateurs du phosphate / cations polyvalents (interaction).")
        if yes(case, "thrombose") or yes(case, "cancer_actif") or yes(case, "evt_cv_recent"):
            r.add(ALERTE, "Antécédent thrombotique, cancer actif ou événement CV récent : réévaluer la balance bénéfice/risque du HIF-PHI.")

    # ---------- sous ASE
    elif not ase.empty:
        row = ase.iloc[0]
        m = mol(row)
        d4w = dose_per_4w(row)
        is_mircera = "mircera" in m
        is_aranesp = "aranesp" in m or "darb" in m
        pres = MIRCERA_PRES if is_mircera else ARANESP_PRES if is_aranesp else None
        recent = recent_change(case, row)
        reduced_recently = pd.notna(row.get("dose_precedente")) and pd.notna(row.get("dose")) and row["dose_precedente"] > row["dose"]

        if unknown(case, "thrombose"):
            r.add(MANQUE, "Antécédents thrombotiques non renseignés : préciser notamment une thrombose de FAV avant toute majoration d'ASE.")
        prudent = yes(case, "thrombose")
        if prudent:
            r.add(ALERTE, "Antécédent thrombotique" + (" (thrombose de FAV)" if case.ctx.get("thrombose_fav") else "")
                  + " : dose minimale efficace d'ASE, ne pas rechercher une Hb élevée ; discuter une cible plus prudente avec le prescripteur.")

        if recent:
            r.add(OK, f"ASE {change_txt(row)} : attendre ≥ 4 semaines avant une nouvelle adaptation, sauf hausse rapide ou Hb excessive.")

        # dose pondérale
        if d4w is None:
            r.add(MANQUE, "Fréquence d'administration de l'ASE à préciser pour calculer la dose pondérale.")
        elif w is None:
            r.add(MANQUE, "Poids du patient non renseigné : dose pondérale d'ASE non calculable.")
        elif is_mircera:
            ugkg = d4w / w
            r.summary += f" Mircera {fmt(d4w, 0)} µg/4 sem = {fmt(ugkg)} µg/kg/4 sem."
            if ugkg > MIRCERA_ALERTE_UGKG or d4w >= MIRCERA_ALERTE_ABS:
                txt = (f"Besoins élevés en Mircera ({fmt(ugkg)} µg/kg/4 sem > 2) "
                       + ("dans un contexte inflammatoire " if inflam else "")
                       + ": rechercher les causes corrigibles d'hyporéponse (fer, inflammation, saignement, HPT, dialyse insuffisante) "
                         "et discuter un relais par roxadustat")
                contra = [lab for key, lab in [("cancer_actif", "cancer actif"), ("evt_cv_recent", "événement CV récent"), ("thrombose", "thrombose")] if yes(case, key)]
                if contra:
                    txt += f" — attention : {', '.join(contra)} (contre-indication relative au HIF-PHI)"
                else:
                    txt += " après évaluation du risque cardiovasculaire, thrombotique et néoplasique"
                r.add(ALERTE, txt + ".")
        elif is_aranesp:
            ugkg_sem = d4w / 4 / w
            r.summary += f" Aranesp {fmt(d4w / 4, 0)} µg/sem = {fmt(ugkg_sem)} µg/kg/sem."
            if ugkg_sem >= ARANESP_ALERTE_UGKG_SEM:
                r.add(ALERTE, f"Dose élevée d'Aranesp ({fmt(ugkg_sem)} µg/kg/sem ≥ 1,5) : rechercher une hyporéponse "
                              "(fer, inflammation, saignement, HPT, dialyse) ; discuter un HIF-PHI si elle persiste.")

        dose = row.get("dose")
        # décisions selon l'Hb
        if hb >= 13.0:
            r.add(MODIF, f"Hb {fmt(hb, 1)} g/dL ≥ 13 sous ASE : suspension temporaire de {row.get('molecule') or 'l’ASE'} à discuter, contrôle Hb à 2–4 semaines.")
        elif hb >= HB_MAX_ASE or rising_fast:
            why = f"Hb {fmt(hb, 1)} ≥ 11,5 g/dL" if hb >= HB_MAX_ASE else "hausse d'Hb > 1 g/dL en < 6 semaines"
            if pd.notna(dose) and pres:
                r.add(MODIF, f"{why} : diminuer {row.get('molecule')} {fmt(dose, 0)} → {step_down(float(dose), pres)} {row.get('unite') or 'µg'} (≈ −25 %), contrôle Hb à 2–4 semaines.")
            else:
                r.add(MODIF, f"{why} : diminuer la dose d'ASE d'environ 25 %, contrôle Hb à 2–4 semaines.")
        elif hb < 10.0:
            iron_def = ferr is not None and cst is not None and ferr <= 500 and cst <= 30
            if reduced_recently:
                r.add(OK, f"Baisse d'Hb à interpréter après la réduction volontaire d'ASE ({change_txt(row)}) : surveiller la cinétique avant de réaugmenter.")
            if iron_def:
                r.add(MODIF, "Hb < 10 g/dL avec bilan martial insuffisant : optimiser le fer IV avant de majorer l'ASE.")
            elif inflam or infection:
                r.add(ALERTE, "Hb < 10 g/dL dans un contexte inflammatoire/infectieux : rechercher et traiter la cause ; hyporéponse probable.")
            if not (recent or reduced_recently or iron_def):
                if unknown(case, "thrombose"):
                    r.add(MANQUE, "Majoration d'ASE envisageable mais antécédents thrombotiques à préciser d'abord.")
                elif prudent:
                    r.add(MODIF, "Hb < 10 g/dL : majoration prudente de l'ASE seulement si symptômes/risque transfusionnel (antécédent thrombotique).")
                elif pd.notna(dose) and pres:
                    r.add(MODIF, f"Hb < 10 g/dL : augmenter {row.get('molecule')} {fmt(dose, 0)} → {step_up(float(dose), pres)} {row.get('unite') or 'µg'} (≈ +25 %) après exclusion d'un saignement, contrôle à 4 semaines.")
                else:
                    r.add(MODIF, "Hb < 10 g/dL : augmenter l'ASE d'environ 25 % après exclusion des causes réversibles.")
        else:
            if falling_fast:
                r.add(ALERTE, "Hb en baisse > 1 g/dL : rechercher saignement, carence martiale, inflammation ; contrôle rapproché avant toute modification.")
            else:
                r.add(OK, "Hb dans la cible sous ASE (< 11,5 g/dL) : maintien de la dose minimale efficace.")

    # ---------- sans ASE ni HIF-PHI
    else:
        if hb <= 9.0 or (hb < 10.0 and falling_fast):
            r.add(MODIF, f"Hb {fmt(hb, 1)} g/dL sans ASE : discuter l'introduction/reprise d'un ASE après correction des causes réversibles (fer, saignement, inflammation).")
            if unknown(case, "thrombose"):
                r.add(MANQUE, "Antécédents thrombotiques (notamment thrombose de FAV) à préciser avant l'introduction d'un ASE.")
        elif hb < 10.0:
            r.add(ALERTE, f"Hb {fmt(hb, 1)} g/dL sans ASE : surveiller ; ASE à discuter si Hb ≤ 9–10 persistante ou symptômes.")
        else:
            r.add(OK, "Hb sans ASE : pas de cible à respecter (les cibles KDIGO s'appliquent sous ASE) ; pas d'action.")

    # ---------- fer
    fer_lbl = ", ".join(tx_label(x) for _, x in fer.iterrows()) if not fer.empty else None
    if ferr is None or cst is None:
        r.add(MANQUE, "Ferritine et/ou CST manquants : bilan martial à compléter.")
    elif ferr > 700 or cst >= 40:
        if fer_lbl:
            r.add(MODIF, f"Ferritine {fmt(ferr, 0)} µg/L / CST {fmt(cst, 0)} % (> 700 ou ≥ 40 %) : suspendre temporairement le fer IV ({fer_lbl}), réévaluer le bilan martial.")
        else:
            r.add(OK, "Réserves martiales élevées : pas de fer IV.")
    elif ferr <= 500 and cst <= 30:
        if infection:
            r.add(ALERTE, "Carence martiale mais infection active : différer le fer IV jusqu'au contrôle de l'infection.")
        elif fer_lbl and (hb < HB_MAX_ASE or not ase.empty or not hif.empty):
            r.add(MODIF, f"Ferritine ≤ 500 et CST ≤ 30 % : majorer le fer IV ({fer_lbl}).")
        elif fer_lbl:
            r.add(OK, f"Ferritine ≤ 500 et CST ≤ 30 % mais Hb {fmt(hb, 1)} g/dL sans ASE : maintenir {fer_lbl}, pas de majoration nécessaire.")
        elif hb >= HB_MAX_ASE and ase.empty and hif.empty:
            r.add(OK, "Bilan martial bas mais pas d'anémie ni d'ASE : pas d'indication au fer IV, surveiller.")
        else:
            r.add(MODIF, "Ferritine ≤ 500 et CST ≤ 30 % : introduire un fer IV (ex. Venofer 100 mg/semaine).")
    else:
        if fer_lbl:
            r.add(OK, f"Bilan martial entre les seuils : maintenir {fer_lbl} avec surveillance (ne pas arrêter le fer sur la seule ferritine > 500).")
        else:
            r.add(OK, "Bilan martial satisfaisant sans fer IV.")
    if inflam and cst is not None and cst < 20 and ferr is not None and ferr > 500:
        r.add(ALERTE, "Ferritine élevée avec CST bas et CRP élevée : carence fonctionnelle / inflammation, interpréter la ferritine avec prudence.")
    return r


# ================================================================ SODIUM
def sodium(case: Case) -> DomainResult:
    r = DomainResult("sodium", "Na / NaD")
    s = series(case, "na")
    rx = rx_current(case)
    nad = rx.get("nad") if rx is not None else None
    if not s:
        r.add(MANQUE, "Natrémie prédialyse non renseignée.")
        return r
    d_last = s[-1][0]
    win = [v for d, v in s if (d_last - d).days <= 92]
    mean = sum(win) / len(win)
    r.summary = f"Na début {history_txt(s, 'mmol/L', nd=0)} ; moyenne 3 mois {fmt(mean, 1)} mmol/L ({len(win)} valeur(s))"
    if nad is None or pd.isna(nad):
        r.summary += "."
        r.add(MANQUE, "NaD prescrit non renseigné (onglet Prescription HD).")
        return r
    r.summary += f", NaD prescrit {fmt(nad, 0)} mmol/L."
    target = round(mean)
    if abs(nad - mean) >= 2:
        sens = "supérieur" if nad > mean else "inférieur"
        risk = ("transfert sodé, soif, prise de poids interdialytique, HTA" if nad > mean
                else "crampes, hypotensions intradialytiques")
        r.add(MODIF, f"NaD {sens} à la natrémie habituelle ({risk}) : proposer NaD {nad:.0f} → {target} mmol/L (dialyse isonatrique), "
                     "en tenant compte des concentrations disponibles, de la PA et de la tolérance.")
    else:
        r.add(OK, f"Dialyse quasi isonatrique : maintenir NaD {nad:.0f} mmol/L.")
    if len(win) < 2:
        r.add(MANQUE, "Une seule natrémie sur 3 mois : moyenne peu fiable.")
    return r


# ================================================================ POTASSIUM
def potassium(case: Case) -> DomainResult:
    r = DomainResult("potassium", "Potassium")
    s = series(case, "k_pre")
    _, kpost = last(case, "k_post")
    rx = rx_current(case)
    bain = rx.get("bain_k") if rx is not None else None
    chel = tx_active(case, "Chélateur du potassium")
    chel_lbl = ", ".join(tx_label(x) for _, x in chel.iterrows()) if not chel.empty else None
    if not s:
        r.add(MANQUE, "Kaliémie prédialyse non renseignée.")
        return r
    k = s[-1][1]
    r.summary = f"K début {history_txt(s, 'mmol/L')}" + (f", K fin {fmt(kpost)}" if kpost is not None else "")
    r.summary += (f", bain K{fmt(bain, 0)}" if bain is not None and not pd.isna(bain) else "") + (f", sous {chel_lbl}" if chel_lbl else "") + "."
    if bain is None or pd.isna(bain):
        r.add(MANQUE, "Potassium du bain non renseigné (onglet Prescription HD).")
        bain = None
    elif bain not in (2.0, 3.0):
        r.add(ALERTE, f"Bain K{fmt(bain)} : seuls les bains K2 et K3 sont disponibles dans l'unité.")

    lows = [v for _, v in s[-3:] if v < 4.0]
    if k >= 6.5:
        r.add(ALERTE, f"Hyperkaliémie sévère ({fmt(k)}) : évaluation urgente (ECG), prise en charge sans attendre l'optimisation du chélateur.")
    elif k > 5.5:
        if bain == 3.0 and not chel_lbl:
            r.add(MODIF, f"K {fmt(k)} > 5,5 sous bain K3 sans chélateur : introduire un chélateur du potassium (stratégie du service : K3 + résine avant K2).")
        elif bain == 3.0 and chel_lbl:
            r.add(MODIF, f"K {fmt(k)} > 5,5 sous K3 + {chel_lbl} : vérifier observance, apports, dose/fréquence du chélateur et Kt/V ; "
                         "si hyperkaliémie réfractaire, discuter le passage au bain K2.")
        elif bain == 2.0:
            r.add(MODIF, f"K {fmt(k)} > 5,5 sous bain K2 : vérifier observance du chélateur, apports et qualité de dialyse"
                         + ("" if chel_lbl else " ; introduire un chélateur du potassium") + ".")
        else:
            r.add(MODIF, f"K {fmt(k)} > 5,5 : adapter (chélateur, bain) selon le bain prescrit.")
    elif bain == 2.0 and k < 5.0:
        r.add(MODIF, f"K {fmt(k)} < 5 sous bain K2 : discuter le retour à un bain K3.")
    elif bain == 2.0 and k <= 5.5:
        r.add(MODIF, f"K {fmt(k)} entre 5 et 5,5 sous bain K2 : discuter bain K3 + chélateur du potassium.")
    elif k < 4.0:
        if chel_lbl:
            r.add(MODIF, f"K {fmt(k)} < 4 sous {chel_lbl} : réduire ou arrêter le chélateur du potassium.")
        elif len(lows) >= 2:
            r.add(MODIF, "Kaliémie prédialyse régulièrement < 4 sous K3 (bain le plus riche disponible) : maintenir K3, rechercher apports insuffisants, "
                         "dénutrition, pertes digestives ; adaptation des apports avec la diététicienne.")
        else:
            r.add(OK, f"K {fmt(k)} légèrement bas : maintenir K3, surveiller.")
    else:
        r.add(OK, "Kaliémie prédialyse dans la cible (4,0–5,5) : pas de modification.")
    if kpost is not None and kpost < 3.0:
        r.add(ALERTE, f"K fin de dialyse {fmt(kpost)} < 3 : risque rythmique" + (" — privilégier K3." if bain == 2.0 else "."))
    return r


# ================================================================ NT-proBNP / PS / PA
def volemie(case: Case) -> DomainResult:
    r = DomainResult("volemie", "NT-proBNP / poids sec / PA")
    s = series(case, "ntprobnp")
    rx_hist = case.rx.dropna(subset=["poids_sec"]).sort_values("date") if not case.rx.empty else case.rx
    ps_txt = ""
    if not rx_hist.empty:
        ps_now = rx_hist.iloc[-1]["poids_sec"]
        ps_txt = f"PS {fmt(ps_now, 1)} kg"
        if len(rx_hist) >= 2 and rx_hist.iloc[-2]["poids_sec"] != ps_now:
            ps_txt += f" (modifié de {fmt(rx_hist.iloc[-2]['poids_sec'], 1)} kg le {fdate(rx_hist.iloc[-1]['date'])})"
    antihtn = tx_active(case, "Antihypertenseur")
    ahtn_lbl = ", ".join(tx_label(x) for _, x in antihtn.iterrows()) if not antihtn.empty else None
    hypo = case.ctx.get("hypotensions_id")
    pas = case.ctx.get("pas_pre")
    fevg = case.ctx.get("fevg")

    parts = []
    if s:
        parts.append(f"NT-proBNP {history_txt(s, 'pg/mL', nd=0)}")
    if ps_txt:
        parts.append(ps_txt)
    if ahtn_lbl:
        parts.append(f"antihypertenseurs : {ahtn_lbl}")
    if pas:
        parts.append(f"PAS prédialyse ~{fmt(pas, 0)} mmHg")
    if hypo == "Oui":
        parts.append("hypotensions intradialytiques")
    r.summary = ", ".join(parts) + "." if parts else ""

    if not s:
        r.add(MANQUE, "NT-proBNP non renseigné.")
        return r
    nt = s[-1][1]
    rising = len(s) >= 2 and nt > s[-2][1] * 1.3
    if fevg is not None and fevg < 40:
        r.add(ALERTE, f"FEVG {fmt(fevg, 0)} % : insuffisance cardiaque à FEVG réduite, avis cardiologique ; prudence avec la baisse du PS et l'arrêt d'un bêtabloquant.")
    if nt > 35000 and fevg is None:
        r.add(ALERTE, "NT-proBNP très élevé : rechercher une cardiopathie sous-jacente (ETT) et pas seulement adapter le poids sec.")

    if rising or nt > 35000:
        if unknown(case, "hypotensions_id"):
            r.add(MANQUE, "Tolérance des séances (hypotensions intradialytiques) à préciser avant d'envisager une modification du PS.")
        if hypo == "Oui" and ahtn_lbl:
            r.add(MODIF, f"NT-proBNP en hausse avec hypotensions intradialytiques : discuter réduction, décalage de prise ou arrêt des antihypertenseurs ({ahtn_lbl}) "
                         "AVANT toute baisse du poids sec, selon leurs indications cardiovasculaires.")
        elif hypo == "Oui":
            r.add(MODIF, "NT-proBNP en hausse mais mauvaise tolérance hémodynamique : ne pas baisser le PS d'emblée ; allongement de séance pour réduire le débit d'UF à discuter.")
        else:
            r.add(MODIF, "NT-proBNP en hausse : rechercher une surcharge clinique ; si confirmée, réduction progressive du PS (± allongement des séances)."
                         + (f" Revoir aussi les antihypertenseurs ({ahtn_lbl})." if ahtn_lbl else ""))
    elif len(s) >= 2 and nt > s[-2][1] * 1.1:
        r.add(OK, "NT-proBNP en légère hausse : surveiller la cinétique et les signes de surcharge ; pas de modification du PS sur ce seul critère.")
    else:
        r.add(OK, "NT-proBNP stable ou en baisse : maintien du poids sec.")
    if pas and pas >= 160 and hypo != "Oui":
        r.add(MODIF, "HTA prédialytique : rechercher une surcharge résiduelle avant d'ajouter un antihypertenseur ; réévaluer le PS.")
    diur = tx_active(case, "Diurétique")
    if not diur.empty and case.ctx.get("diurese_residuelle") in ("Non", "Non renseigné"):
        r.add(MANQUE, "Diurétique prescrit : vérifier la diurèse résiduelle et l'intérêt du traitement.")
    return r


# ================================================================ BICARBONATES
def bicarbonates(case: Case) -> DomainResult:
    r = DomainResult("bicar", "BBNa")
    s = series(case, "bicar")
    rx = rx_current(case)
    hco3 = rx.get("bain_hco3") if rx is not None else None
    if not s:
        r.add(MANQUE, "Bicarbonate prédialyse non renseigné.")
        return r
    v = s[-1][1]
    r.summary = f"HCO3 début {history_txt(s, 'mmol/L', nd=1)}" + (f", bain bicarbonate {fmt(hco3, 0)} mmol/L" if hco3 is not None and not pd.isna(hco3) else "") + "."
    if v < 18:
        r.add(MODIF, f"Acidose prédialyse ({fmt(v, 1)} < 18) : augmenter le bicarbonate du bain (en restant ≤ 37 mmol/L) après vérification des apports et de la dose de dialyse.")
    elif v > 26:
        r.add(MODIF, f"Bicarbonate prédialyse > 26 ({fmt(v, 1)}) : rechercher une alcalose / excès d'apport alcalin, discuter la baisse du bicarbonate du bain.")
    else:
        r.add(OK, "BBNa dans la fourchette 18–26 mmol/L : maintenir la prescription.")
    return r


# ================================================================ PHOSPHOCALCIQUE
def phosphocalcique(case: Case) -> DomainResult:
    r = DomainResult("mbd", "Phosphocalcique")
    s_ca, s_p, s_pth, s_pal = (series(case, c) for c in ("ca", "phos", "pth", "pal_os"))
    ca = s_ca[-1][1] if s_ca else None
    p = s_p[-1][1] if s_p else None
    pth = s_pth[-1][1] if s_pth else None
    pal = s_pal[-1][1] if s_pal else None
    calcimim = tx_active(case, "Calcimimétique (agoniste CaSR)")
    vitd = tx_active(case, "Vitamine D active")
    chel = tx_active(case, "Chélateur du phosphore")
    calc = tx_active(case, "Calcium")
    lbl = lambda df: ", ".join(tx_label(x) for _, x in df.iterrows())  # noqa: E731

    parts = []
    if ca is not None:
        parts.append(f"Ca {history_txt(s_ca, 'mmol/L', n=2)}")
    if p is not None:
        parts.append(f"P {history_txt(s_p, 'mmol/L', n=2)}")
    if pth is not None:
        parts.append(f"PTH {history_txt(s_pth, 'pg/mL', nd=0)} (~{fmt(pth / PTH_LSN, 1)} × LSN)")
    if pal is not None:
        parts.append(f"PAL osseuses {history_txt(s_pal, 'µg/L', nd=1)}")
    ttt = [lbl(x) for x in (calcimim, vitd, chel, calc) if not x.empty]
    if ttt:
        parts.append("sous " + ", ".join(ttt))
    r.summary = ", ".join(parts) + "." if parts else ""
    if pth is None and ca is None and p is None:
        r.add(MANQUE, "Bilan phosphocalcique non renseigné.")
        return r

    calcimim_recent = any(recent_change(case, x, 56) for _, x in calcimim.iterrows())
    pal_high = pal is not None and pal > PAL_OS_LSN
    pal_rising = len(s_pal) >= 2 and pal is not None and pal > s_pal[-2][1] * 1.25

    # Phosphore
    if p is not None and p > 1.78:
        msg = f"Hyperphosphatémie ({fmt(p)} mmol/L)"
        if not chel.empty:
            obs = case.ctx.get("observance_chelateurs")
            if obs == "Bonne":
                r.add(MODIF, f"{msg} malgré une bonne observance de {lbl(chel)} (prise aux repas) : majorer le chélateur, revoir les apports avec la diététicienne.")
            elif obs == "Mauvaise / partielle":
                r.add(MODIF, f"{msg} avec observance insuffisante de {lbl(chel)} : renforcer l'éducation (prise pendant les repas) avant toute majoration.")
            else:
                r.add(MANQUE, f"{msg} sous {lbl(chel)} : vérifier l'observance et la prise aux repas AVANT toute majoration.")
        else:
            r.add(MODIF, f"{msg} sans chélateur : revoir les apports et introduire un chélateur du phosphate.")
        if not vitd.empty:
            r.add(MODIF, f"Hyperphosphatémie sous vitamine D active ({lbl(vitd)}) : réévaluer ce traitement selon Ca, PTH et PAL osseuses (pas d'arrêt systématique).")
    elif p is not None and p > 1.45:
        r.add(OK, f"Phosphatémie modérément élevée ({fmt(p)}) : surveillance, vérifier observance des chélateurs.")

    # Calcium
    if ca is not None:
        if ca > 2.6:
            r.add(MODIF, "Hypercalcémie : réévaluer suppléments calciques, chélateurs calciques et vitamine D active.")
        elif ca < 2.0:
            if not calcimim.empty:
                r.add(MODIF, f"Hypocalcémie < 2,0 mmol/L sous {lbl(calcimim)} : discuter réduction du calcimimétique, ECG, contrôle rapproché.")
            else:
                r.add(MODIF, "Hypocalcémie < 2,0 mmol/L : rechercher cause, discuter supplémentation calcique / vitamine D.")
        elif ca < 2.1 and not calcimim.empty:
            r.add(OK, f"Hypocalcémie modérée (≥ 2,0) sous calcimimétique, asymptomatique : tolérée, pas de baisse systématique du traitement.")

    # PTH + PAL osseuses (jamais la PTH isolément)
    if pth is None:
        r.add(MANQUE, "PTH non renseignée (contrôle tous les 3–6 mois).")
    elif pth > PTH_MAX:
        if calcimim_recent:
            r.add(OK, f"PTH > 9 × LSN mais calcimimétique récemment modifié : évaluer l'effet avant nouvelle adaptation.")
        else:
            opts = "majorer le calcimimétique" if not calcimim.empty else "introduire un calcimimétique (cinacalcet / Parsabiv) ou une vitamine D active selon Ca et P"
            r.add(MODIF, f"PTH {fmt(pth, 0)} > 9 × LSN ({fmt(PTH_MAX, 0)}) : {opts}.")
    elif pth < PTH_MIN:
        if pal_high:
            r.add(OK, "PTH < 2 × LSN mais PAL osseuses élevées : ne pas réduire d'emblée les traitements, surveiller.")
        elif not calcimim.empty or not vitd.empty:
            r.add(MODIF, f"PTH {fmt(pth, 0)} < 2 × LSN : freinage excessif, réduire calcimimétique et/ou vitamine D active.")
        else:
            r.add(ALERTE, "PTH basse sans traitement freinateur : risque d'os adynamique, surveiller.")
    else:
        if pal_rising or pal_high:
            if calcimim_recent:
                r.add(OK, "PAL osseuses élevées/en hausse mais calcimimétique récemment majoré : ne pas proposer de nouvelle majoration, "
                          "contrôler calcémie, PTH et PAL osseuses.")
            else:
                r.add(MODIF, "PTH dans la plage KDIGO mais PAL osseuses élevées/en hausse : remodelage osseux actif, discuter intensification du traitement de l'HPT"
                             + (" (majoration du calcimimétique)." if not calcimim.empty else "."))
        else:
            r.add(OK, "PTH dans la plage KDIGO (2–9 × LSN)" + (" et PAL osseuses stables" if pal is not None else "") + " : maintenir les traitements.")
    if pal is None:
        r.add(MANQUE, "PAL osseuses non renseignées : à interpréter avec la PTH.")
    if calcimim_recent:
        r.add(OK, "Calcimimétique modifié récemment : surveiller la calcémie.")
    return r


# ================================================================ NUTRITION
def nutrition(case: Case) -> DomainResult:
    r = DomainResult("nutrition", "Nutrition")
    s_alb, s_pre, s_npcr = series(case, "albumine"), series(case, "prealbumine"), series(case, "npcr")
    _, crp = last(case, "crp")
    alb = s_alb[-1][1] if s_alb else None
    pre = s_pre[-1][1] if s_pre else None
    npcr = s_npcr[-1][1] if s_npcr else None
    np_ = tx_active(case, "Nutrition parentérale")
    cno = tx_active(case, "Compléments nutritionnels oraux")

    # évolution pondérale (poids sec sur ~3 mois)
    wt_txt, wt_loss = "", False
    rx = case.rx.dropna(subset=["poids_sec", "date"]).sort_values("date") if not case.rx.empty else case.rx
    if len(rx) >= 2:
        last_d = rx.iloc[-1]["date"]
        old = rx[rx["date"] >= last_d - timedelta(days=100)].iloc[0]
        dw = rx.iloc[-1]["poids_sec"] - old["poids_sec"]
        if dw != 0:
            wt_txt = f"PS {fmt(old['poids_sec'], 1)} → {fmt(rx.iloc[-1]['poids_sec'], 1)} kg"
            wt_loss = dw / old["poids_sec"] <= -0.05

    parts = []
    if alb is not None:
        parts.append(f"albumine {history_txt(s_alb, 'g/L', nd=0)}")
    if pre is not None:
        parts.append(f"préalbumine {history_txt(s_pre, 'g/L', n=2)}")
    if npcr is not None:
        parts.append(f"nPCR {fmt(npcr)}")
    if wt_txt:
        parts.append(wt_txt)
    if not np_.empty or not cno.empty:
        parts.append("sous " + ", ".join(tx_label(x) for d in (np_, cno) for _, x in d.iterrows()))
    r.summary = ", ".join(parts) + "." if parts else ""

    if alb is None:
        r.add(MANQUE, "Albumine non renseignée.")
        return r
    signals = []
    if alb < 35:
        signals.append("albumine < 35")
    elif alb < 38:
        signals.append("albumine 35–38")
    if len(s_alb) >= 2 and alb <= s_alb[-2][1] - 3:
        signals.append("albumine en baisse")
    if pre is not None and pre < 0.30:
        signals.append("préalbumine < 0,30")
    if len(s_pre) >= 2 and pre is not None and pre < s_pre[-2][1] * 0.85:
        signals.append("préalbumine en baisse")
    if npcr is not None and npcr < 1.0:
        signals.append("nPCR < 1,0")
    if wt_loss:
        signals.append("perte de poids ≥ 5 %")

    if alb <= 35:
        r.add(ALERTE, "Albumine ≤ 35 g/L : signal d'alerte nutritionnel, même en contexte inflammatoire" + (f" (CRP {fmt(crp, 1)})" if crp and crp > CRP_INFLAM else "") + ".")
    if npcr is None:
        r.add(MANQUE, "nPCR non disponible : à récupérer.")
    if pre is None:
        r.add(MANQUE, "Préalbumine non disponible.")
    if len(signals) >= 2:
        if not np_.empty or not cno.empty:
            r.add(MODIF, f"Dégradation nutritionnelle concordante ({', '.join(signals)}) sous support nutritionnel : réévaluer apports et tolérance avec la diététicienne.")
        else:
            r.add(MODIF, f"Dégradation nutritionnelle concordante ({', '.join(signals)}) : avis diététique, compléments nutritionnels oraux"
                         + ", nutrition parentérale perdialytique à discuter si échec." )
    elif signals:
        r.add(OK, f"Signal isolé ({signals[0]}) : pas de conclusion à une dénutrition sur un seul paramètre ; surveiller poids, albumine, préalbumine et nPCR.")
    else:
        r.add(OK, "Paramètres nutritionnels satisfaisants : surveillance.")
    return r


# ================================================================ ÉPURATION
def epuration(case: Case) -> DomainResult:
    r = DomainResult("epuration", "Épuration")
    s = series(case, "ktv_daug")
    _, ktvi = last(case, "ktv_ionique")
    _, up = last(case, "uree_pre")
    _, uq = last(case, "uree_post")
    rx = rx_current(case)
    parts = []
    if s:
        parts.append(f"Kt/V Daugirdas {history_txt(s, n=2)}")
    if ktvi is not None:
        parts.append(f"Kt/V ionique {fmt(ktvi)}")
    urr = None
    if up and uq:
        urr = (up - uq) / up * 100
        parts.append(f"URR {fmt(urr, 0)} %")
    if rx is not None:
        desc = []
        if rx.get("technique"):
            desc.append(str(rx["technique"]))
        if pd.notna(rx.get("duree_h")):
            desc.append(f"{fmt(rx['duree_h'], 1)} h")
        if pd.notna(rx.get("seances_sem")):
            desc.append(f"× {fmt(rx['seances_sem'], 0)}/sem")
        if pd.notna(rx.get("qb")):
            desc.append(f"Qb {fmt(rx['qb'], 0)}")
        if rx.get("abord"):
            desc.append(str(rx["abord"]))
        if desc:
            parts.append(" ".join(desc))
    r.summary = ", ".join(parts) + "." if parts else ""

    catheter = "cathéter" in str(case.ctx.get("abord_type", "")).lower() or "cath" in str(rx.get("abord") if rx is not None else "").lower()
    if not s:
        if urr is not None:
            (r.add(OK, "URR ≥ 65 %.") if urr >= 65 else r.add(MODIF, f"URR {fmt(urr, 0)} % < 65 % : vérifier la dose de dialyse."))
        r.add(MANQUE, "Kt/V Daugirdas non renseigné.")
    else:
        k = s[-1][1]
        if k >= 1.4:
            r.add(OK, f"spKt/V {fmt(k)} ≥ 1,4 : épuration satisfaisante, maintenir la prescription.")
        elif k >= 1.2:
            r.add(MODIF, f"spKt/V {fmt(k)} entre 1,2 et 1,4 (sous la cible) : vérifier reproductibilité, abord, Qb effectif et temps réel ; "
                         "si confirmé, optimiser (allongement de séance, Qb, HDF).")
        else:
            r.add(MODIF, f"spKt/V {fmt(k)} < 1,2 (minimum KDOQI) : optimiser la dose de dialyse (durée, Qb, fréquence), contrôler l'abord vasculaire.")
    rec = case.ctx.get("recirculation")
    if rec:
        if catheter and rec <= 22:
            r.add(OK, f"Recirculation {fmt(rec, 0)} % (Fresenius 6008) sur cathéter : fréquente, pas d'intervention sur cette seule mesure.")
        elif rec > 15:
            r.add(ALERTE, f"Recirculation {fmt(rec, 0)} % : interpréter avec Kt/V, débits et pressions ; vérifier l'abord si persistante.")
    if case.ctx.get("abord_type") == "Non renseigné" and not (rx is not None and rx.get("abord")):
        r.add(MANQUE, "Type d'abord vasculaire à préciser (« AV » = accès vasculaire, ne pas présumer d'une FAV).")
    return r


DOMAINS = [anemie, sodium, potassium, volemie, bicarbonates, phosphocalcique, nutrition, epuration]


def analyse(case: Case) -> list[DomainResult]:
    return [f(case) for f in DOMAINS]


def bm_draft(results: list[DomainResult], ref: pd.Timestamp | None = None) -> str:
    """Synthèse BM déterministe (brouillon) au format du service."""
    mois = ref.strftime("%m/%Y") if ref is not None else ""
    lines = [f"## BM {mois}".strip(), ""]
    modifs, manques = [], []
    for res in results:
        acts = [f.text for f in res.findings if f.level in (MODIF, ALERTE)]
        oks = [f.text for f in res.findings if f.level == OK]
        line = f"**{res.title} :** {res.summary}"
        if oks:
            line += " " + " ".join(oks)
        if acts:
            line += " " + " ".join(f"**{a}**" for a in acts)
        lines.append(line)
        lines.append("")
        modifs += [f"{res.title} – {f.text}" for f in res.findings if f.level == MODIF]
        manques += [f"{res.title} – {f.text}" for f in res.findings if f.level == MANQUE]
    if modifs:
        lines.append("### Modifications proposées")
        lines += [f"{i}. {m}" for i, m in enumerate(modifs, 1)]
        lines.append("")
    if manques:
        lines.append("### À préciser")
        lines += [f"- {m}" for m in manques]
    lines.append("")
    lines.append("*Propositions à valider par le néphrologue.*")
    return "\n".join(lines)
