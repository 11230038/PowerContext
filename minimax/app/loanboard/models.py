"""Data model for the loan-listing business project."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Loan:
    """One book loan.

    ``returned_on`` is ``None`` while the loan is still active.
    """

    loan_id: str
    member_id: str
    title: str
    due_date: date
    returned_on: date | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "loan_id": self.loan_id,
            "member_id": self.member_id,
            "title": self.title,
            "due_date": self.due_date.isoformat(),
            "returned_on": None if self.returned_on is None else self.returned_on.isoformat(),
        }
