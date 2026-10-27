"""Target tests for SPEC-LOAN-004: the overdue-only filter."""

from __future__ import annotations

from datetime import date

import pytest

from loanboard import Loan, LoanService

AS_OF = date(2026, 1, 15)

LOANS = (
    Loan("L-01", "M-1", "A", date(2026, 1, 10)),
    Loan("L-02", "M-1", "B", date(2026, 1, 15)),
    Loan("L-03", "M-1", "C", date(2026, 1, 20)),
    Loan("L-04", "M-2", "D", date(2026, 1, 5), date(2026, 1, 6)),
    Loan("L-05", "M-2", "E", date(2026, 1, 1)),
)


def service() -> LoanService:
    return LoanService(LOANS)


def test_overdue_only_returns_active_loans_due_before_as_of() -> None:
    loans = service().list_loans(overdue_only=True, as_of=AS_OF)
    assert [loan.loan_id for loan in loans] == ["L-05", "L-01"]


def test_loan_due_today_is_not_overdue() -> None:
    loans = service().list_loans(overdue_only=True, as_of=AS_OF)
    assert "L-02" not in {loan.loan_id for loan in loans}


def test_returned_loan_is_never_overdue() -> None:
    loans = service().list_loans(overdue_only=True, as_of=AS_OF)
    assert "L-04" not in {loan.loan_id for loan in loans}


def test_overdue_filter_combines_with_member() -> None:
    loans = service().list_loans(member_id="M-1", overdue_only=True, as_of=AS_OF)
    assert [loan.loan_id for loan in loans] == ["L-01"]


def test_overdue_filter_combines_with_returned_status() -> None:
    assert service().list_loans(status="returned", overdue_only=True, as_of=AS_OF) == []


def test_overdue_false_keeps_all_loans() -> None:
    loans = service().list_loans(overdue_only=False, as_of=AS_OF)
    assert [loan.loan_id for loan in loans] == ["L-05", "L-04", "L-01", "L-02", "L-03"]


def test_as_of_changes_the_cutoff() -> None:
    assert [loan.loan_id for loan in service().list_loans(overdue_only=True, as_of=date(2026, 1, 11))] == [
        "L-05",
        "L-01",
    ]
    with pytest.raises(ValueError):
        service().list_loans(overdue_only=True, as_of=date(2026, 1, 15), limit=0)
