from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.catalog import WORK_TYPES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://maxphotos:maxphotos@db:5432/maxphotos"
    app_env: str = "production"
    app_origin: str = "http://localhost:8080"
    app_timezone: str = "Asia/Yekaterinburg"
    session_hours: int = 12
    cookie_secure: bool = True
    max_bot_token: str = ""
    max_api_url: str = "https://platform-api2.max.ru"
    max_verify_tls: bool = False
    max_update_mode: Literal["auto", "polling", "webhook"] = "auto"
    max_ca_bundle: str | None = None
    max_webhook_secret: str = ""
    max_download_hosts: str = "max.ru,max.com,okcdn.ru,mycdn.me,userapi.com"
    yandex_disk_token: str = ""
    yandex_disk_root: str = "MAX_PHOTOS"
    yandex_maps_api_key: str = ""
    ml_auto_train: bool = True
    ml_min_samples: int = Field(default=100, ge=4)
    ml_min_per_class: int = Field(default=20, ge=2)
    ml_min_classes: int = Field(default=2, ge=2, le=len(WORK_TYPES))
    ml_min_new_labels: int = Field(default=20, ge=1)
    ml_min_validation_per_class: int = Field(default=3, ge=1)
    ml_min_macro_f1: float = Field(default=0.70, ge=0, le=1)
    ml_min_class_precision: float = Field(default=0.90, ge=0, le=1)
    ml_epochs: int = Field(default=8, ge=1, le=100)
    ml_batch_size: int = Field(default=16, ge=2, le=256)
    ml_learning_rate: float = Field(default=0.0003, gt=0, le=0.1)
    ml_threads: int = Field(default=2, ge=1, le=32)
    ml_check_seconds: int = Field(default=60, ge=5)
    ml_download_backbone: bool = True
    ml_backbone_path: Path | None = None
    work_type_confidence_threshold: float = Field(default=0.8, ge=0, le=1)
    ocr_languages: str = "rus+eng"
    ocr_timeout: int = 60
    data_dir: Path = Path("/data")
    max_file_bytes: int = 52_428_800
    max_image_pixels: int = 60_000_000
    worker_idle_seconds: float = 2

    @property
    def max_transport(self) -> str:
        if self.max_update_mode != "auto":
            return self.max_update_mode
        return "polling" if self.app_env in {"development", "test"} else "webhook"

    @model_validator(mode="after")
    def validate_config(self):
        if not self.database_url.startswith("postgresql"):
            raise ValueError("PostgreSQL/PostGIS is required")
        ZoneInfo(self.app_timezone)
        if self.app_env == "production" and not self.cookie_secure:
            raise ValueError("Production requires COOKIE_SECURE=true and HTTPS")
        if self.app_env == "production" and self.max_transport == "polling":
            raise ValueError("MAX production delivery requires webhook; polling is for local development")
        if "/" in self.yandex_disk_root or not self.yandex_disk_root.strip():
            raise ValueError("YANDEX_DISK_ROOT must be a folder name")
        return self


@lru_cache
def settings() -> Settings:
    return Settings()
