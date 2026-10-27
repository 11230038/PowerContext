"""Runnable entry point for the loan-listing business project."""

from __future__ import annotations

import argparse
import json
from datetime import date

from .models import Loan
from .service import LoanService

DEMO_LOANS = (
    Loan("L-1001", "M-01", "Designing Data-Intensive Applications", date(2026, 1, 10)),
    Loan("L-1002", "M-01", "Refactoring", date(2026, 1, 20)),
    Loan("L-1003", "M-02", "The Pragmatic Programmer", date(2026, 1, 8), date(2026, 1, 9)),
    Loan("L-1004", "M-02", "Domain-Driven Design", date(2026, 1, 12)),
    Loan("L-1005", "M-03", "Release It!", date(2026, 1, 25)),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List library loans")
    parser.add_argument("--member", dest="member_id", default=None)
    parser.add_argument("--status", choices=("active", "returned"), default=None)
    parser.add_argument("--overdue-only", action="store_true")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 1, 15))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args(argv)

    service = LoanService(DEMO_LOANS)
    loans = service.list_loans(
        member_id=args.member_id,
        status=args.status,
        overdue_only=args.overdue_only,
        as_of=args.as_of,
        limit=args.limit,
        offset=args.offset,
    )
    print(json.dumps({"count": len(loans), "loans": [loan.as_dict() for loan in loans]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
