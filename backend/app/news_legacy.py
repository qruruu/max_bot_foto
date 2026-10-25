"""Frozen import source for pre-editor publications, never used as a live fallback."""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

CONTENT_DIR = Path(__file__).with_name("news_content")


class Screenshot(BaseModel):
    file: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*\.(png|jpg|webp)$")
    alt: str = Field(min_length=1)
    caption: str = Field(min_length=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class Section(BaseModel):
    title: str = Field(min_length=1)
    paragraphs: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    screenshots: list[Screenshot] = Field(default_factory=list)


class Post(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    publishedAt: date
    category: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    sections: list[Section] = Field(min_length=1)
