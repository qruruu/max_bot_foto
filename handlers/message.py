from datetime import datetime
from pathlib import Path

from config import (
    BASE_SAVE_DIR,
    CHAT_NAMES,
    IMAGE_EXTENSIONS,
    FAIL_FILE,
)

from downloaders.image import download_photo
from downloaders.file import download_file
from services.max_api import send_message

#создает папку для сохранения фото, если она не существует. Если не существует то не создает.
def save_in_dir(chat_id):
    chat_name = CHAT_NAMES.get(chat_id)

    if not chat_name:
        return None

    #Получаем сегодняшнюю дату в формате "YYYY-MM-DD"
    today = datetime.now().strftime("%Y-%m-%d")

    #Создаем путь к папке для сохранения фото, используя базовую директорию, сегодняшнюю дату и имя чата
    save_dir = BASE_SAVE_DIR / today / chat_name

    #Создаем папку, если она не существует, включая все родительские директории
    save_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return save_dir

#создает папку для сохранения отклоненных фото, если она не существует. Если не существует то не создает.
def save_dir_fail(chat_id):
    chat_name = CHAT_NAMES.get(chat_id)

    if not chat_name:
        return None

    today = datetime.now().strftime("%Y-%m-%d")

    #Создаем путь к папке для сохранения отклоненных фото, используя базовую директорию, сегодняшнюю дату, поддиректорию "НЕПРИНЯТЫЕ_ФОТО" и имя чата
    save_dir = (
        BASE_SAVE_DIR
        / today
        / FAIL_FILE
        / chat_name
    )

    #Создаем папку, если она не существует, включая все родительские директории
    save_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return save_dir


#
def process_message(message):
    # Получаем идентификатор чата из сообщения если он есть, иначе используем пустой словарь
    recipient = message.get("recipient") or {}
    # Получаем идентификатор чата из словаря recipient, если он есть
    chat_id = recipient.get("chat_id")

    print(f"Сообщение из chat_id: {chat_id}")

    # Проверяем, настроен ли этот чат
    if chat_id not in CHAT_NAMES:
        print(
            f"Чат {chat_id} не настроен — пропускаем"
        )
        return

    # Получаем тело сообщения из словаря message, если оно есть, иначе используем пустой словарь
    body = message.get("body") or {}
    attachments = body.get("attachments") or []

    # Вытаскиваем вложения из сообщения и обрабатываем их
    for attachment in attachments:
        attachment_type = attachment.get("type")
        payload = attachment.get("payload") or {}

        # ---------------------------------
        # Пользователь отправил обычное фото
        # ---------------------------------

        if attachment_type == "image":
            url = payload.get("url")

            if not url:
                print("У изображения нет URL")
                continue

            rejected_dir = save_dir_fail(
                chat_id
            )

            try:
                # Сохраняем только как резервную копию
                download_photo(
                    url,
                    attachment,
                    rejected_dir,
                )

                print(
                    "Фото помещено в НЕПРИНЯТЫЕ_ФОТО"
                )

            except Exception as e:
                print(
                    "Ошибка резервного сохранения фото:",
                    e,
                )

            try:
                send_message(
                    chat_id,
                    "❌ Фото не сохранено.\n"
                    "Отправьте снимок файлом.",
                )

            except Exception as e:
                print(
                    "Ошибка отправки сообщения:",
                    e,
                )

        # ---------------------------------
        # Пользователь отправил файл
        # ---------------------------------

        elif attachment_type == "file":
            filename = attachment.get(
                "filename",
                "",
            )

            extension = Path(
                filename
            ).suffix.lower()

            # Нас интересуют только изображения
            if extension not in IMAGE_EXTENSIONS:
                print(
                    f"Пропускаем не изображение: "
                    f"{filename}"
                )
                continue

            url = payload.get("url")

            if not url:
                print(
                    f"У файла {filename} нет URL"
                )
                continue

            save_dir = save_in_dir(
                chat_id
            )

            try:
                saved_path = download_file(
                    url,
                    filename,
                    save_dir,
                )

                print(
                    f"Снимок сохранён: {saved_path}"
                )

                send_message(
                    chat_id,
                    f"✅ Снимок сохранён",
                )

            except Exception as e:
                print(
                    f"Ошибка скачивания файла "
                    f"{filename}: {e}"
                )

                try:
                    send_message(
                        chat_id,
                        "❌ Не удалось сохранить снимок.",
                    )
                except Exception:
                    pass