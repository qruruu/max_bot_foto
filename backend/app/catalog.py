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
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".bmp", ".heic", ".webp"}
ACCEPTED_STATUSES = {Status.ACCEPTED, Status.NEEDS_REVIEW}
REJECTED_STATUSES = {Status.REJECTED, Status.DUPLICATE, Status.FORWARDED}
