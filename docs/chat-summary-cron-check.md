# How to check if the chat summary cron job is running

The chat summary cron runs **daily at 11:20 AM** and generates property-level summaries for listings that need them (no summary yet, or 7+ days since last summary).

---

## Why `last_run_at` and `last_run_status` are null

If **GET /api/v1/admin/cron/status** returns `last_run_at: null` and `last_run_status: null`, it means **no run has been recorded yet**. The status comes from the `cron_job_runs` table; rows are added only when:

1. The cron script **infra/scripts/summary_cron.sh** runs and then calls **POST /api/v1/admin/cron/last-run**, or  
2. You **manually register a run** (see below).

**To get non-null status:** run the cron script once (or trigger the summary job and then register the run), or record a test run with the curl below.

---

## Record a test run (so status is no longer null)

To verify the status endpoint and DB without waiting for the real cron:

```bash
# Replace with your API base URL
curl -s -X POST http://127.0.0.1:8000/api/v1/admin/cron/last-run \
  -H "Content-Type: application/json" \
  -d '{"last_run_at": "2026-02-21T11:20:00+00:00", "status": "200"}'
```

Then call **GET /api/v1/admin/cron/status** again; you should see `last_run_at` and `last_run_status` populated.

---

## 1. Check cron status via API (recommended)

Call the admin cron status endpoint. It returns the **last run time** and **last run status** from the database (updated each time the cron script runs).

```bash
# Replace with your API base URL if different
curl -s http://127.0.0.1:8000/api/v1/admin/cron/status
```

**Example response when the cron has run:**

```json
{
  "job_name": "chat_summary",
  "schedule": "daily at 11:20 AM",
  "endpoint": "/api/v1/admin/summaries/generate",
  "ready": true,
  "last_run_at": "2026-02-21T11:20:05+0530",
  "last_run_status": "200"
}
```

- **`last_run_at`** – When the cron last ran (from DB).
- **`last_run_status`** – HTTP status of the summary job (e.g. `200` = success, `500` = server error).

If **`last_run_at`** and **`last_run_status`** are `null`, either:
- The cron has never run, or
- The cron script is not calling `POST /api/v1/admin/cron/last-run` after each run, or
- The table `cron_job_runs` is missing / not populated.

---

## 2. Check that the cron is scheduled on the server

On the machine where the cron is supposed to run:

```bash
crontab -l
```

You should see something like:

```
20 11 * * * /path/to/Unreserved/infra/scripts/summary_cron.sh
```

If this line is missing, the cron is **not scheduled**. Add it with:

```bash
crontab -e
# Add: 20 11 * * * /full/path/to/infra/scripts/summary_cron.sh
```

Use the **full path** to `summary_cron.sh` and ensure the script is executable (`chmod +x infra/scripts/summary_cron.sh`).

---

## 3. Check cron logs (when running from crontab)

Cron usually mails output to the user or writes to a log. To capture output to a file, run the script with a redirect, e.g.:

```bash
20 11 * * * /path/to/infra/scripts/summary_cron.sh >> /var/log/unreserved_summary_cron.log 2>&1
```

Then inspect:

```bash
tail -100 /var/log/unreserved_summary_cron.log
```

You should see lines like:
- `Starting summary generation cron job`
- `Summary generation completed successfully` (on success)
- Or `ERROR - Summary generation failed with HTTP status ...` (on failure)

---

## 4. Run the cron script manually (to test)

From the project root:

```bash
# Ensure API is running (e.g. uvicorn app.main:app --host 0.0.0.0 --port 8000)
./infra/scripts/summary_cron.sh
```

- If the API is not reachable, the script exits with a preflight error.
- On success it calls `POST /api/v1/admin/cron/last-run`, so the next **GET /api/v1/admin/cron/status** will show this run.

---

## 5. Check the database directly

Last run info is stored in `cron_job_runs`:

```sql
SELECT job_name, ran_at, status
FROM cron_job_runs
WHERE job_name = 'chat_summary'
ORDER BY ran_at DESC
LIMIT 5;
```

If this table is empty, no run has been recorded (cron not run or script not posting to `/cron/last-run`).

---

## Summary

| What you want to know              | How to check                                                                 |
|------------------------------------|-------------------------------------------------------------------------------|
| Did the cron run recently?         | **GET /api/v1/admin/cron/status** → `last_run_at`, `last_run_status`         |
| Is the cron scheduled?             | **`crontab -l`** on the server                                                |
| What did the last run do?          | Cron log file or **manual run** of `infra/scripts/summary_cron.sh`            |
| Raw last-run data                  | **DB:** `SELECT * FROM cron_job_runs WHERE job_name = 'chat_summary' ORDER BY ran_at DESC LIMIT 5` |

**Note:** The status endpoint reads from the `cron_job_runs` table. The cron script must call **POST /api/v1/admin/cron/last-run** after each run (the provided `summary_cron.sh` does this) so that status reflects the latest run.
