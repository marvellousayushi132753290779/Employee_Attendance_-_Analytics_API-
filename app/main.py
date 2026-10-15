"""
Employee Attendance & Analytics API

FastAPI application conforming to openapi.yaml and DATA_MODEL.md.
All business rules R1-R10 are strictly implemented.
"""
import calendar
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import os
import re
from typing import Any, Optional

from pathlib import Path as FilePath

from bson import json_util
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "attendance_db")

client = MongoClient(MONGO_URI, tz_aware=True)
db = client[MONGO_DB]

IST = timezone(timedelta(hours=5, minutes=30))
MIN_EPOCH_MS = 100000000000
MAX_EPOCH_MS = 4102444800000


def create_indexes():
    """Create all required indexes idempotently at startup."""
    # Employees indexes
    db.employees.create_index([("emp_code", 1)], unique=True)
    db.employees.create_index([("department", 1), ("joined_on", 1)])
    db.employees.create_index([("joined_on", 1), ("department", 1)])

    # Attendance logs indexes
    db.attendance_logs.create_index([("emp_code", 1), ("date", 1)], unique=True)
    db.attendance_logs.create_index([("date", -1), ("emp_code", 1)])
    db.attendance_logs.create_index([("emp_code", 1), ("punch_in", -1)])
    db.attendance_logs.create_index([("date", 1), ("late_minutes", 1), ("emp_code", 1)])
    db.attendance_logs.create_index([("date", 1), ("emp_code", 1)])
    db.attendance_logs.create_index([("emp_code", 1), ("date", 1), ("status", 1)])


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_indexes()
    yield


app = FastAPI(
    title="Employee Attendance & Analytics API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/", include_in_schema=False)
    def serve_frontend():
        return FileResponse(os.path.join(frontend_dir, "index.html"))


@app.post("/admin/seed", include_in_schema=False)
def seed_sample_database():
    """Seed or reset sample data from sample_data/."""
    sample_dir = FilePath(__file__).parent.parent / "sample_data"
    opts = json_util.JSONOptions(tz_aware=True)
    counts = {}
    for name in ("employees", "attendance_logs"):
        p = sample_dir / f"{name}.json"
        if p.exists():
            docs = json_util.loads(p.read_text(encoding="utf-8"), json_options=opts)
            db[name].delete_many({})
            if docs:
                db[name].insert_many(docs)
            counts[name] = len(docs)
    create_indexes()
    return {"status": "ok", "seeded": counts}


# --------------------------------------------------------------------------- #
# Domain Helpers & Business Rules (R1 - R10)
# --------------------------------------------------------------------------- #
def validate_epoch_ms(val: Any) -> int:
    """Validate and truncate an instant in epoch milliseconds to whole seconds."""
    if isinstance(val, bool) or not isinstance(val, int):
        raise HTTPException(status_code=422, detail="Instant must be an integer count of epoch milliseconds")
    if not (MIN_EPOCH_MS <= val <= MAX_EPOCH_MS):
        raise HTTPException(status_code=422, detail="Epoch milliseconds out of range")
    # Truncate to whole seconds per R1
    return (val // 1000) * 1000


def to_epoch_ms(dt: Optional[datetime]) -> Optional[int]:
    """Convert a datetime to epoch milliseconds truncated to whole seconds."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ms = int(dt.timestamp() * 1000)
    return (ms // 1000) * 1000


def ms_to_datetime_utc(ms: int) -> datetime:
    """Convert epoch milliseconds to timezone-aware UTC datetime."""
    ms_truncated = (ms // 1000) * 1000
    return datetime.fromtimestamp(ms_truncated / 1000, tz=timezone.utc)


def current_server_time_truncated() -> tuple[int, datetime]:
    """Return current server time as (epoch_ms, datetime_utc), truncated to seconds."""
    now_utc = datetime.now(timezone.utc)
    ms = int(now_utc.timestamp() * 1000)
    ms_truncated = (ms // 1000) * 1000
    return ms_truncated, datetime.fromtimestamp(ms_truncated / 1000, tz=timezone.utc)


def round_half_up(val: Optional[float | Decimal], places: int = 2) -> Optional[float]:
    """Round a number half-up (R8)."""
    if val is None:
        return None
    d = Decimal(str(val))
    q = Decimal("10") ** -places
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def get_attendance_date(punch_in_utc: datetime, shift_start: str, shift_end: str) -> str:
    """
    R1 Time zone and attendance date.
    Shift times and attendance dates are IST (UTC+05:30).
    A record's date is the IST calendar date of its punch_in instant.
    Exception - overnight shifts (shift_end <= shift_start): a punch-in whose IST
    time is earlier than shift_end belongs to the shift that started the previous day.
    """
    punch_in_ist = punch_in_utc.astimezone(IST)
    if shift_end <= shift_start:
        end_h, end_m = map(int, shift_end.split(":"))
        if punch_in_ist.time() < time(end_h, end_m):
            return (punch_in_ist.date() - timedelta(days=1)).isoformat()
    return punch_in_ist.date().isoformat()


def compute_late_minutes(punch_in_utc: datetime, shift_start: str, attendance_date_str: str) -> int:
    """
    R2 Late. Grace period is 10 minutes.
    A punch-in is late only if strictly more than 10:00 (600 seconds) after shift_start.
    When late, late_minutes = whole minutes (floor) elapsed since shift_start. Otherwise 0.
    """
    punch_in_ist = punch_in_utc.astimezone(IST)
    d = date.fromisoformat(attendance_date_str)
    start_h, start_m = map(int, shift_start.split(":"))
    shift_start_dt = datetime(d.year, d.month, d.day, start_h, start_m, 0, tzinfo=IST)
    diff_sec = (punch_in_ist - shift_start_dt).total_seconds()
    if diff_sec > 600:
        return int(diff_sec // 60)
    return 0


def compute_overtime_minutes(punch_out_utc: datetime, shift_start: str, shift_end: str, attendance_date_str: str) -> int:
    """
    R3 Overtime. Whole minutes (floor) between shift_end and punch_out,
    counted only when that is >= 30; otherwise 0.
    """
    punch_out_ist = punch_out_utc.astimezone(IST)
    d = date.fromisoformat(attendance_date_str)
    end_h, end_m = map(int, shift_end.split(":"))
    shift_end_dt = datetime(d.year, d.month, d.day, end_h, end_m, 0, tzinfo=IST)
    if shift_end <= shift_start:
        shift_end_dt += timedelta(days=1)
    diff_sec = (punch_out_ist - shift_end_dt).total_seconds()
    ot_min = int(diff_sec // 60)
    return ot_min if ot_min >= 30 else 0


def compute_work_hours(punch_in_utc: datetime, punch_out_utc: datetime) -> float:
    """
    R4 Work hours. (punch_out - punch_in) in seconds / 3600,
    rounded to 2 decimals half-up.
    """
    diff_sec = int((punch_out_utc - punch_in_utc).total_seconds())
    val = Decimal(diff_sec) / Decimal(3600)
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_half_day(work_hours: Optional[float]) -> bool:
    """
    R5 Half day. After punch-out, half_day = true when rounded work_hours < 4.50.
    """
    if work_hours is None:
        return False
    return work_hours < 4.50


def serialize_employee(doc: dict) -> dict:
    return {
        "emp_code": doc["emp_code"],
        "name": doc["name"],
        "email": doc["email"],
        "department": doc["department"],
        "shift_start": doc["shift_start"],
        "shift_end": doc["shift_end"],
        "joined_on": doc["joined_on"],
        "created_at": to_epoch_ms(doc.get("created_at")),
    }


def serialize_attendance(doc: dict) -> dict:
    history_out = []
    for h in doc.get("history") or []:
        h_changes = {}
        for k, v in (h.get("changes") or {}).items():
            f_val = v.get("from")
            t_val = v.get("to")
            if k in ("punch_in", "punch_out"):
                if isinstance(f_val, datetime):
                    f_val = to_epoch_ms(f_val)
                if isinstance(t_val, datetime):
                    t_val = to_epoch_ms(t_val)
            h_changes[k] = {"from": f_val, "to": t_val}

        at_val = h.get("at")
        if isinstance(at_val, datetime):
            at_val = to_epoch_ms(at_val)

        history_out.append({
            "at": at_val,
            "by": h.get("by"),
            "reason": h.get("reason"),
            "changes": h_changes,
        })

    return {
        "emp_code": doc["emp_code"],
        "date": doc["date"],
        "status": doc["status"],
        "punch_in": to_epoch_ms(doc.get("punch_in")),
        "punch_out": to_epoch_ms(doc.get("punch_out")),
        "work_hours": doc.get("work_hours"),
        "late_minutes": doc.get("late_minutes", 0),
        "overtime_minutes": doc.get("overtime_minutes", 0),
        "half_day": doc.get("half_day", False),
        "history": history_out,
    }


# --------------------------------------------------------------------------- #
# Request Schemas
# --------------------------------------------------------------------------- #
class EmployeeCreate(BaseModel):
    emp_code: str = Field(..., pattern=r"^EMP\d{4,6}$")
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(..., min_length=1, max_length=50)
    shift_start: str = Field("09:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    shift_end: str = Field("18:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    joined_on: str

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("joined_on must be YYYY-MM-DD")
        return v


class PunchInRequest(BaseModel):
    emp_code: str
    punched_at: Optional[Any] = None
    status: str = "PRESENT"


class PunchOutRequest(BaseModel):
    emp_code: str
    punched_at: Optional[Any] = None


class RegularizeRequest(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[Any] = None
    punch_out: Optional[Any] = None
    reason: str = Field(..., min_length=5, max_length=200)
    regularized_by: str = Field(..., min_length=1, max_length=50)


# --------------------------------------------------------------------------- #
# API Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health", tags=["system"])
def health():
    """Readiness probe. Returns 200 only if MongoDB answers a ping, otherwise 503."""
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.post("/employees", status_code=201, tags=["employees"])
def create_employee(body: EmployeeCreate):
    """Create an employee. Unique emp_code enforced by database unique index."""
    if body.shift_start == body.shift_end:
        raise HTTPException(status_code=422, detail="shift_start must differ from shift_end")

    doc = body.model_dump()
    _, now_dt = current_server_time_truncated()
    doc["created_at"] = now_dt

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Employee with this emp_code already exists")

    return serialize_employee(doc)


@app.get("/employees", tags=["employees"])
def list_employees(
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List employees sorted by emp_code ascending."""
    q = {}
    if department is not None:
        q["department"] = department

    total = db.employees.count_documents(q)
    skip = (page - 1) * page_size
    cursor = db.employees.find(q).sort("emp_code", 1).skip(skip).limit(page_size)
    items = [serialize_employee(d) for d in cursor]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201, tags=["attendance"])
def punch_in(body: PunchInRequest):
    """Record a punch-in. Creates the day's record. Concurrency safe."""
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    if body.status not in ("PRESENT", "WFH", "ON_DUTY"):
        raise HTTPException(status_code=422, detail="status must be one of PRESENT, WFH, ON_DUTY")

    if body.punched_at is not None:
        ms = validate_epoch_ms(body.punched_at)
        punch_in_dt = ms_to_datetime_utc(ms)
    else:
        _, punch_in_dt = current_server_time_truncated()

    att_date = get_attendance_date(punch_in_dt, emp["shift_start"], emp["shift_end"])
    late_minutes = compute_late_minutes(punch_in_dt, emp["shift_start"], att_date)

    doc = {
        "emp_code": body.emp_code,
        "date": att_date,
        "status": body.status,
        "punch_in": punch_in_dt,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": late_minutes,
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Already punched in for this date")

    return serialize_attendance(doc)


@app.post("/attendance/punch-out", status_code=200, tags=["attendance"])
def punch_out(body: PunchOutRequest):
    """Record a punch-out. Closes the employee's most recent record."""
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    if body.punched_at is not None:
        ms = validate_epoch_ms(body.punched_at)
        punch_out_dt = ms_to_datetime_utc(ms)
    else:
        _, punch_out_dt = current_server_time_truncated()

    # Find employee's most recent record whose punch_in <= punched_at
    rec = db.attendance_logs.find_one(
        {"emp_code": body.emp_code, "punch_in": {"$lte": punch_out_dt}},
        sort=[("punch_in", -1)],
    )

    if not rec:
        # Check if the employee has any punch-in at all
        any_punch = db.attendance_logs.find_one(
            {"emp_code": body.emp_code, "punch_in": {"$ne": None}}
        )
        if any_punch:
            # Punch-in exists but is after punched_at (punched_at <= punch_in)
            raise HTTPException(status_code=422, detail="punched_at must be after punch_in")
        raise HTTPException(status_code=404, detail="No punch-in found")

    punch_in_dt = rec["punch_in"]
    if punch_in_dt.tzinfo is None:
        punch_in_dt = punch_in_dt.replace(tzinfo=timezone.utc)

    duration_sec = (punch_out_dt - punch_in_dt).total_seconds()
    if duration_sec <= 0 or duration_sec > 24 * 3600:
        raise HTTPException(status_code=422, detail="punched_at must be after punch_in and within 24 hours")

    if rec.get("punch_out") is not None:
        raise HTTPException(status_code=409, detail="Record is already punched out")

    work_hours = compute_work_hours(punch_in_dt, punch_out_dt)
    half_day = compute_half_day(work_hours)
    overtime_minutes = compute_overtime_minutes(punch_out_dt, emp["shift_start"], emp["shift_end"], rec["date"])

    # Atomic update ensuring only one concurrent punch-out succeeds
    updated = db.attendance_logs.find_one_and_update(
        {
            "_id": rec["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": punch_out_dt,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    if not updated:
        raise HTTPException(status_code=409, detail="Record is already punched out")

    return serialize_attendance(updated)


@app.get("/attendance", tags=["attendance"])
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List attendance records sorted by date descending, then emp_code ascending."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from cannot be greater than date_to")

    if status and status not in ("PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"):
        raise HTTPException(status_code=422, detail="Invalid status")

    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if status:
        q["status"] = status
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to

    total = db.attendance_logs.count_documents(q)
    skip = (page - 1) * page_size
    cursor = db.attendance_logs.find(q).sort([("date", -1), ("emp_code", 1)]).skip(skip).limit(page_size)
    items = [serialize_attendance(d) for d in cursor]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.patch("/attendance/{emp_code}/{date}", tags=["attendance"])
def regularize_attendance(
    emp_code: str = Path(...),
    date: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    body: RegularizeRequest = ...,
):
    """Regularize (manually correct) one day's record."""
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    rec = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if not rec:
        raise HTTPException(status_code=404, detail="Attendance record not found for that date")

    if body.status is not None and body.status not in ("PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"):
        raise HTTPException(status_code=422, detail="Invalid status")

    # Rules for regularization
    if body.status in ("ABSENT", "LEAVE"):
        if body.punch_in is not None or body.punch_out is not None:
            raise HTTPException(status_code=422, detail="Cannot supply punch_in or punch_out when setting ABSENT or LEAVE")
        target_status = body.status
        target_punch_in = None
        target_punch_out = None
        target_work_hours = None
        target_late_minutes = 0
        target_overtime_minutes = 0
        target_half_day = False
    else:
        target_status = body.status if body.status is not None else rec["status"]
        if target_status in ("ABSENT", "LEAVE"):
            if body.punch_in is not None or body.punch_out is not None:
                raise HTTPException(status_code=422, detail="ABSENT and LEAVE records cannot have punch times")
            target_punch_in = None
            target_punch_out = None
            target_work_hours = None
            target_late_minutes = 0
            target_overtime_minutes = 0
            target_half_day = False
        else:
            # Presence status
            if body.punch_in is not None:
                in_ms = validate_epoch_ms(body.punch_in)
                target_punch_in = ms_to_datetime_utc(in_ms)
            else:
                target_punch_in = rec.get("punch_in")

            if target_punch_in is None:
                raise HTTPException(status_code=422, detail="A presence status requires a punch_in")

            if target_punch_in.tzinfo is None:
                target_punch_in = target_punch_in.replace(tzinfo=timezone.utc)

            # punch_in must stay on the record's attendance date (R1)
            computed_date = get_attendance_date(target_punch_in, emp["shift_start"], emp["shift_end"])
            if computed_date != date:
                raise HTTPException(status_code=422, detail="punch_in must stay on the record's attendance date")

            if body.punch_out is not None:
                out_ms = validate_epoch_ms(body.punch_out)
                target_punch_out = ms_to_datetime_utc(out_ms)
            else:
                target_punch_out = rec.get("punch_out")

            if target_punch_out is not None:
                if target_punch_out.tzinfo is None:
                    target_punch_out = target_punch_out.replace(tzinfo=timezone.utc)

                diff_sec = (target_punch_out - target_punch_in).total_seconds()
                if diff_sec <= 0 or diff_sec > 24 * 3600:
                    raise HTTPException(status_code=422, detail="punch_out must be after punch_in and within 24 hours")

                target_work_hours = compute_work_hours(target_punch_in, target_punch_out)
                target_half_day = compute_half_day(target_work_hours)
                target_overtime_minutes = compute_overtime_minutes(target_punch_out, emp["shift_start"], emp["shift_end"], date)
            else:
                target_work_hours = None
                target_half_day = False
                target_overtime_minutes = 0

            target_late_minutes = compute_late_minutes(target_punch_in, emp["shift_start"], date)

    # Calculate actual changes
    changes = {}
    if rec.get("status") != target_status:
        changes["status"] = {"from": rec.get("status"), "to": target_status}

    old_in = rec.get("punch_in")
    if (old_in != target_punch_in) and (old_in is None or target_punch_in is None or to_epoch_ms(old_in) != to_epoch_ms(target_punch_in)):
        changes["punch_in"] = {"from": old_in, "to": target_punch_in}

    old_out = rec.get("punch_out")
    if (old_out != target_punch_out) and (old_out is None or target_punch_out is None or to_epoch_ms(old_out) != to_epoch_ms(target_punch_out)):
        changes["punch_out"] = {"from": old_out, "to": target_punch_out}

    if rec.get("work_hours") != target_work_hours:
        changes["work_hours"] = {"from": rec.get("work_hours"), "to": target_work_hours}

    if rec.get("late_minutes", 0) != target_late_minutes:
        changes["late_minutes"] = {"from": rec.get("late_minutes", 0), "to": target_late_minutes}

    if rec.get("overtime_minutes", 0) != target_overtime_minutes:
        changes["overtime_minutes"] = {"from": rec.get("overtime_minutes", 0), "to": target_overtime_minutes}

    if rec.get("half_day", False) != target_half_day:
        changes["half_day"] = {"from": rec.get("half_day", False), "to": target_half_day}

    if not changes:
        raise HTTPException(status_code=422, detail="Request changes nothing")

    _, now_dt = current_server_time_truncated()
    history_entry = {
        "at": now_dt,
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes,
    }

    # Optimistic locking against concurrent regularizations
    updated = db.attendance_logs.find_one_and_update(
        {
            "_id": rec["_id"],
            "history": rec.get("history", []),
        },
        {
            "$set": {
                "status": target_status,
                "punch_in": target_punch_in,
                "punch_out": target_punch_out,
                "work_hours": target_work_hours,
                "late_minutes": target_late_minutes,
                "overtime_minutes": target_overtime_minutes,
                "half_day": target_half_day,
            },
            "$push": {
                "history": history_entry
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    if not updated:
        raise HTTPException(status_code=409, detail="Concurrent edit detected")

    return serialize_attendance(updated)


# --------------------------------------------------------------------------- #
# Analytics Endpoints (MongoDB Aggregations)
# --------------------------------------------------------------------------- #
def build_employee_monthly_pipeline(emp_code: str, month: str, num_days: int) -> list[dict]:
    start_date = f"{month}-01"
    end_date = f"{month}-{num_days:02d}"
    return [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {"$gte": start_date, "$lte": end_date}
            }
        },
        {
            "$project": {
                "is_weekday": {
                    "$in": [
                        {"$isoDayOfWeek": {"$dateFromString": {"dateString": "$date"}}},
                        [1, 2, 3, 4, 5]
                    ]
                },
                "is_present": {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                "half_day": {"$ifNull": ["$half_day", False]},
                "status": 1,
                "late_minutes": {"$ifNull": ["$late_minutes", 0]},
                "overtime_minutes": {"$ifNull": ["$overtime_minutes", 0]},
            }
        },
        {
            "$project": {
                "present_val": {
                    "$cond": [
                        {"$and": ["$is_weekday", "$is_present"]},
                        {"$cond": ["$half_day", 0.5, 1.0]},
                        0.0
                    ]
                },
                "leave_val": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]},
                "late_val": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]},
                "late_minutes": 1,
                "overtime_minutes": 1,
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {"$sum": "$present_val"},
                "leave_days": {"$sum": "$leave_val"},
                "late_count": {"$sum": "$late_val"},
                "total_late_minutes": {"$sum": "$late_minutes"},
                "total_overtime_minutes": {"$sum": "$overtime_minutes"},
            }
        }
    ]


@app.get("/analytics/employees/{emp_code}/monthly", tags=["analytics"])
def employee_monthly(
    emp_code: str = Path(...),
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
):
    """Monthly attendance summary for one employee backed by MongoDB aggregation."""
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    year, m = map(int, month.split("-"))
    num_days = calendar.monthrange(year, m)[1]

    # Calculate working days per R7
    start_d = max(date(year, m, 1), date.fromisoformat(emp["joined_on"]))
    end_d = date(year, m, num_days)

    working_days = 0
    if start_d <= end_d:
        curr = start_d
        while curr <= end_d:
            if curr.weekday() < 5:  # Mon-Fri
                working_days += 1
            curr += timedelta(days=1)

    pipeline = build_employee_monthly_pipeline(emp_code, month, num_days)
    agg_res = list(db.attendance_logs.aggregate(pipeline))

    if agg_res:
        row = agg_res[0]
        present_days = float(row.get("present_days", 0.0))
        leave_days = int(row.get("leave_days", 0))
        late_count = int(row.get("late_count", 0))
        total_late_minutes = int(row.get("total_late_minutes", 0))
        total_overtime_minutes = int(row.get("total_overtime_minutes", 0))
    else:
        present_days = 0.0
        leave_days = 0
        late_count = 0
        total_late_minutes = 0
        total_overtime_minutes = 0

    attendance_pct = None
    if working_days > 0:
        attendance_pct = round_half_up((present_days / working_days) * 100, 2)

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": leave_days,
        "late_count": late_count,
        "total_late_minutes": total_late_minutes,
        "total_overtime_minutes": total_overtime_minutes,
        "attendance_pct": attendance_pct,
    }


def build_department_summary_pipeline(month: str, num_days: int, department: Optional[str] = None) -> list[dict]:
    start_date = f"{month}-01"
    end_date = f"{month}-{num_days:02d}"

    match_stage = {"joined_on": {"$lte": end_date}}
    if department:
        match_stage["department"] = department

    return [
        {"$match": match_stage},
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"emp": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$emp"]},
                                    {"$gte": ["$date", start_date]},
                                    {"$lte": ["$date", end_date]}
                                ]
                            }
                        }
                    }
                ],
                "as": "logs"
            }
        },
        {
            "$project": {
                "department": 1,
                "emp_code": 1,
                "present_days": {
                    "$reduce": {
                        "input": "$logs",
                        "initialValue": 0.0,
                        "in": {
                            "$add": [
                                "$$value",
                                {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$in": ["$$this.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                                {"$in": [{"$isoDayOfWeek": {"$dateFromString": {"dateString": "$$this.date"}}}, [1, 2, 3, 4, 5]]}
                                            ]
                                        },
                                        {"$cond": [{"$ifNull": ["$$this.half_day", False]}, 0.5, 1.0]},
                                        0.0
                                    ]
                                }
                            ]
                        }
                    }
                },
                "work_hours": {
                    "$map": {
                        "input": {
                            "$filter": {
                                "input": "$logs",
                                "as": "l",
                                "cond": {
                                    "$and": [
                                        {"$in": ["$$l.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                        {"$ne": ["$$l.work_hours", None]}
                                    ]
                                }
                            }
                        },
                        "as": "item",
                        "in": "$$item.work_hours"
                    }
                },
                "late_count": {
                    "$size": {
                        "$filter": {
                            "input": "$logs",
                            "as": "l",
                            "cond": {"$gt": [{"$ifNull": ["$$l.late_minutes", 0]}, 0]}
                        }
                    }
                },
                "total_late_minutes": {
                    "$reduce": {
                        "input": "$logs",
                        "initialValue": 0,
                        "in": {"$add": ["$$value", {"$ifNull": ["$$this.late_minutes", 0]}]}
                    }
                },
                "leave_count": {
                    "$size": {
                        "$filter": {
                            "input": "$logs",
                            "as": "l",
                            "cond": {"$eq": ["$$l.status", "LEAVE"]}
                        }
                    }
                },
                "on_duty_count": {
                    "$size": {
                        "$filter": {
                            "input": "$logs",
                            "as": "l",
                            "cond": {"$eq": ["$$l.status", "ON_DUTY"]}
                        }
                    }
                }
            }
        },
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$sum": 1},
                "present_days": {"$sum": "$present_days"},
                "wh_nested": {"$push": "$work_hours"},
                "late_count": {"$sum": "$late_count"},
                "total_late_minutes": {"$sum": "$total_late_minutes"},
                "leave_count": {"$sum": "$leave_count"},
                "on_duty_count": {"$sum": "$on_duty_count"}
            }
        },
        {
            "$project": {
                "department": "$_id",
                "_id": 0,
                "headcount": 1,
                "present_days": 1,
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1,
                "flat_wh": {
                    "$reduce": {
                        "input": "$wh_nested",
                        "initialValue": [],
                        "in": {"$concatArrays": ["$$value", "$$this"]}
                    }
                }
            }
        },
        {
            "$project": {
                "department": 1,
                "headcount": 1,
                "present_days": 1,
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1,
                "avg_work_hours": {
                    "$cond": [
                        {"$gt": [{"$size": "$flat_wh"}, 0]},
                        {"$avg": "$flat_wh"},
                        None
                    ]
                }
            }
        },
        {"$sort": {"department": 1}}
    ]


@app.get("/analytics/departments/summary", tags=["analytics"])
def department_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = None,
):
    """Department summary for a month via MongoDB aggregation."""
    year, m = map(int, month.split("-"))
    num_days = calendar.monthrange(year, m)[1]

    pipeline = build_department_summary_pipeline(month, num_days, department)
    docs = list(db.employees.aggregate(pipeline))

    items = []
    for d in docs:
        avg_wh = d.get("avg_work_hours")
        if avg_wh is not None:
            avg_wh = round_half_up(avg_wh, 2)
        items.append({
            "department": d["department"],
            "headcount": d["headcount"],
            "present_days": round_half_up(d["present_days"], 2),
            "avg_work_hours": avg_wh,
            "late_count": d["late_count"],
            "total_late_minutes": d["total_late_minutes"],
            "leave_count": d["leave_count"],
            "on_duty_count": d["on_duty_count"],
        })

    return {"month": month, "items": items}


def build_late_leaderboard_pipeline(month: str, num_days: int, limit: int, department: Optional[str] = None) -> list[dict]:
    start_date = f"{month}-01"
    end_date = f"{month}-{num_days:02d}"

    pipeline = [
        {
            "$match": {
                "date": {"$gte": start_date, "$lte": end_date},
                "late_minutes": {"$gt": 0}
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1}
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "emp"
            }
        },
        {"$unwind": "$emp"},
    ]

    if department:
        pipeline.append({"$match": {"emp.department": department}})

    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {
                    "rank": {"$rank": {}}
                }
            }
        },
        {
            "$match": {
                "rank": {"$lte": limit}
            }
        },
        {
            "$sort": {
                "total_late_minutes": -1,
                "_id": 1
            }
        },
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$emp.name",
                "department": "$emp.department",
                "total_late_minutes": 1,
                "late_count": 1
            }
        }
    ])
    return pipeline


@app.get("/analytics/leaderboard/late", tags=["analytics"])
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None,
):
    """Late-comers leaderboard for a month using standard competition ranking."""
    year, m = map(int, month.split("-"))
    num_days = calendar.monthrange(year, m)[1]

    pipeline = build_late_leaderboard_pipeline(month, num_days, limit, department)
    items = list(db.attendance_logs.aggregate(pipeline))
    return {"month": month, "items": items}


def build_department_trend_pipeline(department: str, from_str: str, to_str: str) -> list[dict]:
    from_dt = datetime.strptime(from_str, "%Y-%m-%d")
    to_dt = datetime.strptime(to_str, "%Y-%m-%d")
    bounds_end = to_dt + timedelta(days=1)

    return [
        {
            "$match": {
                "date": {"$gte": from_str, "$lte": to_str}
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "emp"
            }
        },
        {"$unwind": "$emp"},
        {
            "$match": {
                "emp.department": department
            }
        },
        {
            "$group": {
                "_id": "$date",
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                            {"$cond": [{"$ifNull": ["$half_day", False]}, 0.5, 1.0]},
                            0.0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]
                    }
                }
            }
        },
        {
            "$project": {
                "date": {"$dateFromString": {"dateString": "$_id"}},
                "present_count": 1,
                "late_count": 1
            }
        },
        {
            "$densify": {
                "field": "date",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [from_dt, bounds_end]
                }
            }
        },
        {
            "$project": {
                "date_str": {"$dateToString": {"format": "%Y-%m-%d", "date": "$date"}},
                "present_count": {"$ifNull": ["$present_count", 0.0]},
                "late_count": {"$ifNull": ["$late_count", 0]},
                "is_working_day": {
                    "$in": [{"$isoDayOfWeek": "$date"}, [1, 2, 3, 4, 5]]
                }
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "let": {"cur_date": "$date_str"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$department", department]},
                                    {"$lte": ["$joined_on", "$$cur_date"]}
                                ]
                            }
                        }
                    },
                    {"$count": "count"}
                ],
                "as": "hc"
            }
        },
        {
            "$project": {
                "date": "$date_str",
                "is_working_day": 1,
                "headcount": {"$ifNull": [{"$first": "$hc.count"}, 0]},
                "present_count": 1,
                "late_count": 1,
            }
        },
        {
            "$project": {
                "date": 1,
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": {
                    "$cond": [
                        {"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
                        {"$divide": ["$present_count", "$headcount"]},
                        None
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"date": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {
                            "documents": [-6, "current"]
                        }
                    }
                }
            }
        },
        {"$sort": {"date": 1}}
    ]


@app.get("/analytics/departments/{department}/trend", tags=["analytics"])
def department_trend(
    department: str = Path(...),
    from_date: str = Query(..., alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    to_date: str = Query(..., alias="to", pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """Daily attendance trend for a department."""
    # Check if department exists
    if db.employees.count_documents({"department": department}) == 0:
        raise HTTPException(status_code=404, detail="Department not found")

    d_from = date.fromisoformat(from_date)
    d_to = date.fromisoformat(to_date)

    if d_to < d_from:
        raise HTTPException(status_code=422, detail="to date cannot be earlier than from date")

    diff_days = (d_to - d_from).days + 1
    if diff_days > 92:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 92 days")

    pipeline = build_department_trend_pipeline(department, from_date, to_date)
    docs = list(db.attendance_logs.aggregate(pipeline))

    items = []
    for d in docs:
        att_rate = d.get("attendance_rate")
        if att_rate is not None:
            att_rate = round_half_up(att_rate, 4)

        mov_avg = d.get("moving_avg_7d")
        if mov_avg is not None:
            mov_avg = round_half_up(mov_avg, 4)

        items.append({
            "date": d["date"],
            "is_working_day": d["is_working_day"],
            "headcount": d["headcount"],
            "present_count": round_half_up(d["present_count"], 2),
            "late_count": d["late_count"],
            "attendance_rate": att_rate,
            "moving_avg_7d": mov_avg,
        })

    return {"department": department, "items": items}


# --------------------------------------------------------------------------- #
# Admin Explain Endpoint
# --------------------------------------------------------------------------- #
@app.get("/admin/explain/{endpoint}", tags=["admin"])
def explain_endpoint(
    endpoint: str = Path(...),
    emp_code: Optional[str] = None,
    month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = None,
    limit: Optional[int] = Query(10, ge=1, le=50),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Run explain with executionStats for the named endpoint's query/pipeline."""
    if endpoint == "attendance_list":
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=422, detail="date_from cannot be greater than date_to")
        q = {}
        if emp_code:
            q["emp_code"] = emp_code
        if status:
            q["status"] = status
        if date_from or date_to:
            q["date"] = {}
            if date_from:
                q["date"]["$gte"] = date_from
            if date_to:
                q["date"]["$lte"] = date_to
        skip = (page - 1) * page_size
        explain_res = db.command("explain", {
            "find": "attendance_logs",
            "filter": q,
            "sort": {"date": -1, "emp_code": 1},
            "skip": skip,
            "limit": page_size,
        }, verbosity="executionStats")
        coll_name = "attendance_logs"

    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(status_code=422, detail="emp_code and month are required")
        year, m = map(int, month.split("-"))
        num_days = calendar.monthrange(year, m)[1]
        pipeline = build_employee_monthly_pipeline(emp_code, month, num_days)
        explain_res = db.command("explain", {
            "aggregate": "attendance_logs",
            "pipeline": pipeline,
            "cursor": {},
        }, verbosity="executionStats")
        coll_name = "attendance_logs"

    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(status_code=422, detail="month is required")
        year, m = map(int, month.split("-"))
        num_days = calendar.monthrange(year, m)[1]
        pipeline = build_department_summary_pipeline(month, num_days, department)
        explain_res = db.command("explain", {
            "aggregate": "employees",
            "pipeline": pipeline,
            "cursor": {},
        }, verbosity="executionStats")
        coll_name = "employees"

    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(status_code=422, detail="month is required")
        year, m = map(int, month.split("-"))
        num_days = calendar.monthrange(year, m)[1]
        pipeline = build_late_leaderboard_pipeline(month, num_days, limit or 10, department)
        explain_res = db.command("explain", {
            "aggregate": "attendance_logs",
            "pipeline": pipeline,
            "cursor": {},
        }, verbosity="executionStats")
        coll_name = "attendance_logs"

    elif endpoint == "department_trend":
        if not department or not from_date or not to_date:
            raise HTTPException(status_code=422, detail="department, from, and to are required")
        pipeline = build_department_trend_pipeline(department, from_date, to_date)
        explain_res = db.command("explain", {
            "aggregate": "attendance_logs",
            "pipeline": pipeline,
            "cursor": {},
        }, verbosity="executionStats")
        coll_name = "attendance_logs"

    else:
        raise HTTPException(status_code=422, detail="Invalid endpoint name")

    explain_clean = json.loads(json_util.dumps(explain_res))
    return {
        "endpoint": endpoint,
        "collection": coll_name,
        "explain": explain_clean,
    }
