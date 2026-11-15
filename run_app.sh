#!/usr/bin/env bash
set -e
export PYTHONPATH="$(dirname "$0")/src"
[ -f db/flame.db ] || python -m flare.cli build-all
exec python -m streamlit run src/flare/ui/Home.py
