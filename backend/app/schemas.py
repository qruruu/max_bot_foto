import re
from datetime import date, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.catalog import WORK_TYPES, Role, Status


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginInput(StrictModel):
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class PasswordInput(StrictModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class UserCreate(StrictModel):
    login: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_.@-]+$")
    name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=12, max_length=256)
    role: Role = Role.OPERATOR
    active: bool = True


class UserUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    password: str | None = Field(default=None, min_length=12, max_length=256)
    role: Role | None = None
    active: bool | None = None


class ChatInput(StrictModel):
    max_chat_id: int
    name: str = Field(min_length=1, max_length=150)
    active: bool = True


class DistrictInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    active: bool = True
    geometry: dict
    confirm_overlap: bool = False


class PhotoEdit(StrictModel):
    version: int = Field(ge=1)
    is_spam: bool = False
    photo_date: date | None = None
    photo_time: time | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    work_type: str | None = None
    detected_address: str | None = Field(default=None, max_length=1000)
    detected_city: str | None = Field(default=None, max_length=300)

    @field_validator("work_type")
    @classmethod
    def validate_work_type(cls, value):
        if value is not None and value not in WORK_TYPES:
            raise ValueError("Вид работы отсутствует в справочнике")
        return value

    @model_validator(mode="after")
    def coordinate_pair(self):
        if self.is_spam and self.work_type is not None:
            raise ValueError("Спаму нельзя назначить вид работы")
        changed = self.model_fields_set
        if ("latitude" in changed) != ("longitude" in changed) or (self.latitude is None) != (
            self.longitude is None
        ):
            raise ValueError("Широту и долготу нужно указать вместе")
        return self


class PhotoFilters(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=30, ge=1, le=100)
    accepted_only: bool = False
    date_from: date | None = None
    date_to: date | None = None
    day: date | None = None
    district_id: int | None = None
    chat_id: int | None = None
    work_type: str | None = None
    status: Status | None = None
    operator_id: int | None = None
    date_basis: Literal["photo", "received"] = "photo"

    @model_validator(mode="after")
    def validate_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Начало периода должно быть раньше его окончания")
        if self.work_type and self.work_type != "NONE" and self.work_type not in WORK_TYPES:
            raise ValueError("Неизвестный вид работы")
        return self


def validate_polygon(data: dict):
    from shapely.geometry import MultiPolygon, shape
    from shapely.validation import explain_validity

    try:
        geo = shape(data)
    except Exception as exc:
        raise ValueError("Некорректный GeoJSON") from exc
    if geo.geom_type not in {"Polygon", "MultiPolygon"} or geo.is_empty or not geo.is_valid:
        raise ValueError("Требуется корректный Polygon/MultiPolygon: " + explain_validity(geo))
    if geo.has_z:
        raise ValueError("Нужны двумерные координаты longitude/latitude")
    left, bottom, right, top = geo.bounds
    if not (-180 <= left <= right <= 180 and -90 <= bottom <= top <= 90):
        raise ValueError("Координаты полигона вне допустимого диапазона")
    if len(re.findall(r"\d+", geo.wkt)) > 40000:
        raise ValueError("Слишком много вершин полигона")
    return MultiPolygon([geo]) if geo.geom_type == "Polygon" else geo
