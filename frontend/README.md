# Polar Lights web workspace — Stage 1

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
- Title, legend, palette, and color limits are local styling. Map hover uses deck.gl picking on local arrays; no hover request is sent.
- Workspace specifications save to localStorage. Reload restores cards, drafts, last-applied parameters, style, layout, and selection. Datasets and request statuses are never persisted. Press **Build chart** to fetch restored cards. Duplicates copy the spec, receive a new ID, and likewise wait for an explicit build.

## Validation

```sh
npm run build
npm test
npx playwright install chromium
npm run test:e2e
```

To use an existing Chromium binary, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`. Browser tests use software WebGL when hardware acceleration is unavailable.

From the repository root, validate the real API contract:

```sh
.venv/bin/python -m unittest tests.test_web_api_contract
```

To run the same browser workflow against the real backend and isolated synthetic storage, start this server from the repository root:

```sh
PYTHONPATH=. .venv/bin/python tests/web_backend_fixture.py
```

Then, with port 5173 free:

```sh
cd frontend
POLAR_REAL_API=1 npm run test:e2e
```

To validate the production bundle against this server, run `npm run build`, then `POLAR_REAL_API=1 POLAR_PREVIEW=1 npm run test:e2e`. The MSW-only error scenario is skipped in real-API mode.

The temporary server seeds only its own temporary directory, uses the existing storage/service/API, and removes the data on exit. The API contract test separately exercises actual async jobs via `Prefer: respond-async`.

## Implementation and contract decisions

- Requests are exactly `{productId, parameters}`. The backend forbids `chartId` and other extra fields; IDs remain in client state.
- `parameterSchema` is an array of `datetime`, `select`, and `multiselect` descriptors, not JSON Schema. Required flags, default values, option types, and availability come from the catalog. Schema option numbers remain JSON numbers.
- Backend graph types determine renderer and library grouping. No unsupported products are added. Availability is advisory: the existing backend may acquire data not yet in its local index.
- Maps default to Arrow, as specified by the backend. Arrow IPC schema metadata uses JSON-encoded values. Nulls survive decoding. Time series and keograms currently return JSON; no invented Arrow time-series endpoint is used.
- `nullPolicy`, column frequency, and offset distinguish `missing_data` from `no_sample_expected`. Off-grid nulls are omitted from a column's plotted sample grid; expected missing samples stay as gaps. All response metadata remains accessible in the card footer.
- MapLibre plus deck.gl render point maps with WebGL. Natural Earth land geometry is bundled so maps do not depend on a tile service. Plotly has a separate lazy bundle for line plots and latitude × time keograms. Resize observers update renderer size without fetching data.
- TanStack Query caches catalog, availability, and per-card data. Successful results can be reused for 60 seconds after an explicit Build. AbortController and per-request identity protect against stale responses; deleting a card releases its renderer and cached results. MSW, Arrow decoding, and renderers are lazy-loaded.
- The API's render jobs, projection choices, and Stage 2 layout tools are outside Stage 1. No backend source files were changed.

Basemap: Natural Earth 1:110m land, public domain, from [natural-earth-vector](https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_land.geojson). Renderer integration follows [deck.gl MapboxOverlay](https://deck.gl/docs/api-reference/mapbox/mapbox-overlay); browser mocking follows [MSW browser integration](https://mswjs.io/docs/integrations/browser/).
