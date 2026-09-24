import os
import time
from pathlib import Path

import requests
import urllib3
from dotenv import load_dotenv

from handlers.message import process_message


load_dotenv()

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


API = "https://platform-api2.max.ru"

TOKEN = os.getenv("MAX_BOT_TOKEN")

MARKER_FILE = Path("max_marker.txt")


if not TOKEN:
    raise RuntimeError(
        "Не задан MAX_BOT_TOKEN в файле .env"
    )


HEADERS = {
    "Authorization": TOKEN,
    "Accept": "application/json",
}


def load_marker():
    if not MARKER_FILE.exists():
        return None

    value = MARKER_FILE.read_text(
        encoding="utf-8"
    ).strip()

    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def save_marker(marker):
    if marker is not None:
        MARKER_FILE.write_text(
            str(marker),
            encoding="utf-8",
        )


def main():
    marker = load_marker()

    print("Бот запущен.")
    print("Ожидаем новые сообщения из MAX...")

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
                if update.get("update_type") != "message_created":
                    continue

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
            print(
                "Ошибка соединения с MAX:",
                e,
            )
            time.sleep(5)

        except Exception as e:
            print(
                "Неожиданная ошибка:",
                e,
            )
            time.sleep(5)


if __name__ == "__main__":
    main()