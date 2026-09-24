import os

import requests
from dotenv import load_dotenv


load_dotenv()

API = "https://platform-api2.max.ru"
TOKEN = os.getenv("MAX_BOT_TOKEN")


HEADERS = {
    "Authorization": TOKEN,
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def send_message(chat_id, text):
    response = requests.post(
        f"{API}/messages",
        headers=HEADERS,
        params={
            "chat_id": chat_id,
        },
        json={
            "text": text,
        },
        timeout=30,
        verify=False,
    )

    response.raise_for_status()

    return response.json()