#!/usr/bin/env bash
set -e
export PYTHONPATH="$(dirname "$0")/src:$(dirname "$0")"
python -m unittest discover -s tests -t . -v
