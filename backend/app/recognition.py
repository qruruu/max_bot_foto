from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import pytesseract
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.catalog import WORK_TYPES
from app.config import settings
from app.media import analysis_image


class OCRService(Protocol):
    def recognize(self, path: Path) -> str: ...


class TesseractOCR:
    def recognize(self, path: Path) -> str:
        # Sparse text recognition is suited to camera stamps in different corners.
        return pytesseract.image_to_string(
            analysis_image(path, 4000),
            lang=settings().ocr_languages,
            config="--psm 11",
            timeout=settings().ocr_timeout,
        )


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
