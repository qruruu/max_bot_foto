"""Company-owned reporting rules. A missing quantity is never a factual zero."""

import base64
from datetime import date
from io import BytesIO
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas import StrictModel

Quantity = Annotated[float, Field(multiple_of=0.001)]


class ReportingProfile(StrictModel):
    company_name: str = Field(default="", max_length=200)
    short_name: str = Field(default="", max_length=150)
    city: str = Field(default="", max_length=150)
    address: str = Field(default="", max_length=500)
    inn: str = Field(default="", max_length=12, pattern=r"^\d{0,12}$")
    ogrn: str = Field(default="", max_length=15, pattern=r"^\d{0,15}$")
    phone: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=150)
    recipient: list[str] = Field(default_factory=list, max_length=5)
    photo_url: str = Field(default="", max_length=1000)
    subject: str = Field(default="по содержанию земель общего пользования", max_length=500)
    letterhead_image: str = Field(default="", max_length=1_400_000)
    signature_image: str = Field(default="", max_length=1_400_000)

    @field_validator("letterhead_image", "signature_image")
    @classmethod
    def document_image(cls, value):
        if not value:
            return value
        from PIL import Image
        try:
            prefix, encoded = value.split(",", 1)
            expected = {"data:image/png;base64": "PNG", "data:image/jpeg;base64": "JPEG"}.get(prefix)
            if not expected:
                raise ValueError()
            content = base64.b64decode(encoded, validate=True)
            if len(content) > 1_048_576:
                raise ValueError()
            with Image.open(BytesIO(content)) as image:
                if image.format != expected or max(image.size) > 5000 or image.width * image.height > 12_000_000:
                    raise ValueError()
                image.verify()
        except Exception as error:
            raise ValueError("Загрузите изображение PNG или JPG размером до 1 МБ и до 5000 пикселей") from error
        return value

    @field_validator("photo_url")
    @classmethod
    def photo_link(cls, value):
        from urllib.parse import urlsplit
        if value:
            parts = urlsplit(value)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                raise ValueError("Укажите ссылку http или https без пароля")
        return value


class ReportingContract(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,60}$")
    number: str = Field(min_length=1, max_length=150)
    prefix: str = Field(default="", max_length=60)
    next_number: int = Field(default=1, ge=1, le=999999999)


class ReportingArea(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,60}$")
    contract_id: str = Field(max_length=60)
    name: str = Field(min_length=1, max_length=1000)
    district_ids: list[int] = Field(default_factory=list, max_length=300)


class ReportingAssignment(StrictModel):
    area_id: str = Field(max_length=60)
    quantity: Quantity | None = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    resources: str = Field(default="", max_length=500)
    annual_limit: Quantity | None = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)


class ReportingWindow(StrictModel):
    start: str = Field(pattern=r"^\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{2}-\d{2}$")

    @field_validator("start", "end")
    @classmethod
    def valid_day(cls, value):
        date.fromisoformat("2000-" + value)
        return value


class ReportingWork(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,60}$")
    name: str = Field(min_length=1, max_length=500)
    unit: str = Field(default="м²", min_length=1, max_length=20)
    season: Literal["all", "summer", "winter"] = "all"
    recurrence: Literal["daily", "monthly", "four_windows", "windows", "deadlines", "dates", "interval", "event"] = "daily"
    schedule_note: str = Field(default="", max_length=1000)
    windows: list[ReportingWindow] = Field(default_factory=list, max_length=30)
    dates: list[str] = Field(default_factory=list, max_length=60)
    interval_days: int = Field(default=5, ge=1, le=366)
    requires_event: bool = False
    photo_codes: list[str] = Field(default_factory=list, max_length=100)
    assignments: list[ReportingAssignment] = Field(default_factory=list, max_length=100)

    @field_validator("dates")
    @classmethod
    def valid_dates(cls, values):
        for value in values:
            date.fromisoformat("2000-" + value)
        return sorted(set(values))

    @model_validator(mode="after")
    def schedule_complete(self):
        if self.recurrence == "windows" and not self.windows:
            raise ValueError("Для окон выполнения укажите даты начала и окончания")
        if self.recurrence in {"deadlines", "dates"} and not self.dates:
            raise ValueError("Укажите календарные даты")
        if len({a.area_id for a in self.assignments}) != len(self.assignments):
            raise ValueError("Территория повторяется в одном виде работ")
        return self


class ReportingConfig(StrictModel):
    profile: ReportingProfile = Field(default_factory=ReportingProfile)
    contracts: list[ReportingContract] = Field(default_factory=list, max_length=30)
    areas: list[ReportingArea] = Field(default_factory=list, max_length=100)
    works: list[ReportingWork] = Field(default_factory=list, max_length=100)
    summer_start: str = ""
    summer_end: str = ""
    source_notes: str = Field(default="", max_length=5000)

    @field_validator("summer_start", "summer_end")
    @classmethod
    def season_day(cls, value):
        if value:
            date.fromisoformat("2000-" + value)
        return value

    @model_validator(mode="after")
    def references(self):
        for values in (self.contracts, self.areas, self.works):
            if len({v.id for v in values}) != len(values):
                raise ValueError("Повторяется идентификатор записи")
        contracts = {c.id for c in self.contracts}
        areas = {a.id for a in self.areas}
        if any(a.contract_id not in contracts for a in self.areas):
            raise ValueError("У территории не найден контракт")
        if any(a.area_id not in areas for w in self.works for a in w.assignments):
            raise ValueError("У работы не найдена территория")
        if bool(self.summer_start) != bool(self.summer_end):
            raise ValueError("Укажите обе границы летнего сезона")
        if self.summer_start and self.summer_start == self.summer_end:
            raise ValueError("Начало и конец летнего сезона должны различаться")
        return self


class ReportingSettingsInput(StrictModel):
    version: int = Field(ge=0)
    config: ReportingConfig


class ReportingLine(StrictModel):
    work_id: str = Field(max_length=60)
    area_id: str = Field(max_length=60)
    decision: Literal["pending", "include", "info", "skip"] = "pending"
    quantity: Quantity | None = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    resources: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=2000)
    cycle_complete: bool = False


class ReportingDocument(StrictModel):
    fact: list[ReportingLine] = Field(default_factory=list, max_length=2000)
    plan: list[ReportingLine] = Field(default_factory=list, max_length=2000)
    fact_season: Literal["", "summer", "winter"] = ""
    plan_season: Literal["", "summer", "winter"] = ""
    fact_events: list[str] = Field(default_factory=list, max_length=100)
    plan_events: list[str] = Field(default_factory=list, max_length=100)
    note: str = Field(default="", max_length=5000)


class ReportingSaveInput(StrictModel):
    version: int = Field(ge=1)
    document: ReportingDocument


class ReportingVersionInput(StrictModel):
    version: int = Field(ge=1)


class ReportingCreateInput(StrictModel):
    day: date
