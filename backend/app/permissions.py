"""Function permissions, shared defaults and prerequisites for operator accounts."""

from enum import StrEnum


class Permission(StrEnum):
    REPORTS_VIEW = "reports_view"
    PHOTOS_VIEW = "photos_view"
    PHOTOS_SORT = "photos_sort"
    ORIGINALS_VIEW = "originals_view"
    PHOTOS_EDIT = "photos_edit"
    SPAM_VIEW = "spam_view"
    REPORTS_EXPORT = "reports_export"
    PREVIEWS_REMOVE = "previews_remove"
    DISTRICTS_VIEW = "districts_view"
    DISTRICTS_EDIT = "districts_edit"
    CHATS_MANAGE = "chats_manage"
    AUDIT_VIEW = "audit_view"
    JOBS_MANAGE = "jobs_manage"
    EXCHANGE_MANAGE = "exchange_manage"
    LEARNING_MANAGE = "learning_manage"
    NEWS_VIEW = "news_view"
    DAYS_REVIEW = "days_review"
    DAILY_REPORTS_VIEW = "daily_reports_view"
    DAILY_REPORTS_EDIT = "daily_reports_edit"
    DAILY_REPORTS_CONFIGURE = "daily_reports_configure"


PERMISSIONS = {
    Permission.DAILY_REPORTS_VIEW: ("Просмотр ежедневных отчётов по контрактам", "Отчётность по контрактам", ()),
    Permission.DAILY_REPORTS_EDIT: (
        "Составление и утверждение ежедневных отчётов", "Отчётность по контрактам", (Permission.DAILY_REPORTS_VIEW,),
    ),
    Permission.DAILY_REPORTS_CONFIGURE: (
        "Настройка реквизитов, контрактов и календаря работ", "Отчётность по контрактам", (Permission.DAILY_REPORTS_VIEW,),
    ),
    Permission.REPORTS_VIEW: ("Обзор и отчёты", "Фотографии и отчёты", ()),
    Permission.PHOTOS_VIEW: ("Просмотр фотографий", "Фотографии и отчёты", ()),
    Permission.PHOTOS_SORT: (
        "Изменение сортировки фотографий",
        "Фотографии и отчёты",
        (Permission.PHOTOS_VIEW,),
    ),
    Permission.ORIGINALS_VIEW: (
        "Открытие и скачивание оригиналов",
        "Фотографии и отчёты",
        (Permission.PHOTOS_VIEW,),
    ),
    Permission.PHOTOS_EDIT: (
        "Проверка, изменение и повторная обработка фото",
        "Фотографии и отчёты",
        (Permission.PHOTOS_VIEW,),
    ),
    Permission.DAYS_REVIEW: (
        "Проверка и закрытие дней",
        "Фотографии и отчёты",
        (Permission.PHOTOS_VIEW, Permission.PHOTOS_EDIT, Permission.REPORTS_VIEW),
    ),
    Permission.SPAM_VIEW: (
        "Просмотр раздела «Спам»",
        "Фотографии и отчёты",
        (Permission.PHOTOS_VIEW,),
    ),
    Permission.REPORTS_EXPORT: (
        "Скачивание Excel",
        "Фотографии и отчёты",
        (Permission.PHOTOS_VIEW, Permission.REPORTS_VIEW),
    ),
    Permission.PREVIEWS_REMOVE: (
        "Удаление превью без оригинала",
        "Фотографии и отчёты",
        (Permission.PHOTOS_VIEW,),
    ),
    Permission.DISTRICTS_VIEW: ("Просмотр карты микрорайонов", "Настройка сервиса", ()),
    Permission.DISTRICTS_EDIT: (
        "Изменение границ микрорайонов",
        "Настройка сервиса",
        (Permission.DISTRICTS_VIEW,),
    ),
    Permission.CHATS_MANAGE: ("Добавление и настройка чатов MAX", "Настройка сервиса", ()),
    Permission.AUDIT_VIEW: ("Журнал действий", "Настройка сервиса", ()),
    Permission.JOBS_MANAGE: ("Очередь обработки и повтор задач", "Настройка сервиса", ()),
    Permission.EXCHANGE_MANAGE: ("Обмен с АРМ и структура папок", "Настройка сервиса", ()),
    Permission.LEARNING_MANAGE: ("Обучение нейросети", "Настройка сервиса", ()),
    Permission.NEWS_VIEW: ("Просмотр новостей", "Информация", ()),
}

# Preserve the capabilities of operators created before per-function access was introduced.
DEFAULT_OPERATOR_PERMISSIONS = [
    str(p)
    for p in (
        Permission.REPORTS_VIEW,
        Permission.PHOTOS_VIEW,
        Permission.ORIGINALS_VIEW,
        Permission.PHOTOS_EDIT,
        Permission.SPAM_VIEW,
        Permission.REPORTS_EXPORT,
        Permission.PREVIEWS_REMOVE,
        Permission.DISTRICTS_VIEW,
    )
]


def validate_permissions(values):
    selected = set(values)
    for code in selected:
        missing = set(PERMISSIONS[code][2]) - selected
        if missing:
            required = ", ".join(PERMISSIONS[p][0] for p in PERMISSIONS if p in missing)
            raise ValueError(f"«{PERMISSIONS[code][0]}» требует доступа: {required}")
    return [code for code in PERMISSIONS if code in selected]


def effective_permissions(user):
    if user.role == "ADMIN_OPERATOR":
        return [str(code) for code in PERMISSIONS]
    selected = set(user.permissions or []) & PERMISSIONS.keys()
    # Fail closed for a malformed stored set; normal writes are validated by the schemas.
    selected = {code for code in selected if set(PERMISSIONS[code][2]) <= selected}
    return [str(code) for code in PERMISSIONS if code in selected]


def has_permission(user, code):
    return code in effective_permissions(user)


def permission_catalog():
    return [
        {
            "code": str(code),
            "name": name,
            "group": group,
            "requires": list(requires),
            "default_operator": code in DEFAULT_OPERATOR_PERMISSIONS,
        }
        for code, (name, group, requires) in PERMISSIONS.items()
    ]


def job_permission(kind):
    if kind in {"PUBLISH", "EXCHANGE_GC", "ARCHIVE_ORGANIZE"}:
        return Permission.EXCHANGE_MANAGE
    if kind == "TRAIN":
        return Permission.LEARNING_MANAGE
    if kind == "REGEO":
        return Permission.DISTRICTS_EDIT
    if kind == "REMOVE_PREVIEW":
        return Permission.PREVIEWS_REMOVE
    if kind in {"BATCH", "SYNC", "REPLY"}:
        return Permission.PHOTOS_EDIT
    return None


def can_retry_job(user, kind):
    required = job_permission(kind)
    return user.role == "ADMIN_OPERATOR" or (required is not None and has_permission(user, required))
