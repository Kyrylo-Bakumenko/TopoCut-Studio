"""
Elevation Relief Package
"""

from elevation_relief.runtime_env import configure_geospatial_runtime_env

# Normalize PROJ/GDAL data paths for this interpreter as soon as package loads.
configure_geospatial_runtime_env(force=True)

__version__ = "0.1.0"
