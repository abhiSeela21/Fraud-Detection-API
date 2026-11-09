"""Export the public API contract without credentials or environment configuration."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fraud_api.main import app  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = ROOT.parent / "frontend/openapi.json"
    content = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not output.exists() or output.read_text() != content:
            raise SystemExit("OpenAPI changed: export schema and regenerate frontend types")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)


if __name__ == "__main__":
    main()
