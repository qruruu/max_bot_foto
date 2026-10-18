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
    SPAM = "SPAM"


class Role(StrEnum):
    ADMIN_OPERATOR = "ADMIN_OPERATOR"
    OPERATOR = "OPERATOR"


# Stable internal codes; display labels and filenames use only the sheet's short markings.
# Source: 19aE4mOlMkGM8F5_0Bic_7euY-qgmGRlJnJzHNhugHVs, gid=1922338105, column F.
WORK_TYPES = {
    "DEICING_MANUAL": ("ПГМ", "ПГМ"),
    "SNOW_MANUAL": ("ПОДХОДЫ", "ПОДХОДЫ"),
    "BIN_EMPTYING": ("УРНЫ", "УРНЫ"),
    "LAWN_LITTER": ("МУСОР_ГАЗОН", "МУСОР_ГАЗОН"),
    "DRAIN_CLEANING": ("КОЛОДЦЫ", "КОЛОДЦЫ"),
    "METAL_CUTTING": ("АРМАТУРА", "АРМАТУРА"),
    "PLAYGROUND_MAINTENANCE": ("ПЛОЩАДКИ", "ПЛОЩАДКИ"),
    "UNPAVED_LITTER": ("СЛУЧ_МУСОР", "СЛУЧ_МУСОР"),
    "SWEEPING": ("ПОДМЕТАНИЕ", "ПОДМЕТАНИЕ"),
    "BIN_WASHING": ("МОЙКА_УРН", "МОЙКА_УРН"),
    "LAWN_RAKING": ("ГРАБЛИ", "ГРАБЛИ"),
    "GREEN_CLEANING": ("ГАЗОН", "ГАЗОН"),
    "GRASS_MOWING": ("ПОКОС", "ПОКОС"),
    "PAVING_WASHING": ("БРУСЧ_МОЙКА", "БРУСЧ_МОЙКА"),
    "SNOW_MECHANICAL": ("МЕХ_СНЕГ", "МЕХ_СНЕГ"),
    "SNOW_REMOVAL": ("ВЫВОЗ_СНЕГА", "ВЫВОЗ_СНЕГА"),
}
# UI order is independent of the stable class indices used by trained models.
_PRIORITY_WORK_TYPES = (
    "BIN_EMPTYING", "PLAYGROUND_MAINTENANCE", "SNOW_MANUAL", "DEICING_MANUAL", "GREEN_CLEANING",
)
WORK_TYPE_DISPLAY_ORDER = _PRIORITY_WORK_TYPES + tuple(
    code for code in WORK_TYPES if code not in _PRIORITY_WORK_TYPES
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".bmp", ".heic", ".webp"}
ACCEPTED_STATUSES = {Status.ACCEPTED, Status.NEEDS_REVIEW}
REJECTED_STATUSES = {Status.REJECTED, Status.DUPLICATE, Status.FORWARDED}
NON_WORK_STATUSES = {Status.DUPLICATE, Status.FORWARDED, Status.SPAM}


def work_type_label(code: str | None, is_defect: bool = False, catalog=None) -> str | None:
    catalog = WORK_TYPES if catalog is None else catalog
    name = catalog[code][0] if code in catalog else code
    return f"{name or 'Не определён'} · НЕИСПРАВНОСТЬ" if is_defect else name
