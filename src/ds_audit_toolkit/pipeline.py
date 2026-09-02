"""End-to-end orchestration: connect, standardize, join + audit, validate, flag.

Dependency direction is one-way:
    pipeline -> {connectors, standardize, join_audit, schema_validate,
                 feature_flags, reporting} -> {types, config}
Stages never import each other; they exchange dataclasses from types.py.
"""

from ds_audit_toolkit.types import RunReport


def run_audit(config_path: str) -> RunReport:
    """Run the full audit pipeline defined by a YAML config.

    Stages:
        1. Connect to declared sources and pull tables (connectors).
        2. Standardize join keys per configured key_type (standardize).
        3. Join and audit match quality (join_audit; fuzzy fallback below
           the configured threshold).
        4. Validate against (or auto-draft) the checked-in schema
           (schema_validate).
        5. If target_column is set, run feature flagging (feature_flags).

    Returns a single RunReport artifact.
    """
    raise NotImplementedError("pipeline orchestration lands in Phase 7")
