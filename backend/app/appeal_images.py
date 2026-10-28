"""Render a predictable OCR stamp while retaining a separate unmarked camera frame."""

import warnings
from io import BytesIO
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()

MAX_PHOTO_BYTES = 6 * 1024 * 1024
MAX_PHOTOS = 3
MIN_LONG_SIDE = 1280
MIN_SHORT_SIDE = 720
MAX_PIXELS = 16_000_000


def prepare_upload(content):
    """Normalize gallery/result images and strip EXIF, GPS and original filenames."""
    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Одна фотография должна занимать не больше 6 МБ")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP", "HEIF", "HEIC"}:
                    raise HTTPException(422, "Загрузите фотографию JPG, PNG, WebP или HEIC")
                if source.width * source.height > 50_000_000 or min(source.size) < 200:
                    raise HTTPException(422, "Размер фотографии: от 200 пикселей по каждой стороне до 50 мегапикселей")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((2560, 2560), Image.Resampling.LANCZOS)
                # Copy pixels into a clean image: do not carry metadata through conversion.
                clean = Image.new("RGB", image.size, "white")
                clean.paste(image)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise HTTPException(422, "Не удалось прочитать фотографию. Выберите другой файл.") from exc
    content = jpeg(clean, 88)
    width, height = clean.size
    clean.thumbnail((800, 800), Image.Resampling.LANCZOS)
    return {"original": content, "stamped": content, "preview": jpeg(clean, 82), "width": width, "height": height}


def stamp_lines(capture, timezone):
    date = capture.captured_at.astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y %H:%M")
    lat = f"{abs(capture.latitude):.4f}".replace(".", ",") + ("N" if capture.latitude >= 0 else "S")
    lon = f"{abs(capture.longitude):.4f}".replace(".", ",") + ("E" if capture.longitude >= 0 else "W")
    return date, f"{lat} {lon}"


def stamp_font(size):
    for name in ("DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def jpeg(image, quality):
    output = BytesIO()
    image.save(output, "JPEG", quality=quality, subsampling=0)
    return output.getvalue()


def prepare_photo(content, capture, timezone):
    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Один снимок должен занимать не больше 6 МБ")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as source:
                if source.format != "JPEG":
                    raise HTTPException(422, "Нужен JPEG-снимок встроенной камеры")
                if source.width * source.height > MAX_PIXELS:
                    raise HTTPException(422, "Слишком большое разрешение снимка")
                if max(source.size) < MIN_LONG_SIDE or min(source.size) < MIN_SHORT_SIDE:
                    raise HTTPException(422, "Недостаточное разрешение камеры: нужно хотя бы 1280 × 720")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise HTTPException(422, "Не удалось прочитать снимок. Сделайте фотографию ещё раз.") from exc
    original = jpeg(image, 95)
    lines = stamp_lines(capture, timezone)
    font = stamp_font(max(28, round(image.width * 0.038)))
    draw = ImageDraw.Draw(image)
    padding = max(10, round(image.width * 0.012))
    line_height = round(font.size * 1.35)
    panel_width = max(round(draw.textlength(line, font=font)) for line in lines) + padding * 2
    panel_height = line_height * 2 + padding * 2
    left, top = image.width - panel_width, image.height - panel_height
    draw.rectangle((left, top, image.width, image.height), fill="black")
    for index, line in enumerate(lines):
        draw.text((image.width - padding, top + padding + index * line_height), line,
                  fill="white", font=font, anchor="rt", stroke_width=0)
    stamped = jpeg(image, 95)
    width, height = image.size
    image.thumbnail((800, 800), Image.Resampling.LANCZOS)
    return {"original": original, "stamped": stamped, "preview": jpeg(image, 85), "width": width, "height": height}
