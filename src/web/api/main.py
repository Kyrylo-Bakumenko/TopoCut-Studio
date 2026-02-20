import uuid
import asyncio
import logging
import traceback
import warnings
import os
import json
import hashlib
import secrets
import sqlite3
import shutil
import tempfile
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, Dict, Optional
from contextlib import asynccontextmanager

from datetime import datetime

from fastapi import FastAPI, BackgroundTasks, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.responses import Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .models import PipelineConfig
from elevation_relief.runtime_env import configure_geospatial_runtime_env

# Suppress the benign resource_tracker warning often seen with Uvicorn/FastAPI on shutdown
warnings.filterwarnings("ignore", category=UserWarning, module="multiprocessing.resource_tracker")

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")
configure_geospatial_runtime_env(force=True)

RESULTS_DIR = Path("results").resolve()
RESULTS_TTL_HOURS = int(os.getenv("RESULTS_TTL_HOURS", "48"))
DATA_DIR = Path("data").resolve()
AUTH_DB_PATH = DATA_DIR / "app.sqlite3"
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "720"))
ENABLE_TEST_LOGIN = os.getenv("ENABLE_TEST_LOGIN", "1").lower() in {"1", "true", "yes", "on"}
TEST_LOGIN_EMAIL = os.getenv("TEST_LOGIN_EMAIL", "test")
TEST_LOGIN_PASSWORD = os.getenv("TEST_LOGIN_PASSWORD", "test")

DEFAULT_MACHINE_PROFILES = [
    {
        "id": "cricut-maker-3",
        "name": "Cricut Maker 3",
        "bed_width_in": 12.0,
        "bed_height_in": 12.0,
        "sheet_margin_in": 0.25,
        "sheet_gap_in": 0.08,
        "calibration_enabled_default": False,
    },
    {
        "id": "laser-cutter",
        "name": "Laser Cutter",
        "bed_width_in": 24.0,
        "bed_height_in": 12.0,
        "sheet_margin_in": 0.25,
        "sheet_gap_in": 0.125,
        "calibration_enabled_default": True,
    },
]

DEFAULT_MATERIAL_PROFILES = [
    {
        "id": "birch-1-4-12x24",
        "name": '1/4" Birch (12x24)',
        "sheet_width_in": 24.0,
        "sheet_height_in": 12.0,
        "layer_thickness_mm": 6.35,
    },
    {
        "id": "birch-1-8-12x24",
        "name": '1/8" Birch (12x24)',
        "sheet_width_in": 24.0,
        "sheet_height_in": 12.0,
        "layer_thickness_mm": 3.175,
    },
    {
        "id": "birch-1-16-12x12",
        "name": '1/16" Birch (12x12)',
        "sheet_width_in": 12.0,
        "sheet_height_in": 12.0,
        "layer_thickness_mm": 1.5875,
    },
    {
        "id": "paper-0p004-letter",
        "name": 'Paper 0.004" (Letter 8.5x11)',
        "sheet_width_in": 11.0,
        "sheet_height_in": 8.5,
        "layer_thickness_mm": 0.1016,
    },
]


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(AUTH_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_auth_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('machine', 'material')),
                name TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_custom_profiles_user_kind ON custom_profiles(user_id, kind)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash)"
        )


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash_password(password: str, salt_hex: str) -> str:
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        200_000,
    )
    return raw.hex()


def _ensure_test_login_user() -> None:
    if not ENABLE_TEST_LOGIN:
        return

    email = _normalize_email(TEST_LOGIN_EMAIL)
    password = TEST_LOGIN_PASSWORD
    if not email or not password:
        return

    with _db_connect() as conn:
        row = conn.execute(
            "SELECT id, password_salt, password_hash, created_at FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None:
            created_at = datetime.now().isoformat()
            salt_hex = secrets.token_hex(16)
            pwd_hash = _hash_password(password, salt_hex)
            conn.execute(
                "INSERT INTO users(email, password_salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (email, salt_hex, pwd_hash, created_at),
            )
            logger.warning("Created test login user '%s'. Disable with ENABLE_TEST_LOGIN=0.", email)
            return

        expected_hash = _hash_password(password, row["password_salt"])
        if expected_hash == row["password_hash"]:
            return

        salt_hex = secrets.token_hex(16)
        pwd_hash = _hash_password(password, salt_hex)
        conn.execute(
            "UPDATE users SET password_salt = ?, password_hash = ? WHERE id = ?",
            (salt_hex, pwd_hash, int(row["id"])),
        )
        logger.warning("Updated test login password for '%s'.", email)


def _create_user(email: str, password: str) -> Dict[str, Any]:
    normalized = _normalize_email(email)
    if len(normalized) < 3 or "@" not in normalized:
        raise HTTPException(status_code=400, detail="Invalid email.")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    salt_hex = secrets.token_hex(16)
    pwd_hash = _hash_password(password, salt_hex)
    created_at = datetime.now().isoformat()
    try:
        with _db_connect() as conn:
            cur = conn.execute(
                "INSERT INTO users(email, password_salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (normalized, salt_hex, pwd_hash, created_at),
            )
            user_id = int(cur.lastrowid)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Email already exists.")

    return {"id": user_id, "email": normalized, "created_at": created_at}


def _get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    normalized = _normalize_email(email)
    with _db_connect() as conn:
        return conn.execute("SELECT * FROM users WHERE email = ?", (normalized,)).fetchone()


def _authenticate_user(email: str, password: str) -> Dict[str, Any]:
    row = _get_user_by_email(email)
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    expected = _hash_password(password, row["password_salt"])
    if expected != row["password_hash"]:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    return {"id": int(row["id"]), "email": str(row["email"]), "created_at": str(row["created_at"])}


def _create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    created_at = datetime.now()
    expires_at = created_at.timestamp() + (SESSION_TTL_HOURS * 3600)
    with _db_connect() as conn:
        conn.execute(
            "INSERT INTO sessions(user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, token_hash, created_at.isoformat(), datetime.fromtimestamp(expires_at).isoformat()),
        )
    return token


def _remove_session(token: str) -> None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _db_connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def _get_user_from_token(token: str) -> Optional[Dict[str, Any]]:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now_iso = datetime.now().isoformat()
    with _db_connect() as conn:
        row = conn.execute(
            """
            SELECT u.id AS user_id, u.email AS email, u.created_at AS created_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ?
            """,
            (token_hash, now_iso),
        ).fetchone()
        if row is None:
            return None
        return {"id": int(row["user_id"]), "email": str(row["email"]), "created_at": str(row["created_at"])}


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header.")
    return parts[1].strip()


def _require_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    token = _extract_bearer_token(authorization)
    user = _get_user_from_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return user


def _public_profile_id(kind: str, profile_id: int) -> str:
    return f"custom-{kind}-{profile_id}"


def _parse_public_profile_id(kind: str, value: str) -> int:
    prefix = f"custom-{kind}-"
    if not value.startswith(prefix):
        raise HTTPException(status_code=400, detail=f"Invalid profile id: {value}")
    raw = value[len(prefix) :]
    if not raw.isdigit():
        raise HTTPException(status_code=400, detail=f"Invalid profile id: {value}")
    return int(raw)


def _validate_machine_profile_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    required = [
        "bed_width_in",
        "bed_height_in",
        "sheet_margin_in",
        "sheet_gap_in",
        "calibration_enabled_default",
    ]
    for key in required:
        if key not in data:
            raise HTTPException(status_code=400, detail=f"Missing machine field: {key}")
    return {
        "bed_width_in": float(data["bed_width_in"]),
        "bed_height_in": float(data["bed_height_in"]),
        "sheet_margin_in": float(data["sheet_margin_in"]),
        "sheet_gap_in": float(data["sheet_gap_in"]),
        "calibration_enabled_default": bool(data["calibration_enabled_default"]),
    }


def _validate_material_profile_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    required = ["sheet_width_in", "sheet_height_in", "layer_thickness_mm"]
    for key in required:
        if key not in data:
            raise HTTPException(status_code=400, detail=f"Missing material field: {key}")
    return {
        "sheet_width_in": float(data["sheet_width_in"]),
        "sheet_height_in": float(data["sheet_height_in"]),
        "layer_thickness_mm": float(data["layer_thickness_mm"]),
    }


def _serialize_custom_profiles(user_id: int) -> Dict[str, Any]:
    machine_profiles: list[Dict[str, Any]] = []
    material_profiles: list[Dict[str, Any]] = []
    with _db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, kind, name, data_json, updated_at
            FROM custom_profiles
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    for row in rows:
        kind = str(row["kind"])
        data = json.loads(str(row["data_json"]))
        payload = {
            "id": _public_profile_id(kind, int(row["id"])),
            "name": str(row["name"]),
            "updated_at": str(row["updated_at"]),
            **data,
        }
        if kind == "machine":
            machine_profiles.append(payload)
        else:
            material_profiles.append(payload)
    return {"machine_profiles": machine_profiles, "material_profiles": material_profiles}


def _init_jobs_db() -> None:
    with _db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL,
                message TEXT NOT NULL,
                result_path TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                config_summary TEXT NOT NULL,
                config_json TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs(user_id, created_at DESC)")


def _recover_incomplete_jobs() -> None:
    with _db_connect() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                message = 'Failed (server restarted)',
                error = COALESCE(error, 'Server restarted during processing')
            WHERE status IN ('pending', 'running')
            """
        )


def _insert_job(
    *,
    job_id: str,
    user_id: int,
    status: str,
    progress: int,
    message: str,
    result_path: Optional[str],
    error: Optional[str],
    created_at: str,
    config_summary: str,
    config_json: Dict[str, Any],
) -> None:
    with _db_connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs(
                id, user_id, status, progress, message, result_path, error,
                created_at, config_summary, config_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                user_id,
                status,
                int(progress),
                message,
                result_path,
                error,
                created_at,
                config_summary,
                json.dumps(config_json),
            ),
        )


def _update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields.keys())
    values = list(fields.values())
    values.append(job_id)
    with _db_connect() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)


def _job_row_to_info(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": str(row["id"]),
        "status": str(row["status"]),
        "progress": int(row["progress"]),
        "message": str(row["message"]),
        "result_path": row["result_path"],
        "error": row["error"],
        "created_at": str(row["created_at"]),
        "config_summary": str(row["config_summary"]),
    }


def _get_job_for_user(job_id: str, user_id: int) -> sqlite3.Row:
    with _db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return row


def _list_jobs_for_user(user_id: int) -> Dict[str, Dict[str, Any]]:
    with _db_connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return {str(row["id"]): _job_row_to_info(row) for row in rows}

def _is_under_results(path: Path) -> bool:
    try:
        path.resolve().relative_to(RESULTS_DIR)
        return True
    except ValueError:
        return False


def _delete_results_path(path: Path) -> bool:
    if not path.exists():
        return False
    if not _is_under_results(path):
        logger.warning("Refusing to delete path outside results: %s", path)
        return False
    shutil.rmtree(path)
    return True


def _cleanup_old_results(ttl_hours: int) -> int:
    if ttl_hours <= 0:
        return 0
    if not RESULTS_DIR.exists():
        return 0
    cutoff = datetime.now().timestamp() - (ttl_hours * 3600)
    removed = 0
    for child in RESULTS_DIR.iterdir():
        if not child.is_dir():
            continue
        try:
            if child.stat().st_mtime < cutoff:
                if _delete_results_path(child):
                    removed += 1
        except OSError:
            continue
    return removed


def _collect_bundle_files(res_dir: Path, kind: str) -> list[Path]:
    nested_dir = res_dir / "nested"
    textures_dir = res_dir / "textures"
    vectors_dir = res_dir / "vectors"

    if kind == "nested":
        patterns = ["*.dxf", "*.svg", "*.json"]
        files: list[Path] = []
        if nested_dir.exists():
            for pattern in patterns:
                files.extend(nested_dir.glob(pattern))
        return files
    if kind == "composite":
        files = []
        if nested_dir.exists():
            files.extend(nested_dir.glob("*_composite.png"))
            files.extend(nested_dir.glob("*_cricut_print.png"))
            files.extend(nested_dir.glob("*_bundle.svg"))
            files.extend(nested_dir.glob("*.dxf"))
        return files
    if kind == "bundle":
        return list(nested_dir.glob("*_bundle.svg")) if nested_dir.exists() else []
    if kind == "textures":
        return list(textures_dir.glob("*.png")) if textures_dir.exists() else []
    if kind == "all":
        files = []
        if res_dir.exists():
            for f in res_dir.rglob("*"):
                if f.is_file() and f.suffix.lower() in {".png", ".svg", ".dxf", ".json", ".tif"}:
                    files.append(f)
        return files
    return []


@asynccontextmanager
async def lifespan(app: FastAPI):
    RESULTS_DIR.mkdir(exist_ok=True)
    _init_auth_db()
    _ensure_test_login_user()
    _init_jobs_db()
    _recover_incomplete_jobs()
    removed = _cleanup_old_results(RESULTS_TTL_HOURS)
    if removed:
        logger.info("Cleaned up %s expired result folders", removed)
    yield


app = FastAPI(title="Elevation Relief API", lifespan=lifespan)

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
    CANCELED = "canceled"

class JobInfo(BaseModel):
    id: str
    status: JobStatus
    progress: int = 0
    message: str = "Pending"
    result_path: Optional[str] = None
    error: Optional[str] = None
    created_at: str = ""
    config_summary: str = ""


class AuthCredentials(BaseModel):
    email: str
    password: str


class AuthUser(BaseModel):
    id: int
    email: str
    created_at: str


class AuthResponse(BaseModel):
    token: str
    user: AuthUser


class ProfileUpsertRequest(BaseModel):
    kind: str
    name: str
    data: Dict[str, Any]

job_cancelled: Dict[str, bool] = {}


class JobCancelledError(Exception):
    pass

def run_job_wrapper(job_id: str, config: dict):
    """
    Wrapper to run the pipeline and update job status.
    """
    logger.info(f"Starting Job {job_id}")
    _update_job(
        job_id,
        status=JobStatus.RUNNING.value,
        message="Starting...",
        progress=0,
        error=None,
    )
    
    def update_progress(pct: int, msg: str):
        if job_cancelled.get(job_id):
            raise JobCancelledError()
        _update_job(job_id, progress=int(pct), message=msg)
        logger.info(f"Job {job_id}: [{pct}%] {msg}")

    try:
        configure_geospatial_runtime_env(force=True)
        # Import lazily so auth/profile endpoints can run even if geospatial runtime is misconfigured.
        from elevation_relief.main import run_pipeline

        # Pydantic model to dict
        result_dir = run_pipeline(config, run_id=job_id, progress_callback=update_progress)
        _update_job(
            job_id,
            result_path=result_dir,
            status=JobStatus.COMPLETED.value,
            progress=100,
            message="Completed Successfully",
            error=None,
        )
        logger.info(f"Job {job_id} Completed. Results at {result_dir}")
    except JobCancelledError:
        _update_job(
            job_id,
            status=JobStatus.CANCELED.value,
            message="Canceled",
            progress=0,
        )
        logger.info(f"Job {job_id} Canceled")
    except Exception as e:
        logger.error(f"Job {job_id} Failed: {e}")
        traceback.print_exc()
        _update_job(
            job_id,
            error=str(e),
            status=JobStatus.FAILED.value,
            message="Failed",
        )
    finally:
        job_cancelled.pop(job_id, None)

@app.post("/jobs", response_model=JobInfo)
async def submit_job(
    config: PipelineConfig,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(_require_current_user),
):
    job_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()
    
    # Convert Pydantic model to dict for the pipeline
    cfg_dict = config.dict()
    
    # Make experiment name unique to avoid file conflicts
    base_name = cfg_dict['experiment']['name'] or "run"
    cfg_dict['experiment']['name'] = f"{base_name}_{job_id[:8]}"
    
    # Create config summary for display
    config_summary = f"{cfg_dict['region']['radius_m']:.0f}m radius, {cfg_dict['model']['contour_interval_m']:.0f}m contour"
    profiles = cfg_dict.get("profiles") or {}
    machine_name = profiles.get("machine_name")
    material_name = profiles.get("material_name")
    if machine_name and material_name:
        config_summary += f" • {machine_name} / {material_name}"
    elif machine_name:
        config_summary += f" • {machine_name}"
    elif material_name:
        config_summary += f" • {material_name}"
    
    _insert_job(
        job_id=job_id,
        user_id=int(user["id"]),
        status=JobStatus.PENDING.value,
        progress=0,
        message="Pending",
        result_path=None,
        error=None,
        created_at=created_at,
        config_summary=config_summary,
        config_json=cfg_dict,
    )
    job_cancelled[job_id] = False
    
    # Running in threadpool to avoid blocking event loop
    background_tasks.add_task(run_job_wrapper, job_id, cfg_dict)
    
    row = _get_job_for_user(job_id, int(user["id"]))
    return _job_row_to_info(row)


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, user: Dict[str, Any] = Depends(_require_current_user)):
    row = _get_job_for_user(job_id, int(user["id"]))
    status = str(row["status"])
    if status in {JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELED.value}:
        return {"status": status, "message": "Job already finished."}
    had_active_worker = job_id in job_cancelled
    job_cancelled[job_id] = True
    _update_job(job_id, message="Canceling...")
    # If no active worker is attached (e.g. server restart), mark canceled immediately.
    if status in {JobStatus.PENDING.value, JobStatus.RUNNING.value} and not had_active_worker:
        _update_job(job_id, status=JobStatus.CANCELED.value, progress=0, message="Canceled")
    return {"status": status, "message": "Cancel requested."}


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str, user: Dict[str, Any] = Depends(_require_current_user)):
    row = _get_job_for_user(job_id, int(user["id"]))
    cancelled = False
    if str(row["status"]) == JobStatus.RUNNING.value:
        job_cancelled[job_id] = True
        _update_job(job_id, message="Canceling...")
        cancelled = True

    deleted_files = False
    result_path = row["result_path"]
    if result_path:
        deleted_files = _delete_results_path(Path(str(result_path)))

    with _db_connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ? AND user_id = ?", (job_id, int(user["id"])))
    job_cancelled.pop(job_id, None)

    return {"status": "deleted", "files_deleted": deleted_files, "cancelled": cancelled}


@app.get("/jobs/{job_id}/download")
async def download_job_bundle(
    job_id: str,
    background_tasks: BackgroundTasks,
    kind: str = "nested",
    user: Dict[str, Any] = Depends(_require_current_user),
):
    row = _get_job_for_user(job_id, int(user["id"]))
    result_path = row["result_path"]
    if not result_path:
        raise HTTPException(status_code=404, detail="Job results not found")

    res_dir = Path(str(result_path))
    if not res_dir.exists():
        raise HTTPException(status_code=404, detail="Job results not found")

    files = _collect_bundle_files(res_dir, kind)
    if not files:
        raise HTTPException(status_code=404, detail="No files available for download")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = Path(tmp.name)
    tmp.close()

    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            try:
                archive.write(file_path, arcname=str(file_path.relative_to(res_dir)))
            except Exception:
                continue

    background_tasks.add_task(os.remove, tmp_path)

    download_name = f"{res_dir.name}_{kind}.zip"
    return FileResponse(tmp_path, filename=download_name, media_type="application/zip")

@app.get("/jobs/{job_id}", response_model=JobInfo)
async def get_job_status(job_id: str, user: Dict[str, Any] = Depends(_require_current_user)):
    row = _get_job_for_user(job_id, int(user["id"]))
    return _job_row_to_info(row)

@app.get("/jobs/{job_id}/config")
async def get_job_config(job_id: str, user: Dict[str, Any] = Depends(_require_current_user)):
    row = _get_job_for_user(job_id, int(user["id"]))
    config_json = json.loads(str(row["config_json"]))
    return {"config": config_json}

@app.get("/jobs", response_model=Dict[str, JobInfo])
async def list_jobs(user: Dict[str, Any] = Depends(_require_current_user)):
    return _list_jobs_for_user(int(user["id"]))


@app.get("/profiles/defaults")
async def get_profile_defaults():
    return {
        "version": "v1",
        "machine_profiles": DEFAULT_MACHINE_PROFILES,
        "material_profiles": DEFAULT_MATERIAL_PROFILES,
    }


@app.post("/auth/signup", response_model=AuthResponse)
async def signup(payload: AuthCredentials):
    user = _create_user(payload.email, payload.password)
    token = _create_session(int(user["id"]))
    return {"token": token, "user": user}


@app.post("/auth/login", response_model=AuthResponse)
async def login(payload: AuthCredentials):
    user = _authenticate_user(payload.email, payload.password)
    token = _create_session(int(user["id"]))
    return {"token": token, "user": user}


@app.get("/auth/me", response_model=AuthUser)
async def auth_me(user: Dict[str, Any] = Depends(_require_current_user)):
    return user


@app.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    token = _extract_bearer_token(authorization)
    _remove_session(token)
    return {"status": "ok"}


@app.get("/profiles/custom")
async def list_custom_profiles(user: Dict[str, Any] = Depends(_require_current_user)):
    return _serialize_custom_profiles(int(user["id"]))


@app.post("/profiles/custom")
async def create_custom_profile(
    payload: ProfileUpsertRequest,
    user: Dict[str, Any] = Depends(_require_current_user),
):
    kind = payload.kind.strip().lower()
    if kind not in {"machine", "material"}:
        raise HTTPException(status_code=400, detail="kind must be 'machine' or 'material'.")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required.")
    data = payload.data or {}
    normalized_data = (
        _validate_machine_profile_payload(data)
        if kind == "machine"
        else _validate_material_profile_payload(data)
    )
    now = datetime.now().isoformat()
    with _db_connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO custom_profiles(user_id, kind, name, data_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(user["id"]), kind, name, json.dumps(normalized_data), now, now),
        )
        row_id = int(cur.lastrowid)
    return {"id": _public_profile_id(kind, row_id)}


@app.put("/profiles/custom/{profile_id}")
async def update_custom_profile(
    profile_id: str,
    payload: ProfileUpsertRequest,
    user: Dict[str, Any] = Depends(_require_current_user),
):
    kind = payload.kind.strip().lower()
    if kind not in {"machine", "material"}:
        raise HTTPException(status_code=400, detail="kind must be 'machine' or 'material'.")
    row_id = _parse_public_profile_id(kind, profile_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required.")
    data = payload.data or {}
    normalized_data = (
        _validate_machine_profile_payload(data)
        if kind == "machine"
        else _validate_material_profile_payload(data)
    )
    now = datetime.now().isoformat()
    with _db_connect() as conn:
        existing = conn.execute(
            "SELECT id FROM custom_profiles WHERE id = ? AND user_id = ? AND kind = ?",
            (row_id, int(user["id"]), kind),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Profile not found.")
        conn.execute(
            """
            UPDATE custom_profiles
            SET name = ?, data_json = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (name, json.dumps(normalized_data), now, row_id, int(user["id"])),
        )
    return {"status": "ok"}


@app.delete("/profiles/custom/{profile_id}")
async def delete_custom_profile(
    profile_id: str,
    kind: str,
    user: Dict[str, Any] = Depends(_require_current_user),
):
    normalized_kind = kind.strip().lower()
    if normalized_kind not in {"machine", "material"}:
        raise HTTPException(status_code=400, detail="kind must be 'machine' or 'material'.")
    row_id = _parse_public_profile_id(normalized_kind, profile_id)
    with _db_connect() as conn:
        cur = conn.execute(
            "DELETE FROM custom_profiles WHERE id = ? AND user_id = ? AND kind = ?",
            (row_id, int(user["id"]), normalized_kind),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Profile not found.")
    return {"status": "ok"}

# Serve results statically
app.mount("/results", CORSStaticFiles(directory=str(RESULTS_DIR)), name="results")

@app.get("/jobs/{job_id}/files")
async def get_job_files(job_id: str, user: Dict[str, Any] = Depends(_require_current_user)):
    row = _get_job_for_user(job_id, int(user["id"]))

    result_path = row["result_path"]
    if not result_path:
         return {"files": []}
         
    path = Path(str(result_path))
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
