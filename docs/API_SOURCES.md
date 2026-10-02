# Официальные API, проверка 30.09–02.10.2026

## MAX

- [Webhook: POST /subscriptions](https://dev.max.ru/docs-api/methods/POST/subscriptions): `platform-api2.max.ru`, заголовок Authorization, `url`, `update_types`, `secret`; HTTPS 443; входящий `X-Max-Bot-Api-Secret`; возврат 200 после надёжной записи события.
- [Message](https://dev.max.ru/docs-api/objects/Message): `recipient.chat_id`, `sender`, `timestamp` (миллисекунды), `body`, `link` (ответ/пересылка). Тип `forward` проверяется в `message.link`, не по тексту.
- [Отправка сообщений](https://dev.max.ru/docs-api/methods/POST/messages): `POST /messages?chat_id=...`, `text`, `link: {type: reply, mid: ...}`; максимум два сообщения в секунду в один чат.
- [Long polling](https://dev.max.ru/docs-api/methods/GET/updates): не выбран для production; доставка в новом сервисе через webhook.
- [Официальная схема MAX Bot API](https://github.com/max-messenger-bot/max-bot-api-schemas): поля image/file attachments, URL в payload, имя файла в file attachment; схема — дополнительная справка, актуальный домен взят из живой документации MAX.

Вложения одного сообщения составляют пакет. Система не придумывает `album_id`, если официальное событие его не предоставляет.

## Яндекс.Диск

- [REST API](https://yandex.com/dev/disk-api/doc/en/): OAuth, ресурсы, создание папок, перемещение.
- [Загрузка](https://yandex.com/dev/disk-api/doc/en/reference/upload): GET `/v1/disk/resources/upload?path=...&overwrite=false` → подписанный `href` → PUT исходных байтов. OAuth не передаётся на storage-host. 202 ещё не подтверждает готовность ресурса.
- [Интерактивная спецификация API](https://yandex.ru/dev/disk/poligon/): `/resources`, `/resources/move`, `/resources/download`, `/operations/{id}`.

Адаптер учитывает асинхронное перемещение и сверяет метаданные SHA-256 до фиксации нового пути. Несколько прямых страниц документации перемещения/создания папок при проверке возвращали ошибку; поэтому эти HTTP-контракты дополнительно покрыты изолированными тестами. Сквозной вызов с пользовательским OAuth-токеном остаётся пунктом приёмки.

## Яндекс.Карты

- [JavaScript API 2.1](https://yandex.ru/dev/jsapi-v2-1/doc/ru/): подключение с ключом.
- [Редактор полигонов](https://yandex.ru/dev/jsapi-v2-1/doc/ru/v2-1/examples/cases/polygonEditor): рисование и изменение вершин.
- [Параметры загрузки](https://yandex.ru/dev/jsapi-v2-1/doc/ru/v2-1/dg/concepts/load): `coordorder=longlat`, `lang=ru_RU`, `csp=true`.
- [Версии](https://yandex.ru/dev/jsapi-v2-1/doc/ru/v2-1/versions/): подключена фиксированная версия 2.1.79.

## Собственная локальная нейросеть

- [Torchvision ResNet18](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.resnet18.html): архитектура и общие ImageNet-веса.
- [Transfer learning](https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html): обучение классификатора на своих размеченных изображениях.

Внешний Vision API удалён по уточнению от 02.10.2026. Классификация выполняется в PyTorch на сервере; обучение использует подтверждения оператора. Из интернета скачиваются только общие базовые веса. Проверка TLS для MAX выключена по тому же уточнению пользователя.
