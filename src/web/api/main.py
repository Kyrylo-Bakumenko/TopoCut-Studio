import uuid
import asyncio
import logging
import traceback
import warnings
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Dict, Optional
from contextlib import asynccontextmanager

from datetime import datetime

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.responses import Response
from pydantic import BaseModel

from elevation_relief.main import run_pipeline
from .models import PipelineConfig

# Suppress the benign resource_tracker warning often seen with Uvicorn/FastAPI on shutdown
warnings.filterwarnings("ignore", category=UserWarning, module="multiprocessing.resource_tracker")

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(title="Elevation Relief API")

class CORSStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        # Allow any origin for static assets so textures can be used in WebGL.
        # This avoids canvas tainting and CORS blocks when the UI is hosted on a different domain.
        allow_origin = "*" if origin else "*"
        response.headers.setdefault("Access-Control-Allow-Origin", allow_origin)
        response.headers.setdefault("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        response.headers.setdefault("Access-Control-Allow-Headers", "*")
        response.headers.setdefault("Vary", "Origin")
        return response

# CORS for frontend (local + deployed)
default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://topocut-studio.pages.dev",
]
cors_env = os.getenv("CORS_ORIGINS")
if cors_env:
    origins = [o.strip() for o in cors_env.split(",") if o.strip()]
else:
    origins = []
origins = sorted({*default_origins, *origins})

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Job Management
class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class JobInfo(BaseModel):
    id: str
    status: JobStatus
    progress: int = 0
    message: str = "Pending"
    result_path: Optional[str] = None
    error: Optional[str] = None
    created_at: str = ""
    config_summary: str = ""

jobs: Dict[str, JobInfo] = {}
job_configs: Dict[str, dict] = {}

def run_job_wrapper(job_id: str, config: dict):
    """
    Wrapper to run the pipeline and update job status.
    """
    logger.info(f"Starting Job {job_id}")
    jobs[job_id].status = JobStatus.RUNNING
    jobs[job_id].message = "Starting..."
    
    def update_progress(pct: int, msg: str):
        if job_id in jobs:
            jobs[job_id].progress = pct
            jobs[job_id].message = msg
            logger.info(f"Job {job_id}: [{pct}%] {msg}")

    try:
        # Pydantic model to dict
        result_dir = run_pipeline(config, run_id=job_id, progress_callback=update_progress)
        jobs[job_id].result_path = result_dir
        jobs[job_id].status = JobStatus.COMPLETED
        jobs[job_id].progress = 100
        jobs[job_id].message = "Completed Successfully"
        logger.info(f"Job {job_id} Completed. Results at {result_dir}")
    except Exception as e:
        logger.error(f"Job {job_id} Failed: {e}")
        traceback.print_exc()
        jobs[job_id].error = str(e)
        jobs[job_id].status = JobStatus.FAILED
        jobs[job_id].message = "Failed"

@app.post("/jobs", response_model=JobInfo)
async def submit_job(config: PipelineConfig, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()
    
    # Convert Pydantic model to dict for the pipeline
    cfg_dict = config.dict()
    
    # Make experiment name unique to avoid file conflicts
    base_name = cfg_dict['experiment']['name'] or "run"
    cfg_dict['experiment']['name'] = f"{base_name}_{job_id[:8]}"
    
    # Create config summary for display
    config_summary = f"{cfg_dict['region']['radius_m']:.0f}m radius, {cfg_dict['model']['contour_interval_m']:.0f}m contour"
    
    job_info = JobInfo(
        id=job_id, 
        status=JobStatus.PENDING,
        created_at=created_at,
        config_summary=config_summary
    )
    jobs[job_id] = job_info
    job_configs[job_id] = cfg_dict
    
    # Running in threadpool to avoid blocking event loop
    background_tasks.add_task(run_job_wrapper, job_id, cfg_dict)
    
    return job_info

@app.get("/jobs/{job_id}", response_model=JobInfo)
async def get_job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

@app.get("/jobs/{job_id}/config")
async def get_job_config(job_id: str):
    if job_id not in job_configs:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"config": job_configs[job_id]}

@app.get("/jobs", response_model=Dict[str, JobInfo])
async def list_jobs():
    return jobs

# Serve results statically?
# Use a mounted static directory for results
# Assuming local development usage
RESULTS_DIR = Path("results").resolve()
RESULTS_DIR.mkdir(exist_ok=True)
app.mount("/results", CORSStaticFiles(directory=str(RESULTS_DIR)), name="results")

@app.get("/jobs/{job_id}/files")
async def get_job_files(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_info = jobs[job_id]
    if not job_info.result_path:
         return {"files": []}
         
    path = Path(job_info.result_path)
    if not path.exists():
         return {"files": []}
         
    # relative to the 'results' mount
    # The mount is at /results pointing to root/results
    # job_info.result_path is absolute. 
    # We need path relative to root/results.
    
    # Assume result_path is like /.../results/experiment_name
    try:
        rel_path = path.relative_to(RESULTS_DIR)
    except ValueError:
        # Fallback if somehow path is weird
        return {"files": []}
        
    files = []
    # Walk directory
    for f in path.rglob("*"):
        if f.is_file() and f.suffix.lower() in ['.png', '.jpg', '.svg', '.dxf', '.json']:
            # Create URL path
            # /results/experiment_name/subdir/file.ext
            file_rel = f.relative_to(RESULTS_DIR)
            url = f"/results/{file_rel}"
            files.append({
                "type": f.suffix.lower()[1:], # png, dxf, etc
                "name": f.name,
                "url": url,
                "category": f.parent.name # nested, textures, etc
            })
            
    return {"files": files}

@app.get("/")
async def root():
    return {"message": "Elevation Relief API is running. Visit /docs for Swagger UI."}
