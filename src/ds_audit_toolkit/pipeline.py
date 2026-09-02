"""End-to-end orchestration: connect, standardize, join + audit, validate, flag."""

from typing import Any


def run_audit(config_path: str) -> Any:
    """Run the full audit pipeline defined by a YAML config.

    Stages:
        1. Connect to declared sources and pull tables.
        2. Standardize join keys per configured key_type.
        3. Join and audit match quality (fuzzy fallback below threshold).
        4. Validate against (or auto-draft) the checked-in schema.
        5. If target_column is set, run feature flagging.

    Returns a report object; see reporting/.
    """
    raise NotImplementedError("pipeline orchestration lands in Phase 7")
