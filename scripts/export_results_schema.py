"""Write docs/results.schema.json from ResultsDoc."""
import json
from pathlib import Path
from coldplate.results_models import ResultsDoc

out = Path(__file__).resolve().parents[1] / "docs" / "results.schema.json"
out.write_text(json.dumps(ResultsDoc.model_json_schema(), indent=2))
print("wrote", out)
