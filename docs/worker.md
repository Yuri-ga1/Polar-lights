# Durable worker (single host, local filesystem)

Run both processes from the repository root, using the same environment,
`POLAR_CONFIG_DIR`, `POLAR_DATA_ROOT` and service account:

```bash
poetry install --extras backend
poetry run uvicorn app.backend.api:create_app --factory --host 127.0.0.1 --port 8000
# Separate terminal/service:
poetry run python -m app.backend.worker
```

API startup no longer starts executors. Cache hits still return 200; cache misses
and `Prefer: respond-async` return the existing 202/status/result contract.
`create_app(start_jobs=True)` remains an explicit development compatibility option.
All coordinators, including this option, share `jobs/coordinator.lock`. Only its
holder recovers or launches jobs. Multiple API processes and standby workers are
supported on one host; shared network filesystems and multi-host operation are not.
The supported crash-recovery deployment is Linux. Other platforms retain Python
process termination but have not been verified for descendant cleanup after SIGKILL.

## Lifecycle and limits

SQLite adds `attempts`, `failures`, `stage`, `heartbeat`, `started`, `finished`,
`next_run`, and private `external` remote identities. Claims, queue admission,
deduplication and retry scheduling use transactional updates. Cancellation is
terminal: late results cannot change a cancelled job into a completed one.
Heartbeat means that the coordinator still observes the execution process; it is
not evidence of scientific progress. `attempts` counts execution sessions,
including remote polling sessions; `failures` counts failed/interrupted attempts.

Public status adds `stage`, `attempts`, `heartbeatAt`, `startedAt`, `finishedAt`,
`nextRunAt`; new statuses are `waiting_external` and `retrying`. No percentage is
invented. These are additive fields, but clients with exhaustive status enums need
updating. Both job routes support `POST /{jobId}/retry` (202): failed/cancelled jobs
create a new job with current settings, subject to queue admission/deduplication.
Old results and errors remain available. Ambiguous remote submissions require
operator reconciliation before retry.

`max_jobs` counts all nonterminal jobs, including delayed retries and remote waits.
`job_workers` bounds subprocesses; only one map/keogram/render/aurora operation is
scheduled at a time, with an additional heavy-resource file lock. This conservative
limit prevents simultaneous backend Chromium/HDF5-heavy jobs. Source locks and
atomic published map files protect shared caches. Separate notebook processes are
not governed by this queue; avoid concurrent notebook writes to the same raw files.

New-operation limits in `backend.toml`:

| Key | Default | Meaning |
|---|---:|---|
| `job_timeout` | 1800 s | Time-series execution and existing source-lock timeout |
| `long_job_timeout` | 43200 s | Map, keogram, aurora and rendering execution session |
| `external_wait_timeout` | 259200 s | SIMuRG generation deadline measured from job creation |
| `job_max_attempts` | 3 | Maximum failed/interrupted attempts, including the initial failure |

Transient source failures (429/502/503/504), unexpected exits and interrupted
workers retry after 60, 120, ... seconds, capped at 900. After the configured number
of failures the job is terminal `failed`. Explicit computation timeouts are terminal
`JOB_TIMEOUT`; retry is a deliberate user action. Validation/data errors are terminal.
Existing partial time-series responses retain their scientific/API semantics.

SIMuRG submission identity is saved before yielding. A not-ready generation yields
`waiting_external` and releases its process and resource lock; the next poll is no
earlier than 60 seconds later. Polling sessions do not consume the failure budget.
The existing client still discovers and reuses matching remote requests. An intent
marker is committed before submission: after an ambiguous interrupted POST the
worker only searches for matching remote requests. If none can be identified it
fails with `REMOTE_SUBMISSION_UNCERTAIN`, avoiding blind duplicate submissions.
Operators must inspect the remote account before submitting the request again.
Remote errors fail explicitly. Local cancellation does not delete a SIMuRG request.

SIGTERM/SIGINT stops scheduling, terminates active subprocesses and retains work
for retry. POSIX executors have their own process groups; forced termination also
kills remaining group members. Linux parent-death signaling stops executors after
a coordinator SIGKILL. Per-job locks prevent overlapping execution during recovery.
Shutdown waits at most `10 + 6 * active_processes` seconds in the runner; supervisors
should allow this grace interval. Hard kills preserve only committed checkpoints.

## Checkpoints and atomic restart boundaries

* Downloads use `.part` files, Range and If-Range with ETag/Last-Modified. Without a
  validator they restart the file; changed validators restart it too. Only a full
  response with consistent size is renamed to the final filename. HDF5 is opened
  for validation before publication; cached HDF5 must be readable. Five transport
  retries per download are bounded by the execution timeout and job retry budget.
* Raw scientific files and atomically merged time-series intervals are reused.
  An interrupted source interval restarts acquisition/processing of that interval.
* HDF5 map publication uses temporary files, including the first ingest. The
  ingestion unit is one file; a killed ingest restarts from the preserved raw file.
* Rendering checkpoints each complete PNG plus its provenance JSON. PNG integrity
  and JSON parsing are checked before reuse. An incomplete pair is regenerated.
* Keogram reduction and response serialization restart as whole stages. The
  existing reducer remains unchanged; it reads slices one by one. There is no
  persistent in-memory numerical accumulator or claim of mid-reducer resumption.
* Final outputs have a committed `artifacts.json` SHA-256 manifest. Recovery checks
  every listed artifact before completing without recalculation; corrupt/missing
  artifacts cause stage execution again. Temporary files are never API results.

Filesystem durability still depends on the local filesystem and hardware honoring
SQLite/fsync/rename semantics. Scientific provenance and pinned effective settings
are retained with outputs. Secrets remain environment-only; remote identity and
internal configuration paths are not returned by public job status.

## Configuration and frontend

API and worker independently watch shared TOML. Dynamic limits affect subsequent
scheduling/admission; operation settings are pinned at job acceptance and survive
retry/restart. Static paths and CORS retain their original values until restart.
Environment is captured at process startup; changing a shell environment does not
update a running service. Invalid TOML retains the last good snapshot.

`GET /api/v1/config/status` requires a configured `POLAR_API_KEY` and matching
`X-API-Key` (even when the API otherwise runs without authentication). It reports
API revision, reload failure and restart-required fields, plus the elected worker's
same diagnostics and heartbeat. A worker heartbeat older than 15 seconds is marked
stale. The existing public config endpoint remains limited to frontend settings.
No remote configuration editing endpoint is added.

The browser saves request/job references in localStorage, scoped to the API base.
Reloading and requesting the same chart resumes polling its saved job. Render
tasks retain their specifications and result links, and resume polling when their
chart panel mounts. This is not a server-wide job history browser. Existing cancel and retry/load controls are kept.
Polling reconnects with 1–15 second backoff and ignores aborted requests; stage,
status and failure reasons are shown. Completed/failed/cancelled references are
cleared; result references are retained until retrieval succeeds. Clearing browser
storage removes these references but does not remove server jobs.

## Upgrade, backup and retention

Stop all old API/worker processes before upgrading. Back up the data root first.
On first startup an additive, `BEGIN IMMEDIATE`-protected SQLite migration adds
columns with defaults and sets `user_version=1`; records, IDs, payloads, old
artifacts and pinned configuration are preserved. Old pinned snapshots obtain
schema defaults for the new settings. Queued jobs continue; interrupted running
jobs enter bounded recovery. Previously terminal `WORKER_RESTARTED` errors remain
historical records and can be retried explicitly. Do not run old and new binaries
against the migrated database (old positional INSERTs are incompatible).

Use SQLite's online backup API for a live database. Do not copy only
`jobs.sqlite3` while WAL mode is active: recent commits may be in `jobs.sqlite3-wal`.
For a consistent database/artifact backup, stop writers, checkpoint WAL, then copy
the entire data root, configuration and renderer assets. Store secrets separately.
Restore these together and start the worker to recover nonterminal records.

There is no automatic deletion. Retain raw caches for expensive-source reuse and
retain job directories/rows for the site's chosen audit period. For manual cleanup,
stop workers/API, back up, then delete only terminal jobs older than the chosen
cutoff, their `job_context`/`job_config` rows and corresponding job directories in
one maintenance operation. Never delete active/waiting jobs, their `.part` files,
or live lock files. Stale `.tmp` files can be removed while services are stopped.
Monitor disk usage and SQLite WAL growth; queue bounds do not bound retained disk.

## Verification

```bash
poetry run python -m pytest tests -q
poetry run ruff check --select E9,F63,F7,F82 app tests
cd frontend
npm test
npm run lint
npm run build
```

Tests include offline fault injection during download/processing, two competing
coordinators, API lifecycle independence, migration, bounded retries, cancellation,
timeouts, remote identity reuse, download resume and frontend reconnection.
Live SIMuRG generation, external scientific sources and real Chromium rendering
require separate deployment checks with credentials/assets; these tests do not
claim to validate their availability or rendered pixels.

Verified in this working tree: 18 backend tests and 5 frontend tests passed;
frontend ESLint and production build passed (Vite reports its existing large-chunk
warning). `ruff check --select E9,F63,F7,F82 app tests`, full Ruff on the new worker,
queue, atomic-publication helper and tests, `compileall`, and `git diff --check`
passed. Full `ruff check app tests` still reports 373 existing diagnostics; comparison
against HEAD found 377 baseline diagnostics and no newly introduced diagnostic.
The repository contained no tracked test directories before this change, so this
is the added regression suite, not a claim that a missing historical suite ran.
