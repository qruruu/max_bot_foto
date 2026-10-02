import os
from pathlib import Path


BASE_SAVE_DIR = Path("MAX_PHOTOS")

CHAT_1 = os.getenv("chat_1")
CHAT_2 = os.getenv("chat_2")

CHAT_NAMES = {
    CHAT_1: "Ручная_уборка",
    CHAT_2: "Механическая_уборка",
}

FAIL_FILE = "НЕПРИНЯТЫЕ_ФОТО"

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".tif",
    ".tiff",
    ".bmp",
    ".heic",
    ".webp",
}

