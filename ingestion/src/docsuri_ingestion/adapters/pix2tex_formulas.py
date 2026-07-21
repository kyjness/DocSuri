"""pix2tex formula reader — recovers approximate LaTeX from a formula's page-crop image.

Import-guarded and optional (``pip install .[formulas]``). The output is an approximation and is
stored as ``FormulaBlock.latexOcr``, which is indexed for search but never rendered: the crop
stays what the reader sees, so a mis-read equation cannot be displayed as the paper's own.
"""

from __future__ import annotations

import io
import logging

log = logging.getLogger("docsuri.ingestion.formulas")

_PIX2TEX_MISSING = "formula reader not installed (pip install .[formulas])"


class Pix2TexFormulaReader:
    """Read LaTeX back out of a rendered formula image, one crop at a time."""

    def __init__(self) -> None:
        self._model = None

    def read_latex(self, image: bytes) -> str | None:
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - assets extra not installed
            raise RuntimeError(_PIX2TEX_MISSING) from exc
        try:
            model = self._loaded()
            with Image.open(io.BytesIO(image)) as img:
                return str(model(img.convert("RGB")) or "").strip() or None
        except Exception:  # noqa: BLE001 - best-effort: an unreadable crop keeps its image only
            log.warning("formula OCR failed", exc_info=True)
            return None

    def _loaded(self):
        if self._model is None:
            try:
                from pix2tex.cli import LatexOCR
            except ImportError as exc:  # pragma: no cover - optional extra
                raise RuntimeError(_PIX2TEX_MISSING) from exc
            self._model = LatexOCR()
        return self._model
