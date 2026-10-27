"""Regression tests: behaviour that must not change while adding overdue filtering."""

from __future__ import annotations

from datetime import date

import pytest

from loanboard import Loan, LoanService

LOANS = (
    Loan("L-03", "M-1", "C", date(2026, 1, 20)),
    Loan("L-01", "M-1", "A", date(2026, 1, 10)),
    Loan("L-02", "M-2", "B", date(2026, 1, 10), date(2026, 1, 12)),
    Loan("L-04", "M-2", "D", date(2026, 1, 5), date(2026, 1, 6)),
)


def service() -> LoanService:
    return LoanService(LOANS)


def test_sorts_by_due_date_then_loan_id() -> None:
    assert [loan.loan_id for loan in service().list_loans()] == ["L-04", "L-01", "L-02", "L-03"]


def test_paging_runs_after_sorting() -> None:
    page = service().list_loans(limit=2, offset=1)
    assert [loan.loan_id for loan in page] == ["L-01", "L-02"]


def test_status_filters() -> None:
    assert [loan.loan_id for loan in service().list_loans(status="active")] == ["L-01", "L-03"]
    assert [loan.loan_id for loan in service().list_loans(status="returned")] == ["L-04", "L-02"]


def test_member_filter() -> None:
    assert [loan.loan_id for loan in service().list_loans(member_id="M-2")] == ["L-04", "L-02"]


def test_member_and_status_combine() -> None:
    assert [loan.loan_id for loan in service().list_loans(member_id="M-2", status="active")] == []


@pytest.mark.parametrize("status", ["lost", "ACTIVE", ""])
def test_invalid_status_raises(status: str) -> None:
    with pytest.raises(ValueError):
        service().list_loans(status=status)


@pytest.mark.parametrize(
    ("limit", "offset"),
    [(0, 0), (101, 0), (-1, 0), (50, -1), (True, 0), (50.0, 0)],
)
def test_invalid_paging_raises(limit: object, offset: object) -> None:
    with pytest.raises(ValueError):
        service().list_loans(limit=limit, offset=offset)  # type: ignore[arg-type]


def test_default_call_keeps_previous_behaviour() -> None:
    loans = service().list_loans()
    assert len(loans) == 4
    assert {loan.returned_on is None for loan in loans} == {True, False}
