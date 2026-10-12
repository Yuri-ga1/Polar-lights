# Docker Compose: one Linux host

The production stack is Nginx/static Vite assets, the HTTP API, and the standalone
worker. API restarts do not restart worker processes. All durable state is on
local host bind mounts; SQLite/WAL and file locks require a local filesystem, not
NFS or a multi-host deployment. Run commands from the repository root. Supported
validation target: Ubuntu 24.04, Linux amd64, Docker Engine with Compose v2.39+.
Allow at least 8 GB RAM and sufficient space for scientific data and image builds.

## First start

```bash
cp .env.example .env
# Set POLAR_UID/POLAR_GID in .env to the output of these commands:
id -u
id -g
mkdir -p files/raw files/processed files/maps files/jobs results logs
# Existing directories must be writable by that UID/GID; do not chmod 777.
docker compose config --quiet
docker compose build
docker compose up -d --wait --wait-timeout 180
docker compose ps
docker compose logs --tail=100 -f api worker
```

Open http://127.0.0.1:8080. Only Nginx is published, on loopback. The API is reachable
only inside the Compose network. A remote operator can use an SSH tunnel:
`ssh -L 8080:127.0.0.1:8080 user@host`. Images run as non-root. The default host UID
is 1000; Docker does not fix ownership of existing bind mounts. Use your service
account's UID/GID consistently, including one-off maintenance containers. If Docker
created root-owned empty mount directories, stop services and correct ownership of
those directories explicitly before proceeding.

`docker compose up -d --build` also builds and starts all services. It can recreate
the worker when its image changes: use the per-service commands below for rollouts.

Images use explicit Python 3.12.12, Node 22.14.0 and Nginx 1.28.0 version tags.
Poetry 2.2.1 installs only locked main dependencies plus the backend extra; the
`ionex` Git revision comes from poetry.lock. Native compilation is in a separate
stage. Runtime includes geospatial/HDF5/OpenJPEG and Playwright Linux libraries.
Playwright **1.55.0** installs its matching Chromium at build time. MapLibre
**5.6.1** JS/CSS are checked against committed SHA-256 hashes, and the rendering
series renderer uses bundled Canvas code and Natural Earth land geometry with
no remote tiles/fonts. There are no browser downloads at startup.
Tags and Debian package repositories are not immutable snapshots; for exact binary
reproducibility in a release, record image digests, mirror images/packages and
promote the tested built images. Rebuild deliberately for security updates.

Inspection found no Selenium/webdriver calls in the current `app/` sources, though
Selenium and webdriver-manager remain locked dependencies. The image does not
install a ChromeDriver or promise to support notebook code that invokes Selenium.
If such a source is introduced, pin and install its matching driver/browser during
build; do not let webdriver-manager download executables during a job.

## Health, settings and resources

```bash
curl --fail http://127.0.0.1:8080/api/v1/health
docker compose exec api python -m deploy.healthcheck ready
docker compose exec worker python -m deploy.healthcheck worker
# If POLAR_API_KEY is configured, curl must send X-API-Key as well.
```

`health` is API liveness. `ready` returns 503 unless SQLite can be read and the
coordinator heartbeat is younger than 20 seconds. API container health uses
liveness, worker container health checks heartbeat plus SQLite. Frontend health
only checks the static server. Compose `--wait` is not a substitute for the ready
probe. Health failures report state; Docker does not automatically restart an
unhealthy but running process.

Edit host `config/*.toml` directly (the whole directory is mounted read-only into
both services, so atomic editor replacements work). Dynamic changes apply to new
operations; jobs retain their accepted configuration snapshot across retries.
Invalid edits keep each process's last valid snapshot. Static paths/CORS require
recreation. `GET /api/v1/config/status` requires `POLAR_API_KEY` plus a matching
`X-API-Key`, and reports API/worker revisions, reload errors and restart requirements.
Worker status updates every five seconds. Changing `.env` requires recreating the
affected services: `docker compose restart` does not apply a new environment.

CPU/RAM/shared-memory limits are in `.env.example`; scientific BLAS/OpenMP threads
are capped at one per process. `config/backend.toml` controls `job_workers` (default
2), queue length, operation deadlines and retry budget. The existing worker permits
**one heavy map/keogram/render job at a time**, so browser concurrency is capped at
one; this is intentionally not an independent configurable pool. Lower
`job_workers` to 1 on small hosts. Waiting SIMuRG jobs release their process slot.
Do not increase concurrency beyond available RAM. Worker `shm_size` defaults to
1 GB. The 420-second supervisor grace covers the code's bounded shutdown even at
the schema maximum of 64 workers; normal two-worker shutdown is bounded by 22 seconds.

Logs rotate using `config/logging.toml` (default 30 days, 20 MiB per file); Docker
stdout logs are also bounded. Job artifacts are retained until explicit maintenance.
Disk use is not bounded by queue limits. Choose `JOB_RETENTION_DAYS` and schedule
an offline maintenance window as described below; this value does not silently
delete data in a running worker.

## Per-service upgrade and shutdown

```bash
# UI rollout; active computation continues.
docker compose build frontend
docker compose up -d --no-deps frontend
# API rollout; worker keeps its running image and active jobs.
docker compose build api
docker compose up -d --no-deps api
# Worker rollout deliberately interrupts compute, then recovers persisted work.
docker compose up -d --no-deps --force-recreate worker
# Clean stop, keeping containers and all data:
docker compose stop
# Resume:
docker compose start
```

Nginx re-resolves the API service name after container replacement. `init: true`
forwards signals and reaps descendants. On SIGTERM the worker stops scheduling,
terminates executor process groups, and records retry state. SIGKILL/host reboot
recover only persisted checkpoints: unfinished acquisition/processing/keogram
stages may run again. Arbitrary RAM computation does not resume. Cancellation
remains terminal. See [worker.md](worker.md) for exact checkpoint boundaries.

Do not use `docker compose down` for ordinary per-service rollouts. It stops the
worker too. It does preserve these bind mounts, but does not preserve RAM. An API
and worker version change that alters the database contract requires stopping both,
backing up, and upgrading them together. Additive SQLite migrations run under the
schema lock on startup; no separate migration command is needed. Do not run old
binaries against a newer incompatible schema or assume rollback needs only an image.

## Consistent backup and restore

Stop all writers, including notebooks and any manually started pipeline. Back up
configuration and outputs with the database. Never copy only the SQLite main file
while its WAL is live. With stopped writers, this checkpoints WAL and archives the
entire durable state; the one-off API container runs only the supplied command:

```bash
docker compose stop api worker
docker compose run --rm --no-deps api python -c 'import sqlite3; c=sqlite3.connect("files/jobs/jobs.sqlite3"); print(c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()); c.close()'
mkdir -p backups
tar -czf "backups/polar-$(date -u +%Y%m%dT%H%M%SZ).tgz" config files/raw files/processed files/maps files/jobs results logs
docker compose start api worker
```

The checkpoint result's first number must be 0; if busy, find remaining writers
before backing up. Keep `.env`/credentials separately in protected secret storage.
Record the deployed image digests with each backup; renderer assets live in the
image. Restore to a fresh checkout with stopped containers: inspect the archive,
extract into that checkout (`tar -xzf /path/to/backup.tgz -C /path/to/checkout`), set
matching UID/GID and image versions, then `docker compose up -d --wait`. Do not
extract over a running deployment or mix an old database with newer artifact files.

## Explicit job cleanup

Back up first, stop API/worker and any other writers, then preview:

```bash
docker compose stop api worker
docker compose run --rm --no-deps worker python -m deploy.retention
# After reviewing the preview:
docker compose run --rm --no-deps worker python -m deploy.retention --apply
docker compose start api worker
```

Use `--days 30` to override `JOB_RETENTION_DAYS` from `.env`. The tool locks out the
coordinator and deletes only old terminal rows, their config/context rows and their
job directories. It does not remove raw/map caches, results, active jobs, or lock
files. API writers must be stopped by the operator. Filesystem deletion and SQLite
are not one transaction: an interrupted cleanup may leave terminal rows pointing
to removed artifacts; rerun cleanup or restore the backup. Never use `down -v`,
recursive data deletion or volume pruning as routine maintenance.

## Public access

The default is a private loopback deployment. Before exposing it, put an HTTPS
reverse proxy with **server-side user authentication and authorization** in front
of the entire site and `/api/` (for example an organization OIDC gateway), restrict
origin access to that gateway, and enforce access to expensive job creation there.
TLS certificates and gateway identity configuration depend on the host/site and
are not provisioned by this stack. API key injection by a trusted gateway is only
service authentication; it does not authenticate users. Never put a shared secret
in Vite build variables or committed files. The app does not implement per-user
job ownership: authorized users currently share the same job namespace. Use this
stack for one trusted group; multi-tenant deployment requires additional authorization.

Nginx preserves API status codes, request IDs and binary Arrow responses, disables
proxy buffering, caps request bodies at 2 MiB, and has a finite 300-second read
idle timeout. Use background job requests (`Prefer: respond-async`) for long work.
The proxy timeout does not stop durable jobs. Gzip covers text assets/JSON, not
Arrow; SPA fallback applies only outside `/api/`.

## Development and verification

Local Poetry/Vite development remains unchanged; see the README. No production
service uses a dev server. Node >=22.12 is required for local frontend builds.

```bash
poetry run python -m unittest discover -s tests -v
poetry run python -m deploy.smoke --skip-browser
# Inside the production image, offline and non-root:
docker run --rm --init --network none --shm-size=1g polar-lights-backend:local python -m deploy.smoke
# Separate temporary bind mounts/project, port 18080; never production data:
python3 deploy/integration.py
```

CI (`.github/workflows/docker.yml`) validates Compose, builds both images, runs
regressions and native HDF5/Arrow/time-series/keogram plus offline Chromium/PNG
checks, then runs isolated lifecycle tests. These force API/frontend recreation
while an executor is active (held at the heavy-resource lock), validate TOML reload
and pinned config, kill/recreate the worker, cancel a job and check persistence
across stop/down/up. This deterministic fault injection does not reproduce a kill
at every possible scientific instruction. The SPA reload check verifies HTTP
serving and retained result URLs, not a full interactive browser UI test.

External SIMuRG generation and other live scientific sources require network,
credentials and operator validation. Cartopy basemap datasets or source data not
already cached may still require external downloads during a scientific operation;
container startup and the offline world-map render smoke do not.

Local validation on 2026-10-12:

- Standalone Docker Compose 2.39.4: `config --quiet` passed.
- `python -m unittest discover -s tests -v`: all 5 tests passed.
- `python -m deploy.smoke`: native imports, HDF5/Arrow, time series, keogram,
  and offline Chromium/MapLibre PNG via SwiftShader passed in the host virtualenv
  (Python 3.13, Playwright 1.55.0). Chromium required execution outside the agent
  sandbox; temporary config/assets were used. This is not a container-image test.
- Ruff on added Python files, fatal-error checks across app/deploy/tests,
  compileall and `git diff --check` passed.
- Docker Engine is absent on the implementation host. Image build/start,
  container permissions and `deploy/integration.py` could not run here. CI has
  been added but has not been observed running. Host Node 18 is below the frontend
  requirement; the Docker build uses Node 22.14. Live external source tests and
  interactive browser job reconnection remain deployment acceptance checks.

References: [Compose service options](https://docs.docker.com/reference/compose-file/services/),
[Playwright browser installation](https://playwright.dev/python/docs/browsers).
