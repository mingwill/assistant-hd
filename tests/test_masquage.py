"""Masquage de l'en-tête patient sur un PDF A4 synthétique (2 pages)."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

from hd import masquage  # noqa: E402


def _pdf() -> bytes:
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page(width=595, height=842)  # A4
        page.insert_text((80, 160), "Patient: DUPONT JEAN  Ne le 01/01/1950", fontsize=12)   # ~19 % : en-tête
        page.insert_text((80, 600), "Hemoglobine 12.3", fontsize=12)                           # ~71 % : données
    return doc.tobytes()


def _noir(img: Image.Image, y_frac: float) -> float:
    w, h = img.size
    row = [img.getpixel((x, int(h * y_frac))) for x in range(0, w, 10)]
    return sum(1 for p in row if p == (0, 0, 0)) / len(row)


def test_pdf_masque_entete_conserve_donnees():
    pages = masquage.preparer([("bio.pdf", _pdf())])
    assert [n for n, _, _ in pages] == ["bio_p1.png", "bio_p2.png"] and all(m for _, _, m in pages)
    p1 = Image.open(io.BytesIO(pages[0][1])).convert("RGB")
    p2 = Image.open(io.BytesIO(pages[1][1])).convert("RGB")
    assert _noir(p1, 0.19) == 1.0 and _noir(p1, 0.27) == 1.0   # page 1 : bande large
    assert _noir(p2, 0.18) == 1.0 and _noir(p2, 0.25) < 0.5     # pages suivantes : bande étroite
    assert _noir(p1, 0.71) < 0.5                                  # données intactes


def test_images_non_masquees_et_option_desactivee():
    assert masquage.preparer([("capture.png", b"xx")]) == [("capture.png", b"xx", False)]
    pages = masquage.preparer([("bio.pdf", _pdf())], masquer_pdf=False)
    assert not any(m for _, _, m in pages)
    assert _noir(Image.open(io.BytesIO(pages[0][1])).convert("RGB"), 0.25) < 0.5
