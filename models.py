from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Dict, Optional


@dataclass
class Attendance:
    id: Optional[int]
    employee_id: int
    attendance_date: date
    check_in: Optional[time]
    check_out: Optional[time]
    status: str

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Attendance":
        return cls(
            id=row.get("id"),
            employee_id=row["employee_id"],
            attendance_date=row["date"],
            check_in=row.get("check_in_time"),
            check_out=row.get("check_out_time"),
            status=row["status"],
        )


@dataclass
class Leave:
    id: Optional[int]
    employee_id: int
    leave_type: str
    start_date: date
    end_date: date
    reason: str
    status: str = "pending"
    applied_on: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Leave":
        return cls(
            id=row.get("id"),
            employee_id=row["employee_id"],
            leave_type=row["leave_type"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            reason=row["reason"],
            status=row.get("status", "pending"),
            applied_on=row.get("applied_on"),
        )


@dataclass
class LeadPipeline:
    id: int
    company_name: str
    service: Optional[str]
    status: str
    pending_department: str
    total_fee: float = 0
    govt_fee: float = 0
    professional_fee: float = 0
    paid_amount: float = 0
    pending_amount: float = 0

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "LeadPipeline":
        return cls(
            id=row["id"],
            company_name=row.get("company_name") or "",
            service=row.get("service"),
            status=row.get("status") or "",
            pending_department=row.get("pending_department") or "",
            total_fee=float(row.get("total_fee") or 0),
            govt_fee=float(row.get("govt_fee") or 0),
            professional_fee=float(row.get("professional_fee") or 0),
            paid_amount=float(row.get("paid_amount") or 0),
            pending_amount=float(row.get("pending_amount") or 0),
        )
