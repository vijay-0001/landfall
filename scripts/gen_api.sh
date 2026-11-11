#!/usr/bin/env bash
# Regenerate apps/api/openapi.json and the web client types after an API schema change.
set -e
cd "$(dirname "$0")/.."
LANDFALL_DATABASE_URL= .venv/Scripts/python -c "
import json,sys
sys.path.insert(0,'apps/api')
from landfall_api.main import app
json.dump(app.openapi(),open('apps/api/openapi.json','w'),indent=2)
"
(cd apps/web && npm run gen:api)
