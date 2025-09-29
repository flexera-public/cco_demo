#!/usr/bin/env python3
"""
Generate fake policy templates to generate incidents in demo environment.
"""
from __future__ import annotations
import json
import re
import random
import secrets
import string
from pathlib import Path

IN_DIR = Path("generated_data/template_schema")
OUT_DIR = Path("templates")

def gen_header(name, version, cloud, service, policy_set, recommendation_type):
    result = f"""# DEMO POLICY TEMPLATE. DOES NOT PRODUCE REAL RESULTS.
name "{name}"
rs_pt_ver 20180301
type "policy"
short_description "Checks for snapshots older than a specified number of days and, optionally, deletes them. See the [README](https://github.com/flexera-public/policy_templates/tree/master/cost/aws/old_snapshots) and [docs.flexera.com/flexera/EN/Automation](https://docs.flexera.com/flexera/EN/Automation/AutomationGS.htm) to learn more."
long_description ""
category "Cost"
severity "low"
default_frequency "weekly"
info(
  version: "{version}",
  provider: "{cloud}",
  service: "{service}",
  policy_set: "{policy_set}",
  recommendation_type: "{recommendation_type}",
  hide_skip_approvals: "true"
)

###############################################################################
# Datasources & Scripts
###############################################################################

"""

    return result

def gen_datasources(incidents):
    result = ""

    for incident in incidents:
      incident_path = incident.get("path", "")
      ds_name = "ds_" + Path(incident_path).stem

      datasource = f"""datasource "{ds_name}" do
  request do
    verb "GET"
    host "raw.githubusercontent.com"
    path "/flexera-public/cco_demo/refs/heads/demo_data/{incident_path}"
  end
end

"""

      result += datasource

    return result

def gen_policy_block_header():
    result = f"""###############################################################################
# Policy
###############################################################################

policy "pol_incident" do
"""

    return result

def gen_incidents(incidents):
    result = ""

    for incident in incidents:
      incident_path = incident.get("path", "")
      summary_template = incident.get("summary_template", "")
      fields = incident.get("export", [])

      ds_name = "ds_" + Path(incident_path).stem

      validate_block = f"""  validate_each ${ds_name} do
    summary_template "{summary_template}"
    check eq(0, 1)
    export do
      resource_level true
"""

      for field in fields:
          field_name = field.get("name", "")
          field_label = field.get("label", "")

          export_block = f"""      field "{field_name}" do
        label "{field_label}"
      end
"""

          validate_block += export_block


      validate_block += f"""    end
  end
"""

      result += validate_block

    return result

def gen_footer():
    result = f"""end
"""

    return result

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for schema_path in sorted(IN_DIR.glob("*.json")):
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        name = schema.get("name", "")
        filename = schema.get("filename", "")
        version = schema.get("version", "")
        cloud = schema.get("cloud", "")
        service = schema.get("service", "")
        policy_set = schema.get("policy_set", "")
        recommendation_type = schema.get("recommendation_type", "")
        incidents = schema.get("incident", [])

        file_contents = gen_header(name, version, cloud, service, policy_set, recommendation_type)
        file_contents += gen_datasources(incidents)
        file_contents += gen_policy_block_header()
        file_contents += gen_incidents(incidents)
        file_contents += gen_footer()

        specific_out_dir = OUT_DIR / cloud.lower()
        specific_out_dir.mkdir(parents=True, exist_ok=True)

        out_path = specific_out_dir / f"{filename}.pt"
        with open(out_path, "w", encoding="utf-8") as out:
            out.write(file_contents)

        print(f"[OK] wrote {out_path}")

if __name__ == "__main__":
    main()
