"""Jinja2-rendered run report: join audit, schema validation, feature flags.

Meant to be attachable to a PR, doc, or review — audit evidence, not just
console output.
"""



def render_report(run_results: dict, output_path: str, fmt: str = "html") -> str:
    """Combine run results into a single HTML (or markdown) report file."""
    raise NotImplementedError("reporting lands in Phase 7")
