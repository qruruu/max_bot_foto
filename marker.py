from pathlib import Path


MARKER_FILE = Path("max_marker.txt")


def load_marker():
    # Если файла с маркером нет — возвращаем None
    if not MARKER_FILE.exists():
        return None

    # Читаем маркер из файла
    value = MARKER_FILE.read_text(
        encoding="utf-8"
    ).strip()

    # Если файл пустой — возвращаем None
    if not value:
        return None

    try:
        # Возвращаем маркер как число
        return int(value)
    except ValueError:
        return None


def save_marker(marker):
    # Сохраняем маркер в файл
    if marker is not None:
        MARKER_FILE.write_text(
            str(marker),
            encoding="utf-8",
        )