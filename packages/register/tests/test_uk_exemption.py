"""The UK exemption list in U.S. Note 52(j)(1) (FR 2026-15181, page 47363) holds none of the codes Landfall prices, so the
10% UK add-on (HTS 9903.05.81) applies to every product in scope. The list was read from the notice and is kept as data."""
import json

from landfall_classifier import load_candidates
from landfall_register import loaders


def test_no_priced_code_is_on_the_uk_exemption_list():
    f = loaders.FIXTURES / "federal_register" / "2026-15181.note52j1_uk_exempt.json"
    exempt = json.loads(f.read_text(encoding="utf-8"))["codes"]
    assert len(exempt) == 49 and exempt[0] == "2208.30.30"
    ours = list(load_candidates())  # every 6-digit subheading the recommender can return
    hits = [(c, e) for c in ours for e in exempt if e.replace(".", "").startswith(c.replace(".", "")) or c.replace(".", "").startswith(e.replace(".", ""))]
    assert hits == []
