"""Loan listing rules described by ``specs/loans.md``.

Snapshot of ``app/loanboard/service.py`` before SPEC-LOAN-004 was implemented.
``overdue_only`` and ``as_of`` are accepted so callers can already pass the new
arguments, but the filter itself is not implemented yet.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from .models import Loan

_STATUSES = frozenset({"active", "returned"})
_MIN_LIMIT = 1
_MAX_LIMIT = 100


class LoanService:
    """Read-only view over a fixed set of loans."""

    def __init__(self, loans: Iterable[Loan]) -> None:
        self._loans = tuple(loans)

    def list_loans(
        self,
        *,
        member_id: str | None = None,
        status: str | None = None,
        overdue_only: bool = False,
        as_of: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Loan]:
        """Return loans filtered by member, status and (not yet) overdue state."""

        _validate_status(status)
        _validate_paging(limit, offset)
        if not isinstance(overdue_only, bool):
            raise ValueError("overdue_only must be a boolean")
        if as_of is not None and not isinstance(as_of, date):
            raise ValueError("as_of must be a date")

        selected: list[Loan] = []
        for loan in self._loans:
            if member_id is not None and loan.member_id != member_id:
                continue
            if status == "active" and loan.returned_on is not None:
                continue
            if status == "returned" and loan.returned_on is None:
                continue
            selected.append(loan)

        selected.sort(key=lambda loan: (loan.due_date, loan.loan_id))
        return selected[offset : offset + limit]


def _validate_status(status: str | None) -> None:
    if status is not None and status not in _STATUSES:
        raise ValueError(f"status must be one of {sorted(_STATUSES)} or None")


def _validate_paging(limit: int, offset: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if not _MIN_LIMIT <= limit <= _MAX_LIMIT:
        raise ValueError(f"limit must be between {_MIN_LIMIT} and {_MAX_LIMIT}")
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ValueError("offset must be an integer")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0")
