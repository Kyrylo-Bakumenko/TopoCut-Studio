#!/bin/bash
# Helper script to run the pipeline
export PYTHONPATH=$PYTHONPATH:$(pwd)/src
python src/elevation_relief/main.py --config config/default_config.yaml
