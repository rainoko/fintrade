"""Export the live OpenAPI schema to backend/openapi.json.

This committed snapshot is the contract the frontend generates its TypeScript
types from (docs/architecture/Frontend.md §5) — it lets frontend work proceed
without running the Python backend at all. Regenerate and commit it any time
app/api/schemas.py or a router's route/response signatures change (see the
add-api-endpoint skill).

Usage: python scripts/export_openapi.py
"""

import json
from pathlib import Path

from app.main import app


def main() -> None:
    schema = app.openapi()
    out_path = Path(__file__).resolve().parent.parent / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
