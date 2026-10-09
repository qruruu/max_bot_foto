import logging
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal, Protocol

import pytesseract
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.catalog import WORK_TYPES
from app.config import settings
from app.media import analysis_image
from app.parsers import CoordinateParser, DateTimeParser

logger = logging.getLogger(__name__)


class OCRService(Protocol):
    def recognize(self, path: Path) -> str: ...


class TesseractOCR:
    @staticmethod
    def _metadata_complete(text: str) -> bool:
        timestamp = DateTimeParser().parse(text)
        coordinates = CoordinateParser().parse(text)
        return (
            timestamp.photo_date is not None
            and timestamp.photo_time is not None
            and coordinates.latitude is not None
            and coordinates.longitude is not None
        )

    def recognize(self, path: Path) -> str:
        # Sparse text recognition is suited to camera stamps in different corners.
        image = analysis_image(path, 4000)
        config = settings()
        deadline = monotonic() + config.ocr_timeout
        text = pytesseract.image_to_string(
            image,
            lang=config.ocr_languages,
            config="--psm 11",
            timeout=config.ocr_timeout,
        )
        # Retry any missing field, even when the date was readable on the first pass.
        # A block layout and enlargement help keep small timestamp/GPS lines together.
        for psm in (11, 6):
            if self._metadata_complete(text):
                break
            retry_image = ImageOps.grayscale(image)
            if psm == 6:
                scale = min(2, 4000 / max(retry_image.size))
                retry_image = retry_image.resize(
                    tuple(round(side * scale) for side in retry_image.size), Image.Resampling.LANCZOS
                )
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            try:
                extra = pytesseract.image_to_string(
                    retry_image,
                    lang=config.ocr_languages,
                    config=f"--psm {psm}",
                    timeout=remaining,
                )
                # Retain conflicting readings for review; never join tokens across passes.
                text += "\n\n--- OCR ---\n\n" + extra
            except (RuntimeError, OSError):
                logger.warning("OCR retry failed; keeping previously recognized text")
                break
        return text


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: Literal["SINGLE", "UNKNOWN", "MULTIPLE"]
    work_type: str | None
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    alternatives: list[str]

    @model_validator(mode="after")
    def validate_categories(self):
        if self.work_type is not None and self.work_type not in WORK_TYPES:
            raise ValueError("Unknown work type")
        if any(x not in WORK_TYPES for x in self.alternatives):
            raise ValueError("Unknown alternative")
        if self.result == "SINGLE" and (not self.work_type or self.alternatives):
            raise ValueError("SINGLE must have exactly one work type")
        if self.result != "SINGLE" and self.work_type is not None:
            raise ValueError("Ambiguous result must not assign a category")
        if self.result == "MULTIPLE" and len(set(self.alternatives)) < 2:
            raise ValueError("MULTIPLE requires alternatives")
        return self

    def automatic_work_type(self, threshold: float) -> str | None:
        return self.work_type if self.result == "SINGLE" and self.confidence >= threshold else None


@dataclass
class ClassificationResponse:
    classification: Classification | None
    raw: dict


class WorkTypeClassifier(Protocol):
    def classify(self, path: Path) -> ClassificationResponse: ...
