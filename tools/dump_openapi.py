import json
import pathlib

from landfall_api.main import app

out = pathlib.Path(__file__).resolve().parent.parent / "apps/api/openapi.json"
out.write_text(json.dumps(app.openapi(), indent=1), encoding="utf-8")
print("wrote", out, len(app.openapi()["paths"]), "paths")
