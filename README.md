# Employee Attendance & Analytics API

A high-performance backend API for employee attendance tracking and analytics built with **FastAPI** and **MongoDB**, strictly adhering to OpenAPI 3.0 specification (`openapi.yaml`) and business rules R1–R10.

---

## Getting Started

### 1. Prerequisites
- Python 3.11+
- MongoDB 6.0+ (local instance or MongoDB Atlas)

### 2. Environment Configuration
Create a `.env` file in the project root (environment variables take precedence):
```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

### 3. Setup Virtual Environment & Install Dependencies
```bash
python -m venv venv
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Seed Sample Data (Optional)
```bash
python sample_seed.py
```

### 5. Run the Application
```bash
uvicorn app.main:app --port 8000 --reload
```
Once started:
- **Interactive API Docs (Swagger UI)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Health Check Endpoint**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## Key Highlights & Implementation Details

- **Strict Schema & Business Rules Adherence**:
  - **R1 Attendance Date & Overnight Shifts**: Accommodates overnight shifts (`shift_end <= shift_start`) across midnight in IST (UTC+05:30). Instants are truncated to whole seconds.
  - **R2 Late Grace Period**: Evaluated strictly after 10:00 grace period (600 seconds) from shift start in IST.
  - **R3 Overtime**: Calculated from shift end with a minimum threshold of 30 minutes.
  - **R4 Work Hours**: Exact calculation in hours rounded half-up to 2 decimal places using `Decimal(ROUND_HALF_UP)`.
  - **R5 Half-Day**: Flagged when rounded work hours are strictly less than 4.50.
  - **R6 Presence**: Counts `PRESENT`, `WFH`, and `ON_DUTY` as present.
  - **R7 Working Days**: Computes Mon–Fri working days dynamically, adjusting for mid-month joiners (`joined_on`).
  - **R8 Rounding**: Round-half-up applied across rates (4 decimals) and reported metrics (2 decimals).
  - **R9 Headcount**: Includes all employees joined on or before period end, including those with zero attendance logs.
  - **R10 Pagination**: Pages start at 1, max page size is 100, and `total` accurately reflects query filters.

- **Concurrency & Race-Safety**:
  - Unique compound index on `("emp_code", "date")` ensures simultaneous punch-in requests yield exactly one `201 Created` and the rest `409 Conflict`.
  - Atomic `find_one_and_update` on punch-out guarantees only one concurrent punch-out succeeds.
  - Optimistic locking on attendance regularization prevents lost update anomalies on history audit trails.

- **Native MongoDB Aggregations**:
  - Analytics endpoints (`/analytics/employees/{emp_code}/monthly`, `/analytics/departments/summary`, `/analytics/leaderboard/late`, `/analytics/departments/{department}/trend`) use native MongoDB aggregation pipelines, avoiding in-memory Python iteration.
  - Gap filling in department trend is handled via `$densify`, and moving averages/competition rankings are computed with `$setWindowFields`.
  - All aggregation queries use index scans (`IXSCAN`) verified via `/admin/explain/{endpoint}` with executionStats verbosity.

---

## File Structure

- `app/main.py`: Complete FastAPI application implementation and lifecycle index creation.
- `requirements.txt`: Python package dependencies.
- `REVIEW.md`: Documentation of defect findings in starter code and resolutions.
- `DECISIONS.md`: Explanations of indexing strategy, concurrency handling, tie-breaking, and scalability decisions.
- `openapi.yaml`: API contract specification.
- `DATA_MODEL.md`: MongoDB schema documentation.
