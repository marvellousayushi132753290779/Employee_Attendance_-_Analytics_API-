"""
Automated test suite covering all requirements and edge cases.
"""
import calendar
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from fastapi.testclient import TestClient

from app.main import app, db, IST

client = TestClient(app)

def reset_db():
    import sample_seed
    # Reset to known sample state
    pass

def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

def test_employee_create_and_validation():
    # Invalid emp_code regex
    res = client.post("/employees", json={
        "emp_code": "INVALID",
        "name": "Test User",
        "email": "test@example.com",
        "department": "Engineering",
        "joined_on": "2026-01-01"
    })
    assert res.status_code == 422

    # Equal shift_start and shift_end
    res = client.post("/employees", json={
        "emp_code": "EMP9991",
        "name": "Test User",
        "email": "test@example.com",
        "department": "Engineering",
        "shift_start": "10:00",
        "shift_end": "10:00",
        "joined_on": "2026-01-01"
    })
    assert res.status_code == 422

    # Valid creation
    res = client.post("/employees", json={
        "emp_code": "EMP9991",
        "name": "Test User",
        "email": "test@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01"
    })
    assert res.status_code == 201
    data = res.json()
    assert data["emp_code"] == "EMP9991"
    assert isinstance(data["created_at"], int)
    assert data["created_at"] >= 100000000000
    assert "_id" not in data

    # Duplicate emp_code -> 409
    res = client.post("/employees", json={
        "emp_code": "EMP9991",
        "name": "Duplicate User",
        "email": "dup@example.com",
        "department": "Engineering",
        "joined_on": "2026-01-01"
    })
    assert res.status_code == 409

def test_list_employees():
    res = client.get("/employees", params={"page": 1, "page_size": 2})
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert data["total"] >= 2
    # Check sorting
    assert data["items"][0]["emp_code"] < data["items"][1]["emp_code"]

    # Filter by department
    res = client.get("/employees", params={"department": "Engineering"})
    assert res.status_code == 200
    data = res.json()
    for item in data["items"]:
        assert item["department"] == "Engineering"

def test_punch_in_and_rules():
    # 404 for unknown employee
    res = client.post("/attendance/punch-in", json={"emp_code": "EMP9999"})
    assert res.status_code == 404

    # 422 for invalid status
    res = client.post("/attendance/punch-in", json={"emp_code": "EMP9991", "status": "ABSENT"})
    assert res.status_code == 422

    # R2 test: Shift 09:30 IST.
    # 09:40:00 IST -> late_minutes = 0
    # 09:40:00 IST = 04:10:00 UTC
    dt_grace = datetime(2026, 8, 3, 4, 10, 0, tzinfo=timezone.utc)
    ms_grace = int(dt_grace.timestamp() * 1000)
    res = client.post("/attendance/punch-in", json={
        "emp_code": "EMP9991",
        "punched_at": ms_grace
    })
    assert res.status_code == 201
    data = res.json()
    assert data["date"] == "2026-08-03"
    assert data["late_minutes"] == 0
    assert data["punch_out"] is None
    assert data["work_hours"] is None
    assert "_id" not in data
    assert "id" not in data

    # Duplicate punch-in for same date -> 409
    res = client.post("/attendance/punch-in", json={
        "emp_code": "EMP9991",
        "punched_at": ms_grace + 1000
    })
    assert res.status_code == 409

    # Test strictly > 10 min late (09:40:01 IST -> 10 minutes late)
    # 09:40:01 IST = 04:10:01 UTC
    dt_late1 = datetime(2026, 8, 4, 4, 10, 1, tzinfo=timezone.utc)
    ms_late1 = int(dt_late1.timestamp() * 1000)
    res = client.post("/attendance/punch-in", json={
        "emp_code": "EMP9991",
        "punched_at": ms_late1
    })
    assert res.status_code == 201
    assert res.json()["late_minutes"] == 10

    # Test 45 min late (10:15:59 IST -> 45 minutes late)
    # 10:15:59 IST = 04:45:59 UTC
    dt_late2 = datetime(2026, 8, 5, 4, 45, 59, tzinfo=timezone.utc)
    ms_late2 = int(dt_late2.timestamp() * 1000)
    res = client.post("/attendance/punch-in", json={
        "emp_code": "EMP9991",
        "punched_at": ms_late2
    })
    assert res.status_code == 201
    assert res.json()["late_minutes"] == 45

def test_overnight_shift_punch_in():
    # EMP0005 has overnight shift 22:00 - 06:00
    # Punch in at 01:30 IST on 2026-08-11 -> belongs to shift starting 2026-08-10
    # 01:30 IST on 2026-08-11 = 20:00 UTC on 2026-08-10
    dt_overnight = datetime(2026, 8, 10, 20, 0, 0, tzinfo=timezone.utc)
    ms_overnight = int(dt_overnight.timestamp() * 1000)
    res = client.post("/attendance/punch-in", json={
        "emp_code": "EMP0005",
        "punched_at": ms_overnight
    })
    assert res.status_code == 201
    data = res.json()
    assert data["date"] == "2026-08-10"

def test_punch_out_and_rules():
    # 404 for unknown employee
    res = client.post("/attendance/punch-out", json={"emp_code": "EMP9999"})
    assert res.status_code == 404

    # For EMP9991 on 2026-08-03:
    # punched in at 04:10:00 UTC (09:40:00 IST).
    # Punch out at 13:40:00 UTC (19:10:00 IST):
    # Total duration: 9 hours 30 min = 9.50 hours.
    # Shift end: 18:30 IST. Overtime: 40 minutes (>= 30 min -> 40 min).
    dt_out = datetime(2026, 8, 3, 13, 40, 0, tzinfo=timezone.utc)
    ms_out = int(dt_out.timestamp() * 1000)
    res = client.post("/attendance/punch-out", json={
        "emp_code": "EMP9991",
        "punched_at": ms_out
    })
    assert res.status_code == 200
    data = res.json()
    assert data["work_hours"] == 9.5
    assert data["half_day"] is False
    assert data["overtime_minutes"] == 40

    # Second punch-out on same record -> 409
    res = client.post("/attendance/punch-out", json={
        "emp_code": "EMP9991",
        "punched_at": ms_out + 10000
    })
    assert res.status_code == 409

    # Punch out equal to punch in (duration <= 0) -> 422
    # On 2026-08-04, punched in at 04:10:01 UTC
    dt_bad = datetime(2026, 8, 4, 4, 10, 1, tzinfo=timezone.utc)
    res = client.post("/attendance/punch-out", json={
        "emp_code": "EMP9991",
        "punched_at": int(dt_bad.timestamp() * 1000)
    })
    assert res.status_code == 422

    # Half-day test: punch out with 4.0 hours (< 4.50)
    # Punched in at 04:10:01 UTC on 2026-08-04. Punch out at 08:10:01 UTC (4.0 hours)
    dt_half = datetime(2026, 8, 4, 8, 10, 1, tzinfo=timezone.utc)
    res = client.post("/attendance/punch-out", json={
        "emp_code": "EMP9991",
        "punched_at": int(dt_half.timestamp() * 1000)
    })
    assert res.status_code == 200
    data = res.json()
    assert data["work_hours"] == 4.0
    assert data["half_day"] is True

def test_attendance_list():
    # date_from > date_to -> 422
    res = client.get("/attendance", params={"date_from": "2026-08-10", "date_to": "2026-08-01"})
    assert res.status_code == 422

    res = client.get("/attendance", params={"emp_code": "EMP9991"})
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) >= 2
    # Verify date descending sort
    dates = [item["date"] for item in data["items"]]
    assert dates == sorted(dates, reverse=True)

def test_regularize_attendance():
    # 404 unknown employee
    res = client.patch("/attendance/EMP9999/2026-08-03", json={
        "reason": "Corrected time",
        "regularized_by": "admin"
    })
    assert res.status_code == 404

    # 404 unknown date
    res = client.patch("/attendance/EMP9991/2026-01-01", json={
        "reason": "Corrected time",
        "regularized_by": "admin"
    })
    assert res.status_code == 404

    # 422 changing nothing
    res = client.patch("/attendance/EMP9991/2026-08-03", json={
        "status": "PRESENT",
        "reason": "Same status",
        "regularized_by": "admin"
    })
    assert res.status_code == 422

    # 422 setting ABSENT with punch times
    res = client.patch("/attendance/EMP9991/2026-08-03", json={
        "status": "ABSENT",
        "punch_in": 1783312500000,
        "reason": "Setting absent with time",
        "regularized_by": "admin"
    })
    assert res.status_code == 422

    # Valid change: Change status to WFH
    res = client.patch("/attendance/EMP9991/2026-08-03", json={
        "status": "WFH",
        "reason": "Worked from home approved",
        "regularized_by": "manager"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "WFH"
    assert len(data["history"]) == 1
    h = data["history"][0]
    assert h["by"] == "manager"
    assert h["reason"] == "Worked from home approved"
    assert "status" in h["changes"]
    assert h["changes"]["status"] == {"from": "PRESENT", "to": "WFH"}

def test_analytics_endpoints():
    # 1. Employee monthly
    res = client.get("/analytics/employees/EMP0001/monthly", params={"month": "2026-07"})
    assert res.status_code == 200
    data = res.json()
    assert data["emp_code"] == "EMP0001"
    assert data["month"] == "2026-07"
    assert data["working_days"] == 23
    assert data["present_days"] == 2.0
    assert data["attendance_pct"] == 8.70

    # 404 unknown employee
    res = client.get("/analytics/employees/EMP9999/monthly", params={"month": "2026-07"})
    assert res.status_code == 404

    # 2. Department summary
    res = client.get("/analytics/departments/summary", params={"month": "2026-07"})
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    depts = {item["department"]: item for item in data["items"]}
    assert "Engineering" in depts
    assert "Sales" in depts
    assert "Support" in depts
    assert depts["Engineering"]["headcount"] == 3
    assert depts["Engineering"]["present_days"] == 3.0
    assert depts["Engineering"]["avg_work_hours"] == 9.04
    assert depts["Sales"]["late_count"] == 1
    assert depts["Sales"]["total_late_minutes"] == 35

    # 3. Leaderboard
    res = client.get("/analytics/leaderboard/late", params={"month": "2026-07", "limit": 5})
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["rank"] == 1
    assert data["items"][0]["emp_code"] == "EMP0003"
    assert data["items"][0]["total_late_minutes"] == 35

    # 4. Department trend
    res = client.get("/analytics/departments/Sales/trend", params={"from": "2026-07-05", "to": "2026-07-10"})
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 6
    # 2026-07-05 is Sunday
    assert data["items"][0]["date"] == "2026-07-05"
    assert data["items"][0]["is_working_day"] is False
    assert data["items"][0]["attendance_rate"] is None

    # 2026-07-06 is Monday
    assert data["items"][1]["date"] == "2026-07-06"
    assert data["items"][1]["is_working_day"] is True
    assert data["items"][1]["headcount"] == 2
    assert data["items"][1]["attendance_rate"] == 0.5
    assert data["items"][1]["moving_avg_7d"] == 0.5

    # 404 unknown department
    res = client.get("/analytics/departments/NonExistent/trend", params={"from": "2026-07-01", "to": "2026-07-05"})
    assert res.status_code == 404

    # 422 to < from
    res = client.get("/analytics/departments/Sales/trend", params={"from": "2026-07-10", "to": "2026-07-05"})
    assert res.status_code == 422

    # 422 range > 92 days
    res = client.get("/analytics/departments/Sales/trend", params={"from": "2026-01-01", "to": "2026-05-01"})
    assert res.status_code == 422

def test_explain_endpoint():
    endpoints = [
        ("attendance_list", {"emp_code": "EMP0001", "date_from": "2026-07-01", "date_to": "2026-07-31"}),
        ("employee_monthly", {"emp_code": "EMP0001", "month": "2026-07"}),
        ("department_summary", {"month": "2026-07"}),
        ("late_leaderboard", {"month": "2026-07"}),
        ("department_trend", {"department": "Sales", "from": "2026-07-01", "to": "2026-07-10"}),
    ]
    for ep, params in endpoints:
        res = client.get(f"/admin/explain/{ep}", params=params)
        assert res.status_code == 200
        data = res.json()
        assert data["endpoint"] == ep
        assert "collection" in data
        assert "explain" in data
    print("All tests passed successfully!")

if __name__ == "__main__":
    test_health()
    print("test_health passed")
    test_employee_create_and_validation()
    print("test_employee_create_and_validation passed")
    test_list_employees()
    print("test_list_employees passed")
    test_punch_in_and_rules()
    print("test_punch_in_and_rules passed")
    test_overnight_shift_punch_in()
    print("test_overnight_shift_punch_in passed")
    test_punch_out_and_rules()
    print("test_punch_out_and_rules passed")
    test_attendance_list()
    print("test_attendance_list passed")
    test_regularize_attendance()
    print("test_regularize_attendance passed")
    test_analytics_endpoints()
    print("test_analytics_endpoints passed")
    test_explain_endpoint()
    print("test_explain_endpoint passed")
    print("\n================== ALL TESTS PASSED! ==================")
