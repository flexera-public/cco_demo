#!/usr/bin/env python3
"""
Generate fake policy templates to generate incidents in demo environment.

Templates that have resource ID fields are enriched to query the Flexera
/costs/select API at runtime, extracting real resource_ids from the org's
cost data and merging them with static seed data.
"""
from __future__ import annotations
import json
from pathlib import Path

IN_DIR = Path("generated_data/template_schema")
OUT_DIR = Path("templates")

# Maps schema cloud name -> cost API vendor dimension value
CLOUD_TO_VENDOR = {
    "AWS": "AWS",
    "Azure": "Azure",
    "Google": "GCP",
    "Oracle": "Oracle",
}

# Templates without resource ID fields, or whose vendor has no usable resource_ids
# in the demo org's cost data — use static seed data instead.
SKIP_ENRICHMENT = {
    # No resource ID fields in seed data
    "aws_tag_cardinality",
    "azure_tag_cardinality",
    "azure_marketplace_new_products",
    "google_label_cardinality",
    # Google: demo org cost data only contains CBI internal IDs (optima_*), not real GCP IDs
    "google_committed_use_discount_recommendations",
    "google_idle_ip_address_recommendations",
    "google_idle_persistent_disk_recommendations",
    "google_rightsize_cloudsql_recommendations",
    "google_rightsize_vm_recommendations",
    # Oracle: this demo org has no Oracle cost billing data
    "oracle_advisor_rightsize_autodbs",
    "oracle_advisor_rightsize_basedbs",
    "oracle_advisor_rightsize_lbs",
    "oracle_advisor_rightsize_vms",
    "oracle_advisor_unattached_volumes",
}

# Per-template JavaScript boolean expression applied to each grouped cost row
# before sorting.  The variable `rid` is the lowercased resource_id string.
# Rows where the expression evaluates to false are discarded, so only
# resource IDs that look correct for the template's resource type make it
# into the merged incident output.
RESOURCE_ID_FILTERS = {
    # ── AWS ──────────────────────────────────────────────────────────────────
    # EC2 instance IDs start with "i-"
    "aws_rightsize_ec2_instances":           "rid.indexOf('i-') === 0",
    "aws_long_stopped_instances":            "rid.indexOf('i-') === 0",
    "aws_superseded_instances":              "rid.indexOf('i-') === 0",
    "aws_reserved_instance_recommendations": "rid.indexOf('i-') === 0",
    "aws_savings_plan_recommendations":      "rid.indexOf('i-') === 0",
    # EBS volume IDs start with "vol-"
    "aws_rightsize_ebs_volumes":             "rid.indexOf('vol-') === 0",
    "aws_superseded_ebs_volumes":            "rid.indexOf('vol-') === 0",
    # RDS instance/cluster IDs start with "db:" or "cluster:"
    "aws_rightsize_rds_instances":           "rid.indexOf('db:') === 0 || rid.indexOf('cluster:') === 0",
    # EC2 snapshot resource_ids come back from the cost API as "snapshot/snap-xxx";
    # also accept bare "snap-" in case of normalised data.
    "aws_delete_old_snapshots":              "rid.indexOf('snapshot/snap-') === 0 || rid.indexOf('snap-') === 0",
    # Load balancer ARN paths: app=ALB, net=NLB, neither=CLB
    "aws_unused_albs": "rid.indexOf('loadbalancer/app/') === 0",
    "aws_unused_nlbs": "rid.indexOf('loadbalancer/net/') === 0",
    "aws_unused_clbs": "rid.indexOf('loadbalancer/') === 0 && rid.indexOf('/app/') < 0 && rid.indexOf('/net/') < 0",
    # Elastic IP allocation IDs start with "eipalloc-"
    "aws_unused_ip_addresses":               "rid.indexOf('eipalloc-') === 0",
    # ── Azure ────────────────────────────────────────────────────────────────
    # Azure ARM paths are lowercased before matching
    # Virtual machines
    "azure_compute_rightsizing":              "rid.indexOf('/virtualmachines/') >= 0",
    "long_stopped_instances_azure":           "rid.indexOf('/virtualmachines/') >= 0",
    "azure_reserved_instance_recommendations": "rid.indexOf('/virtualmachines/') >= 0",
    "azure_savings_plan_recommendations":     "rid.indexOf('/virtualmachines/') >= 0",
    # Managed disks
    "azure_rightsize_managed_disks":          "rid.indexOf('/microsoft.compute/disks/') >= 0",
    "azure_unused_volumes":                   "rid.indexOf('/microsoft.compute/disks/') >= 0",
    # Snapshots
    "azure_delete_old_snapshots":             "rid.indexOf('/microsoft.compute/snapshots/') >= 0",
    # Public IP addresses
    "azure_unused_ip_addresses":              "rid.indexOf('/publicipaddresses/') >= 0",
    # Azure Firewalls
    "azure_unused_firewalls":                 "rid.indexOf('/azurefirewalls/') >= 0",
    # App Service Plans
    "azure_unused_app_service_plans":         "rid.indexOf('/serverfarms/') >= 0",
    # SQL databases
    "azure_rightsize_sql_instances":          "rid.indexOf('/microsoft.sql/servers/') >= 0",
    # MySQL Flexible Servers
    "azure_rightsize_mysql_flexible":         "rid.indexOf('/microsoft.dbformysql/') >= 0",
}

# For some resource types the cost API returns resource_ids with a vendor-specific
# prefix that is NOT part of the resource identifier used in the incident table.
# Map template filename -> prefix string to strip before assigning new_resource_id.
RESOURCE_ID_STRIP_PREFIX = {
    # Flexera cost API returns EC2 snapshot IDs as "snapshot/snap-xxx" but the
    # incident export expects just "snap-xxx".
    "aws_delete_old_snapshots": "snapshot/",
}

# Additional /costs/select filter expressions to narrow results beyond the vendor
# dimension, matching the upstream policy template cost API queries.  Each key is
# a template filename; the value is a list of filter expression dicts that will be
# inserted into the "and" expressions array alongside the vendor filter.
#
# Source patterns (from upstream flexera-public/policy_templates):
#   AWS EC2:       service=AmazonEC2, resource_type=Compute Instance
#   AWS EBS:       service=AmazonEC2, resource_type=Storage|System Operation (OR)
#   AWS RDS:       service=AmazonRDS
#   AWS Snapshots: service=AmazonEC2|AmazonRDS (OR), resource_type=Storage Snapshot
#   AWS ALB:       service=AWSELB, resource_type=Load Balancer-Application
#   AWS NLB:       service=AWSELB, resource_type=Load Balancer-Network
#   AWS CLB:       service=AWSELB, resource_type=Load Balancer
#   Azure VMs:     resource_id substring /providers/Microsoft.Compute/virtualMachines/
#   Azure Disks:   resource_id substring /providers/Microsoft.Compute/disks/
#   (etc. — resource_id substring matching the ARM provider path)
COST_API_FILTERS = {
    # ── AWS EC2 instances ────────────────────────────────────────────────────
    "aws_rightsize_ec2_instances": [
        {"dimension": "service", "type": "equal", "value": "AmazonEC2"},
        {"dimension": "resource_type", "type": "equal", "value": "Compute Instance"},
    ],
    "aws_long_stopped_instances": [
        {"dimension": "service", "type": "equal", "value": "AmazonEC2"},
        {"dimension": "resource_type", "type": "equal", "value": "Compute Instance"},
    ],
    "aws_superseded_instances": [
        {"dimension": "service", "type": "equal", "value": "AmazonEC2"},
        {"dimension": "resource_type", "type": "equal", "value": "Compute Instance"},
    ],
    "aws_reserved_instance_recommendations": [
        {"dimension": "service", "type": "equal", "value": "AmazonEC2"},
        {"dimension": "resource_type", "type": "equal", "value": "Compute Instance"},
    ],
    "aws_savings_plan_recommendations": [
        {"dimension": "service", "type": "equal", "value": "AmazonEC2"},
        {"dimension": "resource_type", "type": "equal", "value": "Compute Instance"},
    ],
    # ── AWS EBS volumes ──────────────────────────────────────────────────────
    "aws_rightsize_ebs_volumes": [
        {"dimension": "service", "type": "equal", "value": "AmazonEC2"},
        {"type": "or", "expressions": [
            {"dimension": "resource_type", "type": "equal", "value": "Storage"},
            {"dimension": "resource_type", "type": "equal", "value": "System Operation"},
        ]},
    ],
    "aws_superseded_ebs_volumes": [
        {"dimension": "service", "type": "equal", "value": "AmazonEC2"},
        {"type": "or", "expressions": [
            {"dimension": "resource_type", "type": "equal", "value": "Storage"},
            {"dimension": "resource_type", "type": "equal", "value": "System Operation"},
        ]},
    ],
    # ── AWS RDS ──────────────────────────────────────────────────────────────
    "aws_rightsize_rds_instances": [
        {"dimension": "service", "type": "equal", "value": "AmazonRDS"},
    ],
    # ── AWS Snapshots ────────────────────────────────────────────────────────
    "aws_delete_old_snapshots": [
        {"type": "or", "expressions": [
            {"dimension": "service", "type": "equal", "value": "AmazonEC2"},
            {"dimension": "service", "type": "equal", "value": "AmazonRDS"},
        ]},
        {"dimension": "resource_type", "type": "equal", "value": "Storage Snapshot"},
    ],
    # ── AWS Load Balancers ───────────────────────────────────────────────────
    "aws_unused_albs": [
        {"dimension": "service", "type": "equal", "value": "AWSELB"},
        {"dimension": "resource_type", "type": "equal", "value": "Load Balancer-Application"},
    ],
    "aws_unused_nlbs": [
        {"dimension": "service", "type": "equal", "value": "AWSELB"},
        {"dimension": "resource_type", "type": "equal", "value": "Load Balancer-Network"},
    ],
    "aws_unused_clbs": [
        {"dimension": "service", "type": "equal", "value": "AWSELB"},
        {"dimension": "resource_type", "type": "equal", "value": "Load Balancer"},
    ],
    # ── Azure VMs ────────────────────────────────────────────────────────────
    "azure_compute_rightsizing": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Compute/virtualMachines/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.compute/virtualmachines/"},
        ]},
    ],
    "long_stopped_instances_azure": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Compute/virtualMachines/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.compute/virtualmachines/"},
        ]},
    ],
    "azure_reserved_instance_recommendations": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Compute/virtualMachines/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.compute/virtualmachines/"},
        ]},
    ],
    "azure_savings_plan_recommendations": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Compute/virtualMachines/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.compute/virtualmachines/"},
        ]},
    ],
    # ── Azure Managed Disks ──────────────────────────────────────────────────
    "azure_rightsize_managed_disks": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Compute/disks/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.compute/disks/"},
        ]},
    ],
    "azure_unused_volumes": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Compute/disks/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.compute/disks/"},
        ]},
    ],
    # ── Azure Snapshots ──────────────────────────────────────────────────────
    "azure_delete_old_snapshots": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Compute/snapshots/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.compute/snapshots/"},
        ]},
    ],
    # ── Azure Public IPs ─────────────────────────────────────────────────────
    "azure_unused_ip_addresses": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Network/publicIPAddresses/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.network/publicipaddresses/"},
        ]},
    ],
    # ── Azure Firewalls ──────────────────────────────────────────────────────
    "azure_unused_firewalls": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Network/azureFirewalls/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.network/azurefirewalls/"},
        ]},
    ],
    # ── Azure App Service Plans ──────────────────────────────────────────────
    "azure_unused_app_service_plans": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Web/serverfarms/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.web/serverfarms/"},
        ]},
    ],
    # ── Azure SQL ────────────────────────────────────────────────────────────
    "azure_rightsize_sql_instances": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Sql/servers/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.sql/servers/"},
        ]},
    ],
    "azure_rightsize_managed_sql": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.Sql/managedInstances/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.sql/managedinstances/"},
        ]},
    ],
    # ── Azure MySQL Flexible ─────────────────────────────────────────────────
    "azure_rightsize_mysql_flexible": [
        {"type": "or", "expressions": [
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/Microsoft.DBforMySQL/"},
            {"dimension": "resource_id", "type": "substring",
             "substring": "/providers/microsoft.dbformysql/"},
        ]},
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Boilerplate PT blocks (constant across all enriched templates)
# ─────────────────────────────────────────────────────────────────────────────

FLEXERA_CREDENTIAL = '''\
credentials "auth_flexera" do
  schemes "oauth2"
  label "Flexera"
  description "Select Flexera One OAuth2 credentials"
  tags "provider=flexera"
end
'''

BOILERPLATE_DATASOURCES = '''\
datasource "ds_flexera_api_hosts" do
  run_script $js_flexera_api_hosts, rs_optima_host
end

script "js_flexera_api_hosts", type: "javascript" do
  parameters "rs_optima_host"
  result "result"
  code <<-'EOS'
  host_table = {
    "api.optima.flexeraeng.com": {
      flexera: "api.flexera.com"
    },
    "api.optima-eu.flexeraeng.com": {
      flexera: "api.flexera.eu"
    },
    "api.optima-apac.flexeraeng.com": {
      flexera: "api.flexera.au"
    }
  }
  result = host_table[rs_optima_host]
EOS
end

datasource "ds_billing_centers" do
  request do
    auth $auth_flexera
    host rs_optima_host
    path join(["/analytics/orgs/", rs_org_id, "/billing_centers"])
    query "view", "allocation_table"
    header "Api-Version", "1.0"
    header "User-Agent", "RS Policies"
    ignore_status [403]
  end
  result do
    encoding "json"
    collect jmes_path(response, "[*]") do
      field "href", jmes_path(col_item, "href")
      field "id", jmes_path(col_item, "id")
      field "name", jmes_path(col_item, "name")
      field "parent_id", jmes_path(col_item, "parent_id")
    end
  end
end

datasource "ds_top_level_bcs" do
  run_script $js_top_level_bcs, $ds_billing_centers
end

script "js_top_level_bcs", type: "javascript" do
  parameters "ds_billing_centers"
  result "result"
  code <<-'EOS'
  filtered_bcs = _.filter(ds_billing_centers, function(bc) {
    return bc['parent_id'] == null || bc['parent_id'] == undefined
  })
  result = _.compact(_.pluck(filtered_bcs, 'id'))
EOS
end

'''

# Template for the /costs/select datasource.  %s is replaced with vendor.
COST_QUERY_TEMPLATE = '''\
datasource "ds_cost_resources" do
  request do
    run_script $js_cost_resources_request, $ds_top_level_bcs, rs_org_id, rs_optima_host
  end
  result do
    encoding "json"
    collect jmes_path(response, "rows[*]") do
      field "resource_id", jmes_path(col_item, "dimensions.resource_id")
      field "vendor_account", jmes_path(col_item, "dimensions.vendor_account")
      field "vendor_account_name", jmes_path(col_item, "dimensions.vendor_account_name")
      field "cost", jmes_path(col_item, "metrics.cost_amortized_unblended_adj")
    end
  end
end

script "js_cost_resources_request", type: "javascript" do
  parameters "ds_top_level_bcs", "rs_org_id", "rs_optima_host"
  result "request"
  code <<-'EOS'
  // 3-month window using month granularity
  var now = new Date()
  var end_year = now.getFullYear()
  var end_m = now.getMonth() + 2
  if (end_m > 12) { end_year += 1; end_m -= 12 }
  var end_month = end_year + "-" + ("0" + end_m).slice(-2)

  var start = new Date(now.getFullYear(), now.getMonth() - 2, 1)
  var start_month = start.getFullYear() + "-" + ("0" + (start.getMonth() + 1)).slice(-2)

  var request = {
    auth: "auth_flexera",
    host: rs_optima_host,
    verb: "POST",
    path: "/bill-analysis/orgs/" + rs_org_id + "/costs/select",
    body_fields: {
      "dimensions": ["resource_id", "vendor_account", "vendor_account_name"],
      "granularity": "month",
      "start_at": start_month,
      "end_at": end_month,
      "metrics": ["cost_amortized_unblended_adj"],
      "billing_center_ids": ds_top_level_bcs,
      "limit": 100000,
      "filter": {
        "type": "and",
        "expressions": [
          {
            "dimension": "vendor",
            "type": "equal",
            "value": "%s"
          }%s,
          {
            "type": "not",
            "expression": {
              "dimension": "adjustment_name",
              "type": "substring",
              "substring": "Shared"
            }
          }
        ]
      }
    },
    headers: {
      "User-Agent": "RS Policies",
      "Api-Version": "1.0"
    },
    ignore_status: [400]
  }
EOS
end

'''

# ─────────────────────────────────────────────────────────────────────────────
# Generator functions
# ─────────────────────────────────────────────────────────────────────────────

def _format_extra_filter_exprs(extra_exprs):
    """Format extra filter expression dicts for insertion into COST_QUERY_TEMPLATE.

    Returns an empty string when extra_exprs is empty, or a string that starts
    with ',\n' and contains JSON-formatted expression dicts separated by ',\n',
    ready for the ``}%s,`` slot in COST_QUERY_TEMPLATE.
    """
    if not extra_exprs:
        return ''
    parts = []
    for expr in extra_exprs:
        raw = json.dumps(expr, indent=2)
        lines = raw.split('\n')
        # Align each expression at 10 spaces to match the surrounding template
        indented = '\n'.join('          ' + line for line in lines)
        parts.append(indented)
    return ',\n' + ',\n'.join(parts)

def gen_header(name, version, cloud, service, policy_set, recommendation_type, enrich):
    """Generate metadata, parameters, and optionally the auth_flexera credential."""
    lines = [
        '# DEMO POLICY TEMPLATE. DOES NOT PRODUCE REAL RESULTS.',
        '# More info available here: https://github.com/flexera-public/cco_demo',
        'name "%s [Demo]"' % name,
        'rs_pt_ver 20180301',
        'type "policy"',
        'short_description "Demo policy template that generates sample recommendations.'
        ' See the [README](https://github.com/flexera-public/cco_demo) for more details."',
        'long_description ""',
        '# This is to make it easy to identify this template as a demo template via API',
        'doc_link "https://github.com/flexera-public/cco_demo"',
        'category "Cost"',
        'severity "low"',
        'default_frequency "weekly"',
        'info(',
        '  version: "%s",' % version,
        '  provider: "%s",' % cloud,
        '  service: "%s",' % service,
        '  policy_set: "%s",' % policy_set,
        '  recommendation_type: "%s",' % recommendation_type,
        '  hide_skip_approvals: "true",',
        '  demo: "true"',
        ')',
    ]
    result = '\n'.join(lines) + '\n'

    result += '\n###############################################################################\n'
    result += '# Parameters\n'
    result += '###############################################################################\n\n'
    result += (
        '# This is to make it easy for automation to determine if an applied policy is\n'
        '# a demo policy or not.\n'
        'parameter "param_demo" do\n'
        '  type "string"\n'
        '  category "Policy Settings"\n'
        '  label "Demo Policy"\n'
        '  description "Indicates that this is a demo policy.'
        ' Should generally be left at its default value."\n'
        '  allowed_values "True", "False"\n'
        '  default "True"\n'
        'end\n'
    )

    if enrich:
        result += '\n###############################################################################\n'
        result += '# Credentials\n'
        result += '###############################################################################\n\n'
        result += FLEXERA_CREDENTIAL

    result += '\n###############################################################################\n'
    result += '# Datasources & Scripts\n'
    result += '###############################################################################\n\n'

    return result


def gen_seed_datasources(incidents):
    """Generate datasources that fetch static seed data from GitHub."""
    result = ""
    for incident in incidents:
        incident_path = incident.get("path", "")
        ds_name = "ds_" + Path(incident_path).stem
        result += 'datasource "%s" do\n' % ds_name
        result += '  request do\n'
        result += '    verb "GET"\n'
        result += '    host "raw.githubusercontent.com"\n'
        result += '    path "/flexera-public/cco_demo/refs/heads/main/%s"\n' % incident_path
        result += '  end\n'
        result += 'end\n\n'
    return result


def gen_cost_query(vendor, extra_exprs=None):
    """Generate the /costs/select datasource filtered by vendor and optional extra expressions."""
    extra_block = _format_extra_filter_exprs(extra_exprs or [])
    return COST_QUERY_TEMPLATE % (vendor, extra_block)


def gen_merge_datasource(idx, seed_ds_name, offset, filter_expr, strip_prefix=""):
    """Generate a datasource + script that merges cost data onto seed data.

    idx:          1-based incident index (for unique naming)
    seed_ds_name: name of the seed datasource (e.g. ds_aws_rightsize_ec2_instances_1)
    offset:       number of cost rows to skip (for multi-incident deduplication)
    filter_expr:  JS boolean expression using `rid` (lowercased resource_id) to
                  restrict which cost rows are eligible, or empty string for no filter
    strip_prefix: optional string prefix to strip from cost API resource_id before
                  assigning to new_resource_id (e.g. "snapshot/" for EC2 snapshots)
    """
    merge_ds = 'ds_merged_%d' % idx
    merge_js = 'js_merged_%d' % idx

    result = 'datasource "%s" do\n' % merge_ds
    result += '  run_script $%s, $ds_cost_resources, $%s\n' % (merge_js, seed_ds_name)
    result += 'end\n\n'

    result += 'script "%s", type: "javascript" do\n' % merge_js
    result += '  parameters "ds_cost_resources", "ds_seed"\n'
    result += '  result "result"\n'
    result += "  code <<-'EOS'\n"
    result += _merge_js_code(offset, filter_expr, strip_prefix)
    result += 'EOS\n'
    result += 'end\n\n'

    return result


def _merge_js_code(offset, filter_expr, strip_prefix=""):
    """Return the JavaScript that merges cost rows onto seed data."""
    if filter_expr:
        filter_block = (
            '  // Keep only rows whose resource_id matches the expected format for this template\n'
            '  var all_rows = _.filter(_.values(cost_by_id), function(e) {\n'
            '    var rid = e[\'resource_id\'].toLowerCase()\n'
            '    return %s\n'
            '  })\n'
        ) % filter_expr
    else:
        filter_block = '  var all_rows = _.values(cost_by_id)\n'

    if strip_prefix:
        strip_block = (
            "      // Strip '" + strip_prefix + "' prefix from resource_id when present (cost API vendor format)\n"
            "      if (new_resource_id.indexOf('" + strip_prefix + "') === 0) "
            "new_resource_id = new_resource_id.slice(" + str(len(strip_prefix)) + ")\n"
        )
    else:
        strip_block = ''

    return (
        '  // Group cost rows by resource_id, sum cost across months\n'
        '  var cost_by_id = {}\n'
        '  _.each(ds_cost_resources, function(row) {\n'
        '    if (!row[\'resource_id\'] || row[\'resource_id\'] === \'\') return\n'
        '    if (!cost_by_id[row[\'resource_id\']]) {\n'
        '      cost_by_id[row[\'resource_id\']] = {\n'
        '        resource_id: row[\'resource_id\'],\n'
        '        vendor_account: row[\'vendor_account\'] || \'\',\n'
        '        vendor_account_name: row[\'vendor_account_name\'] || \'\',\n'
        '        cost: 0\n'
        '      }\n'
        '    }\n'
        '    cost_by_id[row[\'resource_id\']].cost += row[\'cost\']\n'
        '  })\n\n'
        + filter_block +
        '\n'
        '  // Sort by total cost descending and skip offset for multi-incident templates\n'
        '  var sorted = _.sortBy(all_rows, function(e) { return -e.cost })\n'
        '  sorted = sorted.slice(%d)\n\n'
        '  // Overlay real resource identifiers onto seed data\n'
        '  var result = []\n'
        '  for (var i = 0; i < ds_seed.length; i++) {\n'
        '    var item = {}\n'
        '    _.each(_.keys(ds_seed[i]), function(k) { item[k] = ds_seed[i][k] })\n'
        '    if (i < sorted.length) {\n'
        '      var c = sorted[i]\n'
        '      // Capture old seed identity values before replacing, for substring substitution\n'
        '      var old_account_id   = String(item[\'accountID\']  !== undefined ? item[\'accountID\']  : \'\')\n'
        '      var old_account_name = String(item[\'accountName\'] !== undefined ? item[\'accountName\'] : \'\')\n'
        '      var old_resource_id  = String(item[\'resourceID\'] !== undefined ? item[\'resourceID\']  : (item[\'id\'] !== undefined ? item[\'id\'] : \'\'))\n'
        '      var new_account_id   = c[\'vendor_account\']\n'
        '      var new_account_name = c[\'vendor_account_name\']\n'
        '      var new_resource_id  = c[\'resource_id\']\n'
        + strip_block +
        '      // Replace top-level identity fields\n'
        '      if (item.hasOwnProperty(\'accountID\'))   item[\'accountID\']   = new_account_id\n'
        '      if (item.hasOwnProperty(\'accountName\')) item[\'accountName\'] = new_account_name\n'
        '      if (item.hasOwnProperty(\'resourceID\'))  item[\'resourceID\']  = new_resource_id\n'
        '      if (item.hasOwnProperty(\'id\'))          item[\'id\']          = new_resource_id\n'
        '      // Replace embedded occurrences of those values in all other string fields\n'
        '      // (e.g. recommendationDetails, resourceARN, chartUrlField, resourceGroup)\n'
        '      var replacements = []\n'
        '      if (old_resource_id  && old_resource_id  !== new_resource_id)  replacements.push([old_resource_id,  new_resource_id])\n'
        '      if (old_account_id   && old_account_id   !== new_account_id)   replacements.push([old_account_id,   new_account_id])\n'
        '      if (old_account_name && old_account_name !== new_account_name) replacements.push([old_account_name, new_account_name])\n'
        '      _.each(_.keys(item), function(k) {\n'
        '        if (k === \'accountID\' || k === \'accountName\' || k === \'resourceID\' || k === \'id\') return\n'
        '        if (typeof item[k] !== \'string\') return\n'
        '        _.each(replacements, function(pair) { item[k] = item[k].split(pair[0]).join(pair[1]) })\n'
        '      })\n'
        '    }\n'
        '    result.push(item)\n'
        '  }\n'
    ) % offset


def gen_policy_block(incidents, enrich):
    """Generate the full policy block including all validate_each blocks."""
    result = '###############################################################################\n'
    result += '# Policy\n'
    result += '###############################################################################\n\n'
    result += 'policy "pol_incident" do\n'

    for idx, incident in enumerate(incidents, start=1):
        incident_path = incident.get("path", "")
        summary_template = incident.get("summary_template", "")
        fields = incident.get("export", [])

        if enrich:
            ds_ref = "ds_merged_%d" % idx
        else:
            ds_ref = "ds_" + Path(incident_path).stem

        resource_level = "true" if any(f.get("name") == "id" for f in fields) else "false"

        result += '  validate_each $%s do\n' % ds_ref
        result += '    summary_template "%s"\n' % summary_template
        result += '    check eq(0, 1)\n'
        result += '    export do\n'
        result += '      resource_level %s\n' % resource_level

        for field in fields:
            result += '      field "%s" do\n' % field.get("name", "")
            result += '        label "%s"\n' % field.get("label", "")
            result += '      end\n'

        result += '    end\n'
        result += '  end\n'

    result += 'end\n'
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

        enrich = filename not in SKIP_ENRICHMENT and cloud in CLOUD_TO_VENDOR

        # ── Build template ──
        file_contents = gen_header(
            name, version, cloud, service, policy_set, recommendation_type, enrich
        )

        if enrich:
            file_contents += BOILERPLATE_DATASOURCES
            file_contents += gen_seed_datasources(incidents)
            cost_api_filter = COST_API_FILTERS.get(filename, [])
            file_contents += gen_cost_query(CLOUD_TO_VENDOR[cloud], cost_api_filter)

            filter_expr = RESOURCE_ID_FILTERS.get(filename, "")
            strip_prefix = RESOURCE_ID_STRIP_PREFIX.get(filename, "")

            # Compute per-incident offsets so each incident gets unique cost rows
            offset = 0
            for idx, incident in enumerate(incidents, start=1):
                incident_path = incident.get("path", "")
                seed_ds_name = "ds_" + Path(incident_path).stem

                file_contents += gen_merge_datasource(idx, seed_ds_name, offset, filter_expr, strip_prefix)

                # Count seed entries to advance offset for next incident
                seed_file = Path(incident_path)
                if seed_file.exists():
                    with open(seed_file, "r", encoding="utf-8") as sf:
                        offset += len(json.load(sf))
        else:
            file_contents += gen_seed_datasources(incidents)

        file_contents += gen_policy_block(incidents, enrich)

        # ── Write output ──
        specific_out_dir = OUT_DIR / cloud.lower()
        specific_out_dir.mkdir(parents=True, exist_ok=True)

        out_path = specific_out_dir / f"{filename}.pt"
        with open(out_path, "w", encoding="utf-8") as out:
            out.write(file_contents)

        status = "enriched" if enrich else "static"
        print(f"[OK] wrote {out_path}  ({status})")


if __name__ == "__main__":
    main()
