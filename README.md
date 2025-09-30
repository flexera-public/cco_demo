# Flexera CCO Demo Data

This repository contains fictional demo data, and demo policy templates, to use in the Flexera One platform. The purpose is to enable the demonstration of the platform's functionality without the need to unnecessarily pay for a large number of cloud assets to produce *real* optimization recommendations.

## Accessing Demo Policy Templates

Switch to the `main` branch and navigate to the "templates" directory (or [click this link](https://github.com/flexera-public/cco_demo/tree/main/templates) as a shortcut). There you will find the current templates to use.

## Development Flow

Generation of demo policy templates is partially automated via scripts. Branch the repository, follow the below flow to make any updates, and then make a pull request back to the `main` branch in order to update assets.

The following flow should be followed to create/update demo policy templates and data:

1. Create and switch to a development branch.
2. Modify "lists/template_list.json" as needed to add any policy templates from the catalog that we want to demo (if needed).
3. Run the "scripts/generate_template_schema.py" script from the root directory of the repository. This will scrape the policy templates listed in "lists/template_list.json" to create schema that we can generate demo policy templates from.
4. Run the "scripts/generate_fake_templates.py" script from the root directory of the repository. This will use the schema created above to create and store updated demo policy templates in the "templates" directory.
5. Create/update demo data in the "generated_data/fake_incident_tables" directory. More details on how to do this are below.
6. Make a pull request to the `main` branch with your updates and merge it after review.

## Creating Demo Data

Demo data for the demo policy templates is stored in the "generated_data/fake_incident_tables" directory. The data should be a flat list, in JSON format, containing all of the incident fields expected by the relevant demo policy template. Each file should be named after the policy template and the incident number it applies to.

Example:

- There is a demo policy template named "aws_rightsize_ec2_instances.pt" that raises 2 incidents.
  - There should be two files in "generated_data/fake_incident_tables" for this demo policy template:
    - aws_rightsize_ec2_instances_1.json for the first incident.
    - aws_rightsize_ec2_instances_2.json for the second incident.
- There is a demo policy template named "aws_delete_old_snapshots.pt" that raises 1 incident.
  - There should be one file in "generated_data/fake_incident_tables" for this demo policy template:
    - aws_delete_old_snapshots_1.json for the first and only incident.

Generating the demo data itself is up to you. The goal should be to make the demo data fake (it should not reference real infrastructure) but believable, and to have enough entries to look like a plausible result when using the real policy template. Tools such as LLMs may be useful in generating realistic enough data, provided they are prompted well and given good starting data to build from.
