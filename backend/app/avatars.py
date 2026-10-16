"""Decode profile pictures and keep only a small, metadata-free square image."""

import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 25_000_000
AVATAR_SIZE = 256


def normalize_avatar(data: bytes) -> bytes:
    if len(data) > MAX_AVATAR_BYTES:
        raise ValueError("Размер фотографии должен быть не больше 5 МБ.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                    raise ValueError("Выберите фотографию в формате JPG, PNG, WEBP или GIF.")
                if source.width * source.height > MAX_AVATAR_PIXELS:
                    raise ValueError("Фотография слишком большая. Выберите изображение до 25 мегапикселей.")
                source.seek(0)
                square = ImageOps.fit(
                    ImageOps.exif_transpose(source).convert("RGBA"),
                    (AVATAR_SIZE, AVATAR_SIZE),
                    method=Image.Resampling.LANCZOS,
                )
                avatar = Image.new("RGB", square.size, "white")
                avatar.paste(square, mask=square.getchannel("A"))
                output = BytesIO()
                avatar.save(output, format="JPEG", quality=90, optimize=True)
                return output.getvalue()
    except (
        OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("Не удалось прочитать фотографию. Выберите другое изображение.") from exc
