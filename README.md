# India Industrial Intelligence Platform

A Web GIS application for exploring, filtering, and analysing industrial sites
across India, built on top of the `industrial-data` geospatial pipeline.

> **Current milestone** — the web application runs against a synthetic
> 30-site dataset.  The backend is architected to switch to live PostGIS data
> (populated by the `industrial-data` pipeline) by setting one environment
> variable.  No other code change is required.

---

## Repository layout

```
Remote-sensing-OSM/
├── industrial-data/          # geospatial data pipeline (Phase 1–8 complete)
│   ├── docker-compose.yml    # PostGIS 16-3.4 container
│   ├── sql/                  # schema.sql · indexes.sql · functions.sql
│   ├── scripts/              # run_boundaries.py · run_osm_district.py
│   │                         # run_government_ingest.py · run_entity_resolution.py
│   ├── src/                  # Python pipeline source
│   └── requirements.txt
│
└── industrial-gis/           # Web GIS application (this milestone)
    ├── backend/              # FastAPI + SQLAlchemy
    │   ├── app/
    │   │   ├── main.py       # ASGI app, CORS from env
    │   │   ├── config.py     # Settings singleton (DATA_MODE, DATABASE_URL, ALLOWED_ORIGINS)
    │   │   ├── db.py         # SQLAlchemy engine + session factory
    │   │   ├── api/routes.py # All /api/* endpoints
    │   │   └── services/
    │   │       ├── catalog.py         # Synthetic dataset + dispatcher
    │   │       └── postgis_repo.py    # PostGIS queries (ST_Intersects, ST_MakeEnvelope)
    │   ├── tests/
    │   │   ├── test_health.py
    │   │   └── test_endpoints.py
    │   └── requirements.txt
    │
    └── frontend/             # React 18 + TypeScript + Vite + Leaflet
        ├── src/
        │   ├── App.tsx              # Central state, health probe, offline banner
        │   ├── components/
        │   │   ├── MapView.tsx      # Leaflet map, MarkerCluster, bbox emission
        │   │   ├── Header.tsx       # Search + filters + active-filter pills
        │   │   ├── StatisticsCards.tsx
        │   │   ├── IndustryDetails.tsx
        │   │   ├── AnalyticsPanel.tsx
        │   │   ├── LoadingState.tsx
        │   │   └── ErrorState.tsx
        │   ├── services/api.ts      # Central API client (VITE_API_BASE_URL)
        │   ├── types/industrial.ts  # All TypeScript interfaces
        │   └── hooks/useDebounce.ts
        └── vite.config.ts           # Proxy: /api → http://127.0.0.1:8000
```

---

## Architecture

```
Browser (http://localhost:5173)
  │
  │  React 18 + TypeScript + Vite
  │  Leaflet 1.9 + leaflet.markercluster
  │
  ├── /api/*  (proxied by Vite dev server)
  │              ↓
  │         FastAPI  (http://localhost:8000)
  │         uvicorn · Python 3.11+
  │              ↓
  │    DATA_MODE=synthetic  →  in-memory 30-site dataset
  │    DATA_MODE=postgis    →  industrial_sites (PostGIS)
  │                                   ↑
  │                        populated by industrial-data pipeline
  │
  └── PostGIS 16-3.4 (docker-compose in industrial-data/)
        database: industrial_data
        tables:   industrial_sites · osm_industries
                  industrial_entity_matches · states · districts
```

---

## Prerequisites

| Tool | Minimum version | Notes |
|---|---|---|
| Python | 3.11 | 3.13 confirmed working |
| Node.js | 18 | 20+ recommended |
| npm | 9 | bundled with Node |
| Docker | 24 | only needed for PostGIS mode |

---

## 1 — Development setup (synthetic mode — no database required)

### 1.1 Backend

```powershell
# From the repository root
cd industrial-gis

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# Install dependencies
pip install -r backend/requirements.txt

# Start the API server (DATA_MODE defaults to 'synthetic')
python -m uvicorn backend.app.main:app --reload --port 8000 --host 127.0.0.1
```

The server logs `data_mode=synthetic` on startup.

### 1.2 Frontend

```powershell
# In a second terminal
cd industrial-gis/frontend

npm install
npm run dev
```

### 1.3 Open the application

| URL | Purpose |
|---|---|
| http://localhost:5173 | Web GIS application |
| http://localhost:8000/api/health | Backend health check |
| http://localhost:8000/api/docs | Interactive API documentation (Swagger UI) |

---

## 2 — PostGIS mode (live data from the pipeline)

### 2.1 Start the PostGIS container

The Docker Compose file is in `industrial-data/`.

```powershell
cd industrial-data

# Copy the example env file and adjust if needed
copy .env.example .env

# Start PostGIS 16-3.4 (service name: postgis, container: industrial-data-postgis)
docker compose up -d

# Verify it is healthy
docker compose ps
```

Default credentials (from `.env.example`):

| Setting | Default |
|---|---|
| `POSTGRES_DB` | `industrial_data` |
| `POSTGRES_USER` | `industrial` |
| `POSTGRES_PASSWORD` | `industrial` |
| `POSTGRES_PORT` | `5432` |

The SQL scripts in `industrial-data/sql/` are mounted as
`/docker-entrypoint-initdb.d` and run automatically on first container start.
They create the PostGIS extension, all tables, indexes, and spatial helper
functions — **do not run them manually**.

### 2.2 Run the data pipeline

```powershell
# Still inside industrial-data/
pip install -r requirements.txt

# Phase 1 — boundaries (India / states / districts)
python scripts/run_boundaries.py

# Phase 2 — OSM extraction (one district at a time)
python scripts/run_osm_district.py --district-name "Ahmedabad" --dry-run

# Phase 3 — government dataset ingestion
python scripts/run_government_ingest.py --input path/to/source.csv \
    --table-name government_industries_source_a \
    --source-id-column source_id --name-column name \
    --industry-type-column industry_type --dry-run

# Phase 4 — entity resolution → populates industrial_sites
python scripts/run_entity_resolution.py \
    --government-table government_industries_source_a --dry-run
```

Remove `--dry-run` to write to the database.

### 2.3 Switch the backend to PostGIS

```powershell
cd industrial-gis

# Create backend/.env from the example
copy backend\.env.example backend\.env
```

Edit `backend/.env`:

```dotenv
DATA_MODE=postgis
DATABASE_URL=postgresql+psycopg2://industrial:industrial@localhost:5432/industrial_data
ALLOWED_ORIGINS=http://localhost:5173
```

Restart the backend — the startup log will show `data_mode=postgis` and the
status bar badge in the UI will change from **🔬 Synthetic** to **🗄 PostGIS**.

---

## 3 — Environment variables

### Backend (`industrial-gis/backend/.env`)

| Variable | Default | Required |
|---|---|---|
| `DATA_MODE` | `synthetic` | No |
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/industrial_gis` | Only in `postgis` mode |
| `ALLOWED_ORIGINS` | `*` (all origins) | No — restrict in production |

See [`backend/.env.example`](industrial-gis/backend/.env.example) for the full reference.

### Frontend (`industrial-gis/frontend/.env.local`)

| Variable | Default | Notes |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` (Vite proxy) | Override to connect directly to the backend |

See [`frontend/.env.example`](industrial-gis/frontend/.env.example) for usage.

---

## 4 — API reference

All endpoints are prefixed with `/api`.  Interactive docs at
`http://localhost:8000/api/docs`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | `{"status":"ok","data_mode":"synthetic"\|"postgis"}` |
| `GET` | `/api/industries` | GeoJSON FeatureCollection with optional filters |
| `GET` | `/api/industries/search` | Full-text search (requires `?q=`) |
| `GET` | `/api/industries/{site_id}` | Single site GeoJSON Feature |
| `GET` | `/api/statistics` | Aggregate counts by state, type, confidence |
| `GET` | `/api/filters/options` | Dropdown values for all filter fields |
| `GET` | `/api/boundaries/{level}` | Boundary GeoJSON (`india` / `states` / `districts`) |

### Bbox parameter

All list endpoints accept `?bbox=west,south,east,north` (EPSG:4326).
In PostGIS mode this uses `ST_Intersects + ST_MakeEnvelope` against the
GIST-indexed `geometry` column.  In synthetic mode it filters the in-memory
dataset geometrically.

---

## 5 — Running tests

### Backend

```powershell
cd industrial-gis
python -m pytest backend/tests/ -v
```

Current result: **32/32 passed** (no database required — all tests run against
`DATA_MODE=synthetic`).

### Frontend — TypeScript compilation

```powershell
cd industrial-gis/frontend
npx tsc --noEmit
```

Current result: **0 errors**.

### Frontend — production build

```powershell
cd industrial-gis/frontend
npm run build
```

Current result: **built in ~1.6 s, 369 kB JS bundle**.

---

## 6 — Feature status

### Completed (this milestone)

| Feature | Status |
|---|---|
| Interactive Leaflet map centred on India | ✅ |
| CartoDB Positron basemap | ✅ |
| MarkerCluster (colour-coded by density) | ✅ |
| Industry-type emoji markers | ✅ |
| Confidence legend (bottom-left overlay) | ✅ |
| Click marker → IndustryDetails side panel | ✅ |
| Match-score animated bar | ✅ |
| OSM / Government provenance links | ✅ |
| Debounced auto-search (420 ms) | ✅ |
| State / District / Industry type / Status filters | ✅ |
| District cascade (filtered by selected state) | ✅ |
| Active filter pills with individual clear buttons | ✅ |
| Statistics cards (6 metrics with hover animation) | ✅ |
| Analytics panel (Sites by State / Industry bar charts) | ✅ |
| Bbox-based map loading (debounced 650 ms on moveend) | ✅ |
| Backend health probe + offline banner + Retry | ✅ |
| Dynamic data-mode badge (Synthetic / PostGIS) | ✅ |
| Zero-results overlay | ✅ |
| CORS from `ALLOWED_ORIGINS` env var | ✅ |
| `DATA_MODE` dispatcher (synthetic ↔ PostGIS, no code change) | ✅ |
| PostGIS repository with ST_Intersects + ST_MakeEnvelope | ✅ |
| TypeScript strict mode, 0 errors | ✅ |
| 32 backend pytest tests | ✅ |
| Vite production build | ✅ |

### Remaining work (future phases)

| Item | Notes |
|---|---|
| Populate `industrial_sites` with real OSM + government data | Run the `industrial-data` pipeline phases 2–4 |
| State / district boundary GeoJSON layers on map | `/api/boundaries/*` endpoints exist; add Leaflet GeoJSON layer |
| Confidence-level filter dropdown | Backend already supports `?confidence=` |
| Pagination / virtual loading for >500 sites | Add `limit` / `offset` or cursor to `/api/industries` |
| GeoJSON / CSV export of filtered results | New endpoint or client-side blob download |
| Production deployment | Nginx reverse proxy, gunicorn workers, static frontend build |
| Satellite / remote-sensing integration | Future phase |

---

## 7 — Current data source

> **The web application currently uses synthetic data.**
>
> The 30-site dataset in `backend/app/services/catalog.py` is a hand-crafted
> representative sample.  It is labelled `data_sources: ["openstreetmap", "government"]`
> for display purposes only — these records were **not** extracted from the real
> OSM database or any government registry.
>
> The `/api/health` response includes `"data_mode": "synthetic"` so this is
> always explicit.  The badge in the application UI also shows **🔬 Synthetic**.
>
> Switch to `DATA_MODE=postgis` after running the `industrial-data` pipeline to
> work with real data.

---

## 8 — Troubleshooting

**Backend won't start — `DATA_MODE` error**
: Set `DATA_MODE=synthetic` or `DATA_MODE=postgis` in your environment or
  `backend/.env`.  Any other value is rejected at startup.

**`DATABASE_URL is not configured`**
: This appears only in `postgis` mode.  Either set the variable or switch to
  `DATA_MODE=synthetic`.

**Frontend shows "Backend unavailable" banner**
: The backend is not running or not reachable on port 8000.  Check that
  `uvicorn` is running and the Vite proxy target matches (`http://127.0.0.1:8000`
  in `vite.config.ts`).

**Markers not visible on map**
: Open browser devtools → Network.  If `/api/industries` returns 0 features,
  check your bbox / filter settings or click **Reset**.

**PostGIS container not healthy**
: Run `docker compose logs postgis` inside `industrial-data/` and check for
  authentication or volume errors.

---

## 9 — Data pipeline (industrial-data)

The `industrial-data` module is a separate, self-contained pipeline that
produces the `industrial_sites` PostGIS table consumed by this web application.

| Phase | What it does | Script |
|---|---|---|
| 1 | India / state / district boundary ingestion (GeoBoundaries) | `run_boundaries.py` |
| 2 | OSM industrial extraction via Overpass API | `run_osm_district.py` |
| 3 | Government dataset ingestion (tabular CSV) | `run_government_ingest.py` |
| 4–5 | Entity resolution → master `industrial_sites` table | `run_entity_resolution.py` |
| 6 | Data-quality report (`exports/data_quality_report.json`) | auto-generated |
| 7 | Temporal tracking (`first_seen`, `last_seen`, `operational_status`) | merged on rerun |
| 8 | Spatial helper functions + duplicate-cluster detection | PostGIS functions |

See [`industrial-data/README.md`](industrial-data/README.md) for full pipeline documentation.
