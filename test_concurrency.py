"""
Concurrency test verifying simultaneous requests handling.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_concurrent_punch_ins():
    # Setup test employee
    emp_code = "EMP8881"
    client.post("/employees", json={
        "emp_code": emp_code,
        "name": "Race Tester",
        "email": "race@example.com",
        "department": "QA",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01"
    })

    # Fixed timestamp for same date
    dt = datetime(2026, 9, 1, 4, 0, 0, tzinfo=timezone.utc)
    ms = int(dt.timestamp() * 1000)

    def do_punch_in():
        return client.post("/attendance/punch-in", json={
            "emp_code": emp_code,
            "punched_at": ms
        }).status_code

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(do_punch_in) for _ in range(5)]
        codes = [f.result() for f in futures]

    print("Concurrent punch-in response codes:", codes)
    assert codes.count(201) == 1
    assert codes.count(409) == 4
    print("test_concurrent_punch_ins PASSED!")

def test_concurrent_punch_outs():
    emp_code = "EMP8882"
    client.post("/employees", json={
        "emp_code": emp_code,
        "name": "Race Tester 2",
        "email": "race2@example.com",
        "department": "QA",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01"
    })

    dt_in = datetime(2026, 9, 2, 4, 0, 0, tzinfo=timezone.utc)
    ms_in = int(dt_in.timestamp() * 1000)
    res_in = client.post("/attendance/punch-in", json={"emp_code": emp_code, "punched_at": ms_in})
    assert res_in.status_code == 201

    dt_out = datetime(2026, 9, 2, 13, 0, 0, tzinfo=timezone.utc)
    ms_out = int(dt_out.timestamp() * 1000)

    def do_punch_out():
        return client.post("/attendance/punch-out", json={
            "emp_code": emp_code,
            "punched_at": ms_out
        }).status_code

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(do_punch_out) for _ in range(5)]
        codes = [f.result() for f in futures]

    print("Concurrent punch-out response codes:", codes)
    assert codes.count(200) == 1
    assert codes.count(409) == 4
    print("test_concurrent_punch_outs PASSED!")

if __name__ == "__main__":
    test_concurrent_punch_ins()
    test_concurrent_punch_outs()
    print("ALL CONCURRENCY TESTS PASSED!")
