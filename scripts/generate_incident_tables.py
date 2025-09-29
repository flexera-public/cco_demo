#!/usr/bin/env python3
"""
Generate fake incident tables from per-template schema files.
"""
from __future__ import annotations
import json
import re
import random
import secrets
import string
from pathlib import Path

IN_DIR = Path("generated_data/template_schema")
OUT_DIR = Path("generated_data/fake_incident_tables")
ROWS = 50
VAL_LEN = 10

# This contains the logic to generate specific random data for specific policy templates
# Fallback for unrecognized fields is a completely random 10-letter string
def generate_field(template, cloud, field):
    result = ""

    if (cloud == "AWS"):
        if (field == "accountID"):
            result = rand_num()

    # If no matches, just do a completely random 10-letter string
    if result == "":
        result = rand_str()

    return result

# Generic function for generating a random string
def rand_str(n: int = VAL_LEN) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))

# Generic function for generating a random integer-string
def rand_num(n: int = VAL_LEN) -> str:
    return "".join(random.choices('0123456789', k=10))

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for schema_path in sorted(IN_DIR.glob("*.json")):
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        template_name = schema.get("name", [])
        template_cloud = schema.get("cloud", [])
        incidents = schema.get("incident", [])

        base = schema_path.stem  # template basename (e.g., aws_rightsize_ec2_instances)

        for idx, inc in enumerate(incidents, 1):
            # Collect columns from export fields (dedupe while preserving order)
            columns_ordered = []
            for f in inc.get("export", []):
                name = f.get("name")
                if name and name not in columns_ordered:
                    columns_ordered.append(name)

            # Build 50 fake rows
            rows = [{col: generate_field(template_name, template_cloud, col) for col in columns_ordered} for _ in range(ROWS)]

            # New filename format: <template_basename>_<incident_number>.json
            out_path = OUT_DIR / f"{base}_{idx}.json"
            with open(out_path, "w", encoding="utf-8") as out:
                json.dump(rows, out, indent=2, ensure_ascii=False)

            print(f"[OK] wrote {out_path}")

if __name__ == "__main__":
    main()
