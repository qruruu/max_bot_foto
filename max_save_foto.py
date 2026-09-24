import os
import time
import json
import mimetypes
import urllib3
from pathlib import Path
from datetime import datetime

import requests

import os
from dotenv import load_dotenv

load_dotenv()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API = "https://platform-api2.max.ru"

# Лучше задать токен через переменную окружения MAX_BOT_TOKEN
TOKEN = os.getenv("MAX_BOT_TOKEN")

# 0 = сохранять фотографии из всех чатов, где работает бот.
# Когда узнаете ID нужной беседы, впишите его сюда.
TARGET_CHAT_ID = 0

SAVE_DIR = Path("MAX_PHOTOS")
MARKER_FILE = Path("max_marker.txt")

SAVE_DIR.mkdir(parents=True, exist_ok=True)

if not TOKEN:
    raise RuntimeError(
        "Не задан токен. Укажите переменную окружения MAX_BOT_TOKEN."
    )

HEADERS = {
    "Authorization": TOKEN,
    "Accept": "application/json",
}


def load_marker():
    if not MARKER_FILE.exists():
        return None

    value = MARKER_FILE.read_text(encoding="utf-8").strip()

    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def save_marker(marker):
    if marker is not None:
        MARKER_FILE.write_text(str(marker), encoding="utf-8")


def get_extension(response, url):
    content_type = response.headers.get("Content-Type", "")
    content_type = content_type.split(";")[0].strip()

    ext = mimetypes.guess_extension(content_type)

    if ext == ".jpe":
        ext = ".jpg"

    if not ext:
        path = url.split("?")[0]
        ext = Path(path).suffix

    if not ext or len(ext) > 6:
        ext = ".jpg"

    return ext


def download_photo(url, message, index):
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()

    ext = get_extension(response, url)

    timestamp_ms = message.get("timestamp", 0)

    if timestamp_ms:
        dt = datetime.fromtimestamp(timestamp_ms / 1000)
    else:
        dt = datetime.now()

    body = message.get("body") or {}
    message_id = body.get("mid", "unknown")

    filename = (
        f"{dt:%Y-%m-%d_%H-%M-%S}_"
        f"{message_id}_{index}{ext}"
    )

    filepath = SAVE_DIR / filename

    # Если такое фото уже было сохранено — повторно не качаем
    if filepath.exists():
        print(f"Уже существует: {filepath}")
        return

    with filepath.open("wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if chunk:
                f.write(chunk)

    print(f"Сохранено: {filepath}")


def process_message(message):
    recipient = message.get("recipient") or {}

    chat_id = recipient.get("chat_id")

    print(f"Сообщение из chat_id: {chat_id}")

    if TARGET_CHAT_ID and chat_id != TARGET_CHAT_ID:
        return

    body = message.get("body") or {}
    attachments = body.get("attachments") or []

    photo_number = 0

    for attachment in attachments:
        if attachment.get("type") != "image":
            continue

        payload = attachment.get("payload") or {}
        url = payload.get("url")

        if not url:
            print("У изображения нет URL:", attachment)
            continue

        photo_number += 1

        try:
            download_photo(url, message, photo_number)
        except Exception as e:
            print("Ошибка скачивания фотографии:", e)


def main():
    marker = load_marker()

    print("Бот запущен.")
    print("Фотографии будут сохраняться в:", SAVE_DIR.resolve())

    if TARGET_CHAT_ID:
        print("Слушаем chat_id:", TARGET_CHAT_ID)
    else:
        print("TARGET_CHAT_ID = 0 — слушаем все доступные беседы.")
        print("ID бесед будут выводиться на экран.")

    while True:
        params = {
            "timeout": 30,
            "limit": 100,
            "types": "message_created",
        }

        if marker is not None:
            params["marker"] = marker

        try:
            response = requests.get(
                f"{API}/updates",
                headers=HEADERS,
                params=params,
                timeout=40,
                verify=False,
            )

            response.raise_for_status()

            data = response.json()

            for update in data.get("updates", []):
                if update.get("update_type") == "message_created":
                    message = update.get("message")

                    if message:
                        process_message(message)

            new_marker = data.get("marker")

            if new_marker is not None:
                marker = new_marker
                save_marker(marker)

        except KeyboardInterrupt:
            print("\nБот остановлен.")
            break

        except requests.RequestException as e:
            print("Ошибка соединения с MAX:", e)
            time.sleep(5)

        except Exception as e:
            print("Ошибка:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
