import os
import time

import requests
import urllib3
from dotenv import load_dotenv

from handlers.message import process_message
from marker import load_marker, save_marker

load_dotenv()

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


API = "https://platform-api2.max.ru"

TOKEN = os.getenv("MAX_BOT_TOKEN")


if not TOKEN:
    raise RuntimeError(
        "Не задан MAX_BOT_TOKEN в файле .env"
    )


HEADERS = {
    # Подготавливаем токен бота для авторизации в MAX API
    "Authorization": TOKEN,
    # Сообщаем API, что ожидаем ответ в формате JSON
    "Accept": "application/json",
}



def main():
    # Загружаем маркер из файла, если он существует
    marker = load_marker()

    print("Бот запущен.")
    print("Ожидаем новые сообщения из MAX...")

    # Бесконечный цикл 
    while True:
        params = {
            # Макс ждет максимум 30 секунд, а потом опять отправляет запрос
            "timeout": 30,
            # Максимальное количество событий за один раз
            "limit": 100,
            # Типы обновлений, которые мы хотим получать
            "types": "message_created",
        }

        # Если маркер существует, добавляем его в параметры запроса
        if marker is not None:
            params["marker"] = marker

        """Попробуй выполнить код ниже.
           Если будет ошибка — программа не упадёт сразу,
            ошибку потом поймает except."""
        try:
            #Отправь GET-запрос и сохрани ответ в переменную response
            response = requests.get(
                # Вот сюда
                f"{API}/updates",
                # передали эти данные в запросе
                headers=HEADERS,
                params=params,
                # Ждём ответа от сервера не более 40 секунд
                timeout=40,
                # Игнорируем проверку SSL-сертификата
                verify=False,
            )

            # Проверяем, что запрос прошёл успешно.
            response.raise_for_status()

            # Получаем данные из ответа в формате JSON
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