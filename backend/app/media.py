import hashlib
import os
import warnings
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from app.config import settings

register_heif_opener()
FORMATS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "GIF": (".gif", "image/gif"),
    "TIFF": (".tiff", "image/tiff"),
    "BMP": (".bmp", "image/bmp"),
    "HEIF": (".heic", "image/heic"),
    "WEBP": (".webp", "image/webp"),
}


class InvalidImage(ValueError):
    pass


def inspect_image(path: Path) -> tuple[str, str]:
    Image.MAX_IMAGE_PIXELS = settings().max_image_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as img:
                fmt = img.format
                if fmt not in FORMATS or img.width * img.height > settings().max_image_pixels:
                    raise InvalidImage("Unsupported or oversized image")
                img.seek(0)
                img.load()
                return FORMATS[fmt]
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise InvalidImage("Unreadable image") from exc


def analysis_image(path: Path, max_size: int = 2400) -> Image.Image:
    with Image.open(path) as img:
        img.seek(0)
        frame = ImageOps.exif_transpose(img).convert("RGB")
        frame.thumbnail((max_size, max_size))
        return frame.copy()


def analysis_jpeg(path: Path) -> bytes:
    buf = BytesIO()
    analysis_image(path).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def media_path(photo_id: int, preview: bool = False) -> Path:
    folder = settings().data_dir / ("previews" if preview else "spool")
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{photo_id}{'.jpg' if preview else '.original'}"


def write_preview(photo_id: int, original: Path):
    target = media_path(photo_id, preview=True)
    temp = target.with_suffix(".tmp")
    analysis_image(original, 1400).save(temp, format="JPEG", quality=88)
    os.replace(temp, target)


def digest_file(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()
