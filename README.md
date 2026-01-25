# Elevation Relief Generator

Generates laser‑cuttable elevation relief models from DEM + satellite imagery. It builds layered contour vectors, nests them onto sheet layouts, and produces preview textures plus composite sheets that overlay raster textures with vector outlines for verification before cutting.

## What it does
- Fetches DEM + imagery for a selected region.
- Slices terrain into contour layers.
- Exports per‑layer DXF vectors and textures.
- Nests layers onto configurable sheet sizes with edge margin and part gap.
- Generates composite sheets (PNG + DXF) for laser‑cut workflows.

## Run & interact

### Backend (FastAPI)
From project root:
- Create env (optional): `conda env create -f environment.yml` or use your existing Python env.
- Start API: `uvicorn src.web.api.main:app --reload`

### Frontend (Vite + React)
From src/web/ui:
- Install deps: `npm install`
- Start UI: `npm run dev`

### Web UI flow
1. Choose location and radius on the map.
2. Set width (inches) and layer thickness (1/8" or 1/16").
3. Radius and contour interval auto‑synchronize to keep scale consistent.
4. Run the job and inspect:
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
  raw_dem.tif
```

## DXF and PNG handling
- DXF: exported in mm units (R2000, LWPOLYLINE), suitable for laser cutters and CorelDRAW.
- PNG textures: raster previews generated per layer and used to build composite sheets.
- Composite sheets: a PNG that overlays texture fills inside the nested vector outlines. Occluded areas are removed based on the layer above to avoid engraving hidden regions.

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
\text{scale}_{mm/m} = \frac{\text{width}_{mm}}{2 \cdot \text{radius}_{m}}
$$

$$
\text{contour\_interval}_{m} = \frac{\text{layer\_thickness}_{mm}}{\text{scale}_{mm/m}}
$$

### Nesting
- Polygons are packed with bounding‑box packing.
- Spacing uses $\text{kerf} + \text{part\_gap}$ to keep cuts from colliding.
- Sheet margin is applied by reducing packable area and offsetting placements.

### Composite generation
- The visible region for each layer is computed by subtracting all higher layers.
- Textures are cropped in imagery space and mapped into packed sheet coordinates.
- Vector outlines are drawn on top of the composite raster to verify alignment.

## APIs
- `POST /jobs` starts a job
- `GET /jobs` lists all jobs
- `GET /jobs/{id}` fetches job status
- `GET /jobs/{id}/files` lists output files (DXF/PNG/SVG)

## Current tech stack
- Backend: Python, FastAPI, rasterio, shapely, numpy, scipy, matplotlib, ezdxf
- Frontend: React 19, Vite, Ant Design, TanStack Query, Leaflet
- Data: STAC + Planetary Computer; Copernicus GLO‑30, USGS 3DEP, NAIP, Sentinel‑2
