"""Local camera-stamp OCR with cached CPU models and a bounded Tesseract fallback."""

import logging
from functools import lru_cache
from pathlib import Path
from threading import Lock
from time import monotonic

from PIL import Image

from app.config import settings
from app.media import analysis_image
from app.ocr_models import verified_models
from app.recognition import TesseractOCR

logger = logging.getLogger(__name__)
_inference_lock = Lock()


@lru_cache(maxsize=1)
def paddle_engine(directory: Path, threads: int):
    # Explicit verified paths prevent the library from downloading anything at runtime.
    detector, recognizer = verified_models(directory)
    import cv2
    import onnxruntime
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    onnxruntime.disable_telemetry_events()
    cv2.setNumThreads(1)
    return RapidOCR(params={
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.MOBILE,
        "Det.model_path": str(detector),
        "Det.limit_type": "max",
        "Det.limit_side_len": 1280,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
        "Rec.lang_type": LangRec.ESLAV,
        "Rec.model_path": str(recognizer),
        "Global.use_cls": False,
        "Global.text_score": 0.65,
        "Global.log_level": "error",
        "Global.max_side_len": 4000,
        "EngineConfig.onnxruntime.intra_op_num_threads": threads,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    })


def stamp_regions(image: Image.Image):
    """Find black stamp panels first; retain a full-frame fallback for other layouts."""
    import cv2
    import numpy as np

    small = image.copy()
    small.thumbnail((1000, 1000))
    gray = np.array(small.convert("L"))
    mask = (gray < 45).astype("uint8") * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), dtype="uint8"))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    width, height = small.size
    panels = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        near_edge = min(x, width - x - w) < width * 0.05 or min(y, height - y - h) < height * 0.05
        if (
            near_edge and area >= width * height * 0.005
            and 1.1 <= w / h <= 15 and w >= width * 0.2
            and cv2.contourArea(contour) / area > 0.8
        ):
            sx, sy = image.width / width, image.height / height
            box = (
                max(0, round(x * sx) - 6), max(0, round(y * sy) - 6),
                min(image.width, round((x + w) * sx) + 6),
                min(image.height, round((y + h) * sy) + 6),
            )
            panels.append((area, box))
    for _, box in sorted(panels, reverse=True)[:2]:
        yield image.crop(box)
    if image.height > image.width * 0.6:
        footer = image.crop((0, round(image.height * 0.6), image.width, image.height))
        yield footer
        # Only reached for incomplete metadata. Isolate bright lettering from snow,
        # paving and objects, recovering faint decimal points without guessing digits.
        kernel_size = max(7, min(61, round(footer.width / 70))) | 1
        highlighted = cv2.morphologyEx(
            np.array(footer.convert("L")), cv2.MORPH_TOPHAT,
            cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size)),
        )
        yield Image.fromarray(highlighted).convert("RGB")
    yield image


def stamp_text(output) -> str:
    """Join adjacent detections on the same physical line, not unrelated OCR passes."""
    if output.txts is None:
        return ""
    rows = []
    for box, text in sorted(zip(output.boxes, output.txts, strict=True), key=lambda pair: min(p[1] for p in pair[0])):
        left, right = min(p[0] for p in box), max(p[0] for p in box)
        top, bottom = min(p[1] for p in box), max(p[1] for p in box)
        center, height = (top + bottom) / 2, max(1, bottom - top)
        for row in rows:
            if abs(row[0] - center) < min(row[1], height) * 0.45:
                row[2].append((left, right, text))
                break
        else:
            rows.append((center, height, [(left, right, text)]))
    return "\n".join(" ".join(part[2] for part in sorted(row[2])) for row in rows)


class LocalOCR:
    @staticmethod
    def _recognize(image: Image.Image) -> str:
        import numpy as np

        config = settings()
        # Improve small stamp detection without unbounded upscaling of thin/wide images.
        scale = min(2, 1000 / max(image.size))
        if scale > 1:
            image = image.resize(
                tuple(round(side * scale) for side in image.size), Image.Resampling.LANCZOS
            )
        # RapidOCR's call parameters are mutable; never share a simultaneous inference.
        with _inference_lock:
            engine = paddle_engine(config.ocr_model_dir, config.ocr_threads)
            return stamp_text(engine(np.array(image)))

    def recognize(self, path: Path) -> str:
        config = settings()
        if config.ocr_backend == "tesseract":
            return TesseractOCR().recognize(path)
        deadline = monotonic() + config.ocr_timeout
        texts = []
        image = analysis_image(path, 4000)
        try:
            for region in stamp_regions(image):
                if monotonic() >= deadline:
                    break
                text = self._recognize(region)
                if text and text not in texts:
                    texts.append(text)
                combined = "\n\n--- OCR ---\n\n".join(texts)
                if TesseractOCR._metadata_complete(combined):
                    return combined
        except Exception:
            logger.warning("PaddleOCR unavailable; using local Tesseract fallback", exc_info=True)
        remaining = deadline - monotonic()
        if remaining > 0:
            try:
                text = TesseractOCR().recognize(path, timeout=remaining)
                if text and text not in texts:
                    texts.append(text)
            except (RuntimeError, OSError):
                if not texts:
                    raise
                logger.warning("Tesseract fallback failed; keeping neural OCR text")
        return "\n\n--- OCR ---\n\n".join(texts)
