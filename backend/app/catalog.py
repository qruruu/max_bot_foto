from enum import StrEnum


class Status(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    ACCEPTED = "ACCEPTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"
    FORWARDED = "FORWARDED"
    ERROR = "ERROR"


class Role(StrEnum):
    ADMIN_OPERATOR = "ADMIN_OPERATOR"
    OPERATOR = "OPERATOR"


# Stable codes are used in DB, AI output, audit and export.
WORK_TYPES = {
    "DEICING_MANUAL": ("Распределение противогололедных материалов вручную", "противогололедная"),
    "SNOW_MANUAL": ("Уборка снега вручную", "снег_вручную"),
    "SNOW_MECHANICAL": ("Механизированная уборка снега", "снег_механизированный"),
    "SNOW_REMOVAL": ("Погрузка и вывоз снежных масс на полигон", "вывоз_снега"),
    "BIN_EMPTYING": ("Очистка урн от мусора", "урны"),
    "LAWN_LITTER": ("Уборка газонов от мусора", "мусор_газоны"),
    "DRAIN_CLEANING": ("Очистка дождеприемных колодцев от мокрого ила и грязи", "колодцы"),
    "METAL_CUTTING": ("Резка арматуры (труб)", "резка_арматуры"),
    "PLAYGROUND_MAINTENANCE": ("Содержание детских, спортивных, тренажерных площадок", "содержание_площадок"),
    "UNPAVED_LITTER": ("Уборка случайного мусора на проездах и площадях без покрытия", "мусор_проезды"),
    "SWEEPING": ("Подметание территории", "подметание"),
    "BIN_WASHING": ("Промывка урн с дезинфицирующими средствами", "мойка_урн"),
    "LAWN_RAKING": ("Уборка зеленых зон и газонов под грабли", "грабли"),
    "GREEN_CLEANING": ("Уборка зеленых зон и газонов", "уборка_газонов"),
    "GRASS_MOWING": ("Выкашивание травы", "выкашивание"),
    "PAVING_WASHING": ("Мойка брусчатки", "мойка_брусчатки"),
    "MAF_INSPECTION": ("Ежедневный осмотр МАФ", "осмотр_МАФ"),
    "PLAYGROUND_SNOW": ("Уборка снега на площадках после снегопада", "снег_площадки"),
    "PLAYGROUND_SUMMER": ("Летняя уборка площадок", "летняя_уборка"),
    "PLAYGROUND_MOWING": ("Покос зеленых зон площадок", "покос_площадки"),
    "FALLEN_TREE": ("Уборка упавшего дерева по заявке", "упавшее_дерево"),
    "CUT_GRASS_REMOVAL": ("Вывоз скошенной травы после покоса", "вывоз_травы"),
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".bmp", ".heic", ".webp"}
ACCEPTED_STATUSES = {Status.ACCEPTED, Status.NEEDS_REVIEW}
REJECTED_STATUSES = {Status.REJECTED, Status.DUPLICATE, Status.FORWARDED}
