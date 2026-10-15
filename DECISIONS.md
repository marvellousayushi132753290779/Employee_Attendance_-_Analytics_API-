# DECISIONS.md

1. **Indexes.**
   On `employees`, we created a unique index on `emp_code` to enforce business identity and instant lookups, plus compound indexes on `(department, joined_on)` and `(joined_on, department)` to optimize filtering and headcount stages. On `attendance_logs`, we created a unique compound index on `(emp_code, date)` to prevent duplicate punches and optimize single-record lookups, `(date: -1, emp_code: 1)` to back paginated attendance queries, `(emp_code: 1, punch_in: -1)` for open-punch searches, and `(date: 1, late_minutes: 1, emp_code: 1)` for the late leaderboard. We considered and rejected indexing `history` or standalone status fields due to low selectivity and unnecessary write overhead.

2. **Punch-in race.**
   When two identical punch-in requests arrive simultaneously, both compute the attendance date and attempt `insert_one`. MongoDB's unique compound index on `(emp_code, date)` serializes the write: exactly one request succeeds and returns 201, while the loser encounters a `DuplicateKeyError`. Our code catches this exception and returns 409 Conflict, avoiding check-then-insert races.

3. **Ties.**
   Using MongoDB's `$setWindowFields` with the `$rank` operator, we apply standard competition ranking (1, 2, 2, 4). The `rank <= limit` filter applies after ranking. If two employees tie at the cutoff rank, both are included in the response (which may return more rows than `limit`), ordered secondarily by `emp_code` ascending.

4. **Headcount.**
   The department summary aggregation starts on the `employees` collection filtered by `joined_on <= month_end`, and uses `$lookup` to pull logs from `attendance_logs`. Headcount is computed via `{"$sum": 1}` per department; employees with zero logs have an empty logs array but still count toward headcount.

5. **One thing you would change for 100x data.**
   We would introduce pre-aggregated daily/monthly rollup collections updated asynchronously via MongoDB Change Streams or scheduled workers, serving analytics via point-lookups rather than ad-hoc aggregations over tens of millions of raw records.
