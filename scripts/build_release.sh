#!/usr/bin/env bash
# © 2026 Mike Pollow, Digitalroots
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
SITE="$("$PY" -c 'import mlx, os; print(os.path.dirname(mlx.__path__[0]))')"
rm -rf build dist
"$PY" setup.py py2app
BUNDLE_PY="dist/Kira.app/Contents/Resources/lib/python3.12"
rm -rf "$BUNDLE_PY/mlx" "$BUNDLE_PY/lib-dynload/mlx"
cp -R "$SITE/mlx" "$BUNDLE_PY/mlx"
touch "$BUNDLE_PY/mlx/__init__.py"
zip -dq dist/Kira.app/Contents/Resources/lib/python312.zip "mlx/*" "mlx_metal*/*" 2>/dev/null || true
find dist/Kira.app -name ".DS_Store" -delete
ditto --norsrc --noextattr --noqtn dist/Kira.app "/tmp/Kira-clean-$$.app"
rm -rf dist/Kira.app
mv "/tmp/Kira-clean-$$.app" dist/Kira.app
codesign --force --deep --sign - dist/Kira.app
codesign --verify --deep --strict dist/Kira.app
echo "dist/Kira.app"
