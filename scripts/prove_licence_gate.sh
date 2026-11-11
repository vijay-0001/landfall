#!/usr/bin/env bash
# Proves the licence gate fails on a planted GPL package, for both ecosystems, then cleans up.
# Usage: scripts/prove_licence_gate.sh   (expects the repo venv and apps/web/node_modules to exist)
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python; [ -x "$PY" ] || PY=.venv/bin/python
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"; "$PY" -m pip uninstall -y planted-gpl >/dev/null 2>&1; rm -rf apps/web/node_modules/planted-gpl' EXIT

echo "== python: plant a GPL-3.0 package"
mkdir -p "$tmp/py/planted_gpl"
cat > "$tmp/py/pyproject.toml" <<'EOF'
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
[project]
name = "planted-gpl"
version = "1.0"
license = "GPL-3.0-only"
EOF
echo "" > "$tmp/py/planted_gpl/__init__.py"
"$PY" -m pip install -q "$tmp/py" || exit 2
"$PY" -m piplicenses --format=json --output-file=.licences-py.json >/dev/null
"$PY" scripts/licence_gate.py python .licences-py.json; py_rc=$?

echo "== npm: plant a GPL-3.0 package"
mkdir -p "$tmp/npm"
echo '{"name":"planted-gpl","version":"1.0.0","license":"GPL-3.0-only","main":"index.js"}' > "$tmp/npm/package.json"
echo 'module.exports = 1' > "$tmp/npm/index.js"
mkdir -p apps/web/node_modules/planted-gpl && cp "$tmp/npm/"* apps/web/node_modules/planted-gpl/
(cd apps/web && npx --yes license-checker-rseidelsohn@4 --json --out ../../.licences-npm.json >/dev/null 2>&1)
"$PY" scripts/licence_gate.py npm .licences-npm.json; npm_rc=$?

if [ "$py_rc" -ne 0 ] && [ "$npm_rc" -ne 0 ]; then
  echo "PROVEN: the gate fails on a planted GPL package in both ecosystems (python rc=$py_rc, npm rc=$npm_rc)"
else
  echo "NOT PROVEN: python rc=$py_rc npm rc=$npm_rc"; exit 1
fi
