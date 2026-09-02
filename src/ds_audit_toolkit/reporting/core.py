"""Jinja2-rendered run report: join audit, schema validation, feature flags.

Meant to be attachable to a PR, doc, or review — audit evidence, not just
console output. Templates are inline strings (no filesystem dependency):
html renders with autoescape on, markdown stays plain text. Every section
(stages, join audit, schema validation, feature flags) is optional — a None
or empty section renders an explicit placeholder instead of failing.
"""

from pathlib import Path

from jinja2 import Environment

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Audit run {{ run_id }}</title>
<style>
body { font-family: sans-serif; margin: 2rem; }
table { border-collapse: collapse; margin: 0.5rem 0; }
th, td { border: 1px solid #999; padding: 0.25rem 0.6rem; text-align: left; }
th { background: #eee; }
</style>
</head>
<body>
<h1>Audit run {{ run_id }}</h1>
<p>config: <code>{{ config_path }}</code></p>

<h2>Stages</h2>
{% if stages %}
<table>
<tr><th>stage</th><th>status</th><th>error</th></tr>
{% for stage in stages %}
<tr>
<td>{{ stage.stage }}</td>
<td>{{ stage.status }}</td>
<td>{{ stage.error if stage.error else "" }}</td>
</tr>
{% endfor %}
</table>
{% else %}
<p>No stages recorded.</p>
{% endif %}

{% if join_audit %}
<h2>Join audit</h2>
<p>
match rate {{ "%.1f"|format(join_audit.match_rate * 100) }}%
vs threshold {{ "%.1f"|format(join_audit.match_threshold * 100) }}%;
matched rows {{ join_audit.matched_rows }}
</p>
{% if join_audit.unmatched_keys %}
<p>Unmatched keys (sample): {{ join_audit.unmatched_keys|join(", ") }}</p>
{% endif %}
{% if join_audit.column_mismatch_rates %}
<table>
<tr><th>column</th><th>mismatch rate</th></tr>
{% for column, rate in join_audit.column_mismatch_rates.items() %}
<tr><td>{{ column }}</td><td>{{ "%.1f"|format(rate * 100) }}%</td></tr>
{% endfor %}
</table>
{% endif %}
{% if join_audit.key_quality %}
<h3>Key quality</h3>
<p>
duplicates: left={{ join_audit.key_quality.duplicates.get("left", 0) }},
right={{ join_audit.key_quality.duplicates.get("right", 0) }};
nulls: left={{ join_audit.key_quality.nulls.get("left", 0) }},
right={{ join_audit.key_quality.nulls.get("right", 0) }}
</p>
{% if join_audit.key_quality.dtype_mismatches %}
<ul>
{% for mismatch in join_audit.key_quality.dtype_mismatches %}
<li>{{ mismatch }}</li>
{% endfor %}
</ul>
{% endif %}
{% endif %}
<p>fuzzy fallback used: {{ "yes" if join_audit.fuzzy_used else "no" }}</p>
{% if join_audit.fuzzy_confidence %}
<table>
<tr><th>key</th><th>best fuzzy score</th></tr>
{% for key, score in join_audit.fuzzy_confidence.items() %}
<tr><td>{{ key }}</td><td>{{ "%.3f"|format(score) }}</td></tr>
{% endfor %}
</table>
{% endif %}
{% else %}
<p>No join audit for this run.</p>
{% endif %}

{% if schema_validation %}
<h2>Schema validation</h2>
<p>
dataset {{ schema_validation.dataset }}:
{{ "passed" if schema_validation.passed else "FAILED" }}
{% if schema_validation.schema_path %}({{ schema_validation.schema_path }}){% endif %}
</p>
{% if schema_validation.failures %}
<ul>
{% for failure in schema_validation.failures %}
<li>{{ failure }}</li>
{% endfor %}
</ul>
{% endif %}
{% else %}
<p>No schema validation for this run.</p>
{% endif %}

{% if feature_flags and feature_flags.flags %}
<h2>Feature flags</h2>
<p>target: {{ feature_flags.target_column }}</p>
<table>
<tr><th>column</th><th>leak score</th><th>predictive score</th><th>reason</th></tr>
{% for flag in feature_flags.flags|sort(attribute="leak_score", reverse=true) %}
<tr>
<td>{{ flag.column }}</td>
<td>{{ "%.2f"|format(flag.leak_score) }}</td>
<td>{{ "%.2f"|format(flag.predictive_score) }}</td>
<td>{{ flag.reason }}</td>
</tr>
{% endfor %}
</table>
{% else %}
<p>No feature flags for this run.</p>
{% endif %}
</body>
</html>
"""

_MARKDOWN_TEMPLATE = """# Audit run {{ run_id }}

config: `{{ config_path }}`

## Stages

{% if stages %}
| stage | status | error |
|---|---|---|
{% for stage in stages %}
| {{ stage.stage }} | {{ stage.status }} | {{ stage.error if stage.error else "" }} |
{% endfor %}
{% else %}
No stages recorded.
{% endif %}

{% if join_audit %}
{% set rate = "%.1f"|format(join_audit.match_rate * 100) %}
{% set threshold = "%.1f"|format(join_audit.match_threshold * 100) %}
## Join audit

- match rate: {{ rate }}% (threshold {{ threshold }}%)
- matched rows: {{ join_audit.matched_rows }}
{% if join_audit.unmatched_keys %}
- unmatched keys (sample): {{ join_audit.unmatched_keys|join(", ") }}
{% endif %}
{% if join_audit.column_mismatch_rates %}
{% for column, mismatch in join_audit.column_mismatch_rates.items() %}
- column mismatch `{{ column }}`: {{ "%.1f"|format(mismatch * 100) }}%
{% endfor %}
{% endif %}
{% if join_audit.key_quality %}
{% set dup = join_audit.key_quality.duplicates %}
{% set nulls = join_audit.key_quality.nulls %}
- key duplicates: left={{ dup.get("left", 0) }}, right={{ dup.get("right", 0) }}
- key nulls: left={{ nulls.get("left", 0) }}, right={{ nulls.get("right", 0) }}
{% for mismatch in join_audit.key_quality.dtype_mismatches %}
- key dtype mismatch: {{ mismatch }}
{% endfor %}
{% endif %}
- fuzzy fallback used: {{ "yes" if join_audit.fuzzy_used else "no" }}
{% if join_audit.fuzzy_confidence %}
{% for key, score in join_audit.fuzzy_confidence.items() %}
- fuzzy match `{{ key }}`: best score {{ "%.3f"|format(score) }}
{% endfor %}
{% endif %}
{% else %}
No join audit for this run.
{% endif %}

{% if schema_validation %}
## Schema validation

dataset {{ schema_validation.dataset }}:
{{ "passed" if schema_validation.passed else "FAILED" }}
{% if schema_validation.schema_path %}({{ schema_validation.schema_path }}){% endif %}

{% for failure in schema_validation.failures %}
- {{ failure }}
{% endfor %}
{% else %}
No schema validation for this run.
{% endif %}

{% if feature_flags and feature_flags.flags %}
## Feature flags

target: {{ feature_flags.target_column }}

| column | leak score | predictive score | reason |
|---|---|---|---|
{% for flag in feature_flags.flags|sort(attribute="leak_score", reverse=true) %}
{% set leak = "%.2f"|format(flag.leak_score) %}
{% set predictive = "%.2f"|format(flag.predictive_score) %}
| {{ flag.column }} | {{ leak }} | {{ predictive }} | {{ flag.reason }} |
{% endfor %}
{% else %}
No feature flags for this run.
{% endif %}
"""

_TEMPLATES = {"html": _HTML_TEMPLATE, "markdown": _MARKDOWN_TEMPLATE}


def render_report(run_results: dict, output_path: str, fmt: str = "html") -> str:
    """Combine run results into a single HTML (or markdown) report file.

    Args:
        run_results: keys `run_id`, `config_path`, `stages`, `join_audit`,
            `schema_validation`, `feature_flags` — the same mapping that
            types.RunReport.save passes. Any report section may be None or
            empty; it then renders as a placeholder.
        output_path: destination file path (parent directories are created).
        fmt: "html" (autoescaped) or "markdown"; anything else raises
            ValueError.

    Returns:
        The output_path the report was written to.
    """
    if fmt not in _TEMPLATES:
        raise ValueError(
            f"unsupported report format {fmt!r}; expected one of {sorted(_TEMPLATES)}"
        )
    environment = Environment(
        autoescape=fmt == "html", trim_blocks=True, lstrip_blocks=True
    )
    rendered = environment.from_string(_TEMPLATES[fmt]).render(**run_results)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return output_path
