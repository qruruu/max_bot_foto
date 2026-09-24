import mimetypes
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests


def get_extension(response, url):
    content_type = response.headers.get("Content-Type", "")
    content_type = content_type.split(";")[0].strip()

    ext = mimetypes.guess_extension(content_type)

    if ext == ".jpe":
        ext = ".jpg"

    if not ext or ext == ".bin":
        path = urlparse(url).path
        ext = Path(path).suffix

    if not ext or ext == ".bin":
        ext = ".jpg"

    return ext


def get_filename_from_response(response, url):
    # 1. Пробуем получить имя из Content-Disposition
    content_disposition = response.headers.get(
        "Content-Disposition",
        ""
    )

    if "filename=" in content_disposition:
        filename = content_disposition.split("filename=", 1)[1]
        filename = filename.strip().strip('"')

        if filename:
            return Path(unquote(filename)).name

    # 2. Пробуем взять имя из URL
    url_path = urlparse(url).path
    url_filename = Path(unquote(url_path)).name

    if url_filename and "." in url_filename:
        return url_filename

    return None


def download_photo(url, attachment, save_dir):
    response = requests.get(
        url,
        stream=True,
        timeout=60,
        verify=False,
    )

    response.raise_for_status()

    save_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = get_filename_from_response(
        response,
        url,
    )

    # MAX не дал исходное имя
    if not filename:
        payload = attachment.get("payload") or {}
        photo_id = payload.get("photo_id", "unknown")

        ext = get_extension(response, url)

        filename = f"photo_{photo_id}{ext}"

    # Защита от путей вроде ../../file.jpg
    filename = Path(filename).name

    filepath = save_dir / filename

    # Не перезаписываем файл с таким же именем
    if filepath.exists():
        stem = filepath.stem
        suffix = filepath.suffix

        counter = 1

        while filepath.exists():
            filepath = (
                save_dir /
                f"{stem}_{counter}{suffix}"
            )
            counter += 1

    with filepath.open("wb") as f:
        for chunk in response.iter_content(
            chunk_size=1024 * 256
        ):
            if chunk:
                f.write(chunk)

    print(f"Фото сохранено: {filepath}")