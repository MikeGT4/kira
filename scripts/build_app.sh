#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
rm -rf build dist
python setup.py py2app -A
echo "Alias bundle: dist/Kira.app"
echo "To test: open dist/Kira.app"
echo "To create full distributable (slower): python setup.py py2app"
