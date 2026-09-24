from pathlib import Path

import requests


def download_file(url, original_filename, save_dir):
    response = requests.get(
        url,
        stream=True,
        timeout=60,
        verify=False,
    )

    response.raise_for_status()

    # Защита от путей вроде ../../file.jpg
    safe_filename = Path(original_filename).name

    save_dir.mkdir(parents=True, exist_ok=True)

    filepath = save_dir / safe_filename

    if filepath.exists():
        stem = filepath.stem
        suffix = filepath.suffix

        counter = 1

        while filepath.exists():
            filepath = save_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    with filepath.open("wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if chunk:
                f.write(chunk)

    print(f"Файл сохранён: {filepath}")

    return filepath