# Polar Lights web workspace — Stage 2

React/TypeScript workspace for the existing FastAPI backend. The library and data controls come from `/api/v1/catalog`; no scientific acquisition, raw-file parsing, or processing runs in the frontend.

## Run with the backend

Use Node 22.12+ and the repository's Python environment with the `backend` optional dependencies installed.

From the repository root:

```sh
.venv/bin/python -m uvicorn app.backend.api:create_app --factory --host 127.0.0.1 --port 8000
```

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` to `http://localhost:8000`. Set `POLAR_BACKEND_URL` when the backend is elsewhere. Components use the central `apiClient`, never a hardcoded backend address.

For a separate API origin, set `VITE_API_BASE_URL` to the origin (without `/api/v1`) and set `POLAR_CORS_ORIGINS=http://localhost:5173` on the backend, matching the actual browser origin. CORS is opt-in in the existing backend; the development proxy does not require CORS. Production hosting must serve `dist/`, proxy `/api`, and serve the bundled `land.geojson` from the application root. Deploy at the domain root. If the backend uses `POLAR_API_KEY`, configure an authenticated same-origin reverse proxy to add the key; do not place secrets in frontend environment variables.

## Run without the backend

```sh
npm run dev:mock
```

MSW intercepts the same API routes. The header identifies synthetic data. Use `2026-01-19T00:00:00Z` and `2026-01-19T01:00:00Z` for maps, and a range on January 19, 2026 for time series/keograms. Dates in the year 2000 demonstrate errors. Mock requests pass through `202 → processing → completed → result`, including Arrow map payloads. Cancel stops polling and sends DELETE to the existing job endpoint.

`src/mocks/catalog.json` is a snapshot of `CatalogResponse.model_validate(catalog()).model_dump(exclude_none=True)` from the backend. The Python contract test checks for drift. This snapshot is only imported by MSW and tests; the production library always comes from the API.

## Use the workspace

- Click a library product, or drag it onto the canvas. Unavailable products are disabled.
- Select a card and complete its required fields in the inspector. All dates are interpreted as UTC, independent of the browser timezone. Press **Build chart** to request data.
- Each card has independent draft parameters, last-applied parameters, request status, errors, and results. Editing parameters does not send a request. Errors preserve the previous valid visualization. Retry uses the current draft.
- Drag the header to move, pull an edge/corner to resize, and use the header buttons to duplicate or delete. Click empty canvas space to deselect.
- Title, subtitle, axes, lines, markers, fonts, margins, legend, palette, and the full colorbar editor are local styling. Map hover uses deck.gl picking on local arrays; no hover request is sent.
- Workspace specifications save to localStorage. Reload restores cards, drafts, last-applied parameters, style, layout, and selection. Datasets and request statuses are never persisted. Press **Build chart** to fetch restored cards. Duplicates copy the spec, receive a new ID, and likewise wait for an explicit build.

## Validation

```sh
npm run build
npm test
npm run lint
npm run format:check
npx playwright install chromium
npm run test:e2e
```

To use an existing Chromium binary, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`. Browser tests use software WebGL when hardware acceleration is unavailable.

From the repository root, validate the real API contract:

```sh
.venv/bin/python frontend/tests/test_backend_contract.py
```

To run the same browser workflow against the real backend and isolated synthetic storage, start this server from the repository root:

```sh
.venv/bin/python frontend/tests/backend_fixture.py
```

Then, with port 5173 free:

```sh
cd frontend
POLAR_REAL_API=1 npm run test:e2e
```

To validate the production bundle against this server, run `npm run build`, then `POLAR_REAL_API=1 POLAR_PREVIEW=1 npm run test:e2e`. The MSW-only error scenario is skipped in real-API mode.

On Windows use `.venv\Scripts\python.exe` and set environment variables with PowerShell, for example `$env:POLAR_REAL_API='1'`. The fixture and contract test look for Python Playwright's Chromium in `.cache/playwright` by default; set `PLAYWRIGHT_BROWSERS_PATH` to use another installation. Install it with `python -m playwright install chromium` in the same environment. The fixture copies MapLibre assets from the installed frontend package, seeds only its own temporary directory, and removes that directory on exit. The contract test runs an actual asynchronous render job and downloads its artifacts. `POLAR_EXTERNAL_SERVER=1` runs browser tests against an already started frontend server.

## Advanced workspace

- Shift-click or drag a selection rectangle; groups select, move and resize together. The inspector shows only layout actions for a multiple selection. Use all six alignments, horizontal/vertical distribution, grouping, ordering and lock/unlock.
- Free canvas has eight resize handles, numeric geometry, grid snapping and alignment guides. Grid mode preserves the free positions, data, styles and loaded results when switching back.
- Undo/redo stores up to 80 UI snapshots. Request status, scientific results and render-job polling are separate from history. Delete, copy/paste, duplicate, undo/redo and preset export have Ctrl/Cmd shortcuts. Text fields retain their editing shortcuts; focused cards move with arrow keys (Shift for 20 pixels).
- Map capabilities come from the catalog. Geographic, north-polar and south-polar displays are available when projection is supported. No geomagnetic/MLT mode is advertised without backend support. Polar display projects already loaded geographic coordinates and does not perform scientific transformations.
- Availability is advisory. The map timeline debounces by 350 ms and aborts superseded requests; stale responses cannot replace a newer frame. It reuses a shared in-memory LRU bounded to eight slices / 64 MiB and a 60-second freshness window. Neighbour prefetch is deliberately omitted: visiting a frame can trigger expensive backend acquisition. Scientific arrays are never stored in presets or localStorage.
- Presets export as `schemaVersion: 2`; Stage 1 `version: 1` / `schemaVersion: 1` presets migrate through Zod validation. Unknown versions, duplicate IDs and invalid selections are rejected before changing the workspace. Import restores specifications; Build chart reloads data explicitly.
- Card exports: PNG, PDF, JSON and SVG for loaded Plotly charts. WebGL maps have PNG/PDF only. Workspace PNG/PDF preserve positions, sizes, order and rendered appearance; JSON preserves specifications. Raster exports are limited to 32 megapixels. PDF embeds the rendered PNG; Plotly SVG uses vector output. Downloaded scientific data are not embedded in JSON.
- Library and inspector can be collapsed; small screens use overlay panels and the canvas scrolls horizontally. Library buttons provide a keyboard/click alternative to dragging.

## Server map series

The existing `/api/v1/render-assets` and `/api/v1/map-render-jobs` API is used unchanged. MapLibre **5.6.1** is pinned in both frontend and Python renderer; Playwright **1.55.0** is pinned for reproducible browser execution. Install backend assets with `python -m app.backend.setup_render`, then install Chromium with `python -m playwright install chromium`. In deployment, configure `POLAR_RENDER_ASSETS` as needed.

Select a supported map, open **Server map series**, enter up to 48 UTC timestamps and submit. The UI snapshots the render specification and displays queued/processing/completed/failed/cancelled status, cancellation and artifact links, including the `spec.json` manifest. The backend does not publish numeric progress, so no percentage is invented. Server rendering uses the existing fixed geographic blue/red renderer; use card export for the interactive card's custom style. Preview uses the backend's exact pinned assets and the currently loaded frame.

## Implementation and contract decisions

- Requests are exactly `{productId, parameters}`. The backend forbids `chartId` and other extra fields; IDs remain in client state.
- `parameterSchema` is an array of `datetime`, `select`, and `multiselect` descriptors, not JSON Schema. Required flags, default values, option types, and availability come from the catalog. Schema option numbers remain JSON numbers.
- Backend graph types determine renderer and library grouping. No unsupported products are added. Availability is advisory: the existing backend may acquire data not yet in its local index.
- Maps default to Arrow, as specified by the backend. Arrow IPC schema metadata uses JSON-encoded values. Nulls survive decoding. Time series and keograms currently return JSON; no invented Arrow time-series endpoint is used.
- `nullPolicy`, column frequency, and offset distinguish `missing_data` from `no_sample_expected`. Off-grid nulls are omitted from a column's plotted sample grid; expected missing samples stay as gaps. All response metadata remains accessible in the card footer.
- MapLibre plus deck.gl render point maps with WebGL. Natural Earth land geometry is bundled so maps do not depend on a tile service. Plotly has a separate lazy bundle for line plots and latitude × time keograms. Resize observers update renderer size without fetching data.
- TanStack Query caches catalog, availability and time-series results; map slices use the bounded LRU. AbortController and per-request identity protect against stale responses; deleting a card releases its renderer and cache ownership. MSW, Arrow decoding, renderers, batch controls and image/PDF exporters are lazy-loaded. Large visualization bundles load only when needed.
- No scientific backend implementation or API contract was changed for Stage 2.

Basemap: Natural Earth 1:110m land, public domain, from [natural-earth-vector](https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_land.geojson). Renderer integration follows [deck.gl MapboxOverlay](https://deck.gl/docs/api-reference/mapbox/mapbox-overlay); browser mocking follows [MSW browser integration](https://mswjs.io/docs/integrations/browser/).
