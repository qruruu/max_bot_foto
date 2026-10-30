"""Appeal decisions are separate from the result of an executor's task."""

from typing import Literal

AppealStatus = Literal[
    "NEW", "IN_REVIEW", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "REJECTED", "CANCELLED",
    "RESOLVED", "DECLINED", "SPAM",
]
CloseStatus = Literal["RESOLVED", "DECLINED", "CANCELLED", "REJECTED"]
DECISION_STATUSES = frozenset({"RESOLVED", "DECLINED", "CANCELLED", "REJECTED"})
FINAL_STATUSES = frozenset({"RESOLVED", "DECLINED", "SPAM"})


def has_decision(appeal):
    return (appeal.status in {"RESOLVED", "DECLINED"}
            or appeal.status in {"CANCELLED", "REJECTED"} and appeal.resolved_at is not None)


def is_final(appeal):
    return appeal.status in FINAL_STATUSES or has_decision(appeal)
