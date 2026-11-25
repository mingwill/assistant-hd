"""Masquage de l'en-tête patient des documents MedWare avant tout envoi à l'IA.

Les PDF MedWare (bilan mensuel, prescription de dialyse, synthèse des séances, récapitulatif des traitements)
sont des images A4 sans couche texte. Leur identité patient est toujours au même endroit :
  - 1re page : encadré « Patient / Né(e) le / Adresse / Tél » (+ titre, prescripteur et N° IPP pour la prescription) ;
  - pages suivantes : nom du patient en haut à droite.
On recouvre ces bandes d'un rectangle noir sur toute la largeur, puis le médecin vérifie l'aperçu avant l'envoi.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

# bandes à masquer, en proportion de la hauteur de page (calibrées sur les documents MedWare A4)
BANDE_PAGE_1 = (0.150, 0.288)
BANDE_PAGES_SUIVANTES = (0.150, 0.198)
DPI = 150


def pages_pdf(data: bytes, dpi: int = DPI) -> list[Image.Image]:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        pages.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
    return pages


def masquer(img: Image.Image, premiere_page: bool) -> Image.Image:
    img = img.copy()
    h0, h1 = BANDE_PAGE_1 if premiere_page else BANDE_PAGES_SUIVANTES
    w, h = img.size
    ImageDraw.Draw(img).rectangle([0, int(h * h0), w, int(h * h1)], fill="black")
    return img


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def preparer(fichiers: list[tuple[str, bytes]], masquer_pdf: bool = True) -> list[tuple[str, bytes, bool]]:
    """-> [(nom, png, masqué)] : chaque page de PDF devient une image (masquée si demandé) ; les images restent telles quelles."""
    out = []
    for nom, data in fichiers:
        if nom.lower().endswith(".pdf"):
            for i, page in enumerate(pages_pdf(data)):
                img = masquer(page, i == 0) if masquer_pdf else page
                out.append((f"{nom.rsplit('.', 1)[0]}_p{i + 1}.png", _png(img), masquer_pdf))
        else:
            out.append((nom, data, False))
    return out
