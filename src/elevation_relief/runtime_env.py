"""Runtime helpers for stable geospatial library initialization."""

from __future__ import annotations

import logging
import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

LOGGER = logging.getLogger("runtime_env")

_MIN_PROJ_DB_MINOR = 6
_CONFIGURED = False


def _split_env_paths(raw: str | None) -> list[Path]:
    if not raw:
        return []
    return [Path(p).expanduser() for p in raw.split(os.pathsep) if p]


def _proj_db_minor(proj_dir: Path) -> int | None:
    db_path = proj_dir / "proj.db"
    if not db_path.exists():
        return None

    try:
        with sqlite3.connect(str(db_path)) as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(metadata)")]
            key_column = None
            if "name" in columns:
                key_column = "name"
            elif "key" in columns:
                key_column = "key"
            if not key_column:
                return None

            row = conn.execute(
                f"SELECT value FROM metadata WHERE {key_column} = ?",
                ("DATABASE.LAYOUT.VERSION.MINOR",),
            ).fetchone()
            if not row:
                return None
            return int(row[0])
    except Exception:
        return None


def _module_dir(module_name: str) -> Path | None:
    """Resolve package directory without importing the module."""
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception:
        return None
    if spec is None:
        return None
    if spec.submodule_search_locations:
        try:
            return Path(next(iter(spec.submodule_search_locations))).resolve()
        except Exception:
            return None
    if spec.origin:
        try:
            return Path(spec.origin).resolve().parent
        except Exception:
            return None
    return None


def _candidate_proj_dirs() -> list[Path]:
    candidates: list[Path] = []

    for key in ("PROJ_DATA", "PROJ_LIB"):
        candidates.extend(_split_env_paths(os.environ.get(key)))

    prefixes = [Path(sys.prefix), Path(sys.base_prefix)]
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        prefixes.append(Path(conda_prefix))

    for prefix in prefixes:
        candidates.append(prefix / "share" / "proj")
        candidates.append(prefix / "Library" / "share" / "proj")

    rasterio_dir = _module_dir("rasterio")
    if rasterio_dir:
        candidates.append(rasterio_dir / "proj_data")

    pyproj_dir = _module_dir("pyproj")
    if pyproj_dir:
        candidates.append(pyproj_dir / "proj_dir" / "share" / "proj")

    seen: set[Path] = set()
    unique_existing: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_dir() and (resolved / "proj.db").exists():
            unique_existing.append(resolved)

    return unique_existing


def _select_proj_dir() -> tuple[Path | None, int | None]:
    best_dir: Path | None = None
    best_minor = -1

    for proj_dir in _candidate_proj_dirs():
        minor = _proj_db_minor(proj_dir)
        if minor is None:
            continue
        if minor > best_minor:
            best_minor = minor
            best_dir = proj_dir

    if best_dir is None:
        return None, None
    return best_dir, best_minor


def _candidate_gdal_dirs() -> list[Path]:
    candidates: list[Path] = []
    candidates.extend(_split_env_paths(os.environ.get("GDAL_DATA")))

    prefixes = [Path(sys.prefix), Path(sys.base_prefix)]
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        prefixes.append(Path(conda_prefix))

    for prefix in prefixes:
        candidates.append(prefix / "share" / "gdal")
        candidates.append(prefix / "Library" / "share" / "gdal")

    rasterio_dir = _module_dir("rasterio")
    if rasterio_dir:
        candidates.append(rasterio_dir / "gdal_data")

    seen: set[Path] = set()
    unique_existing: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_dir():
            unique_existing.append(resolved)
    return unique_existing


def configure_geospatial_runtime_env(force: bool = False) -> None:
    """Pick compatible PROJ/GDAL data directories for the current interpreter."""

    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    proj_dir, proj_minor = _select_proj_dir()
    if proj_dir:
        os.environ["PROJ_DATA"] = str(proj_dir)
        os.environ["PROJ_LIB"] = str(proj_dir)
        if proj_minor is not None and proj_minor < _MIN_PROJ_DB_MINOR:
            LOGGER.warning(
                "Using PROJ data at %s with layout minor %s (< %s).",
                proj_dir,
                proj_minor,
                _MIN_PROJ_DB_MINOR,
            )
        else:
            LOGGER.info("Using PROJ data at %s (layout minor %s).", proj_dir, proj_minor)
    else:
        LOGGER.warning("Could not find a valid proj.db in known locations.")

    gdal_candidates = _candidate_gdal_dirs()
    if gdal_candidates:
        # Prefer rasterio's bundled gdal_data when available.
        selected = gdal_candidates[0]
        for candidate in gdal_candidates:
            if candidate.name == "gdal_data" and "rasterio" in str(candidate):
                selected = candidate
                break
        os.environ["GDAL_DATA"] = str(selected)
        LOGGER.info("Using GDAL data at %s.", selected)

    _CONFIGURED = True
