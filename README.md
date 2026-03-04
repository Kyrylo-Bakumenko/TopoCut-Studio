# [Elevation Relief Generator](https://topocut-studio.pages.dev/)

Generates cutter-ready elevation relief models from DEM + satellite imagery. It builds layered contour vectors, nests them onto sheet layouts, and produces preview textures plus composite sheets that overlay raster textures with vector outlines for verification before cutting.

## What it does
- Fetches DEM + imagery for a selected region.
- Slices terrain into contour layers.
- Exports per‑layer DXF vectors and textures.
- Nests layers onto configurable sheet sizes with edge margin and part gap.
- Supports machine/material profiles (e.g. laser vs Cricut workflows) with per-job overrides.
- Generates composite sheets (PNG + DXF) for laser‑cut workflows.
- Groups sheets onto machine bed pages and exports bed-level previews.

## Run & interact

### Backend (FastAPI)
From project root:
- Install deps: `poetry install`
- Start API: `poetry run uvicorn src.web.api.main:app --reload`
- The app now auto-normalizes `PROJ_DATA` / `PROJ_LIB` / `GDAL_DATA` to the active Python env at startup, so shell-level geospatial env leaks no longer break new terminals.

### Frontend (Vite + React)
From src/web/ui:
- Install deps: `npm install`
- Start UI: `npm run dev`

### Web UI flow
1. Choose location and radius on the map.
2. Use the top-right account control to sign in.
3. Choose machine and material profiles (defaults are backend-provided).
4. Optionally save custom machine/material presets to your account.
5. Set width (inches) and layer thickness.
6. Radius and contour interval auto‑synchronize to keep scale consistent.
7. Run the job and inspect:
   - Textures (per layer)
   - Nested Sheets (vector SVG + DXF)
   - Composite Sheets (texture + vector overlay)

### Outputs (results/)
Each job writes to:
```
results/{experiment_name}_{job_id[:8]}/
  textures/            # per-layer PNG textures
  vectors/             # per-layer DXF vectors
  nested/              # nested DXFs + previews + composite PNGs
                      # includes calibration_manifest.json when calibration is enabled
                      # includes bed_*.{dxf,svg,png,json} and bed_manifest.json
  raw_dem.tif
```

## DXF and PNG handling
- DXF: exported in mm units (R2000, LWPOLYLINE), suitable for laser cutters and CorelDRAW.
- PNG textures: raster previews generated per layer and used to build composite sheets.
- Composite sheets: a PNG that overlays texture fills inside the nested vector outlines. Occluded areas are removed based on the layer above to avoid engraving hidden regions.

## Texture normalization (engraving)
Texture previews are contrast‑stretched using global percentiles (computed from the full imagery) and then adjusted with a **gamma curve**. We considered an S‑curve for finer mid‑tone shaping, but gamma was chosen because it’s a single, easy‑to‑tune knob that makes A/B testing simpler and more repeatable (S‑curve planned in a future update).

## Pipeline and methods

### Data sources
- DEM: Copernicus GLO‑30 (global) or USGS 3DEP (US)
- Imagery: NAIP (US) or Sentinel‑2 (global) via STAC + Planetary Computer

### Core pipeline
1. Fetch DEM + imagery for the ROI bounds.
2. Reproject to Web Mercator (EPSG:3857).
3. Slice terrain into contour layers.
4. Generate per‑layer textures by masking imagery with layer polygons.
5. Scale vectors to model width and export per‑layer DXFs.
6. Nest all layers onto sheets with edge margin + inter‑part gap.
7. Export nested DXFs, SVG previews, and composite PNGs.

### Scale & consistency
The model scale is derived from the user’s width and selected radius. The contour interval is tied to layer thickness so physical layers match vertical elevation steps:

$$
\mathrm{scale}_{mm/m} = \frac{\mathrm{width}_{mm}}{2 \cdot \mathrm{radius}_{m}}
$$

$$
\mathrm{contour\ interval}_{m} = \frac{\mathrm{layer\ thickness}_{mm}}{\mathrm{scale}_{mm/m}}
$$

### Nesting
- Polygons are packed with bounding‑box packing.
- Spacing uses $\mathrm{kerf} + \mathrm{part\ gap}$ to keep cuts from colliding.
- Sheet margin is applied by reducing packable area and offsetting placements.

### Bed + sheet layout
- Sheets are first nested as usual.
- Sheets are then grouped onto machine beds using deterministic row-major placement.
- Bed capacity is computed from bed usable area, sheet size, and inter-sheet gap.
- Existing per-sheet outputs are preserved; additional `bed_*` outputs are emitted.

### Composite generation
- The visible region for each layer is computed by subtracting all higher layers.
- Textures are cropped in imagery space and mapped into packed sheet coordinates.
- Vector outlines are drawn on top of the composite raster to verify alignment.
- Layer labels are baked into generated composite PNGs for assembly guidance:
  - Labels use existing `L01`, `L02`, ... format.
  - Placement tries each part's white occlusion zone first.
  - If no room exists, labels are placed outside the part with a thin leader arrow.
  - Minimum label cap height is `1.8mm`.
  - Bundle SVGs include these labels automatically because they embed the composite PNG.

### Calibration workflow
- Calibration uses a gamma ladder strip (default sweep 0.70 to 1.60 in 10 steps).
- The strip is auto-packed onto an existing nested sheet when space is available.
- If no sheet has room, a fallback calibration-only sheet is emitted.
- Composite PNGs include the strip engraving target and labels.
- `nested/calibration_manifest.json` records placement and sweep values for traceability.

## APIs
- `POST /jobs` starts a job
- `GET /jobs` lists all jobs
- `GET /jobs/{id}` fetches job status
- `GET /jobs/{id}/files` lists output files (DXF/PNG/SVG)
- `GET /profiles/defaults` returns built-in machine/material profile defaults
- `POST /auth/signup`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`
- `GET /profiles/custom`, `POST /profiles/custom`, `PUT /profiles/custom/{id}`, `DELETE /profiles/custom/{id}`
- Dev test login is seeded by default: `email=test`, `password=test` (disable with `ENABLE_TEST_LOGIN=0`).

Job history is account-scoped and persisted in the backend DB until explicitly deleted.

## Current tech stack
- Backend: Python, FastAPI, rasterio, shapely, numpy, scipy, matplotlib, ezdxf
- Frontend: React 19, Vite, Ant Design, TanStack Query, Leaflet
- Data: STAC + Planetary Computer; Copernicus GLO‑30, USGS 3DEP, NAIP, Sentinel‑2
