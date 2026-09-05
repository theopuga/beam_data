"""Data-quality advisories: what pandas read but quietly left as object dtype."""

import re

import pandas as pd

# Symbols stripped from both ends before the numeric check; a "%" column is
# still numeric semantics (the scale is the reader's business, this only flags).
_CURRENCY_CHARS = "$€£¥%"
# Values treated as missing: neither evidence for nor against numeric.
_MISSING = {"", "na", "n/a", "nan", "null", "none", "-"}

_SIMPLE = re.compile(r"^\d+(?:([.,])(\d+))?$")
_SPACE_GROUPED = re.compile(r"^\d{1,3}(?:[ \u00a0]\d{3})+(?:([.,])(\d+))?$")
_GROUPED = re.compile(r"^\d{1,3}([.,])\d{3}(?:\1\d{3})*(?:((?!\1)[.,])\d+)?$")


def _decimal_mark(raw: str) -> str | None:
    """The decimal mark if the string parses as a number under some local
    convention ("1 234,56", "1,234.56", "$12.50", "45%"), else None ("").
    Plain integers return ""; grouped forms use their single separator."""
    s = raw.strip().strip(_CURRENCY_CHARS).strip()
    if s and s[0] in "+-":
        s = s[1:]
    m = _SIMPLE.match(s) or _SPACE_GROUPED.match(s) or _GROUPED.match(s)
    if m is None:
        return None
    return m.group(1) or m.group(2) or ""


def numeric_advisory(df: pd.DataFrame, threshold: float = 0.9) -> pd.DataFrame:
    """Flag non-numeric columns whose values mostly parse as numbers.

    Mixed-decimal columns ("1 234,56" next to "1234.56") stay object dtype
    after a read, silently breaking sums and joins downstream. This is an
    advisory report, not a fix: one row per flagged column, empty when
    nothing looks suspect. Missing-like values ("N/A", "-", blanks) are
    excluded from the evidence; columns already numeric/bool/datetime are
    never scanned. Note plain digit strings (e.g. bare phone numbers) parse
    as numbers — that ambiguity is exactly what the report surfaces.

    threshold= minimum share of non-null values that must parse (per
    convention) for the column to be flagged.
    """
    rows: list[dict] = []
    for col in df.columns:
        series = df[col]
        if (pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series)
                or pd.api.types.is_datetime64_any_dtype(series)):
            continue
        values = series.dropna().astype(str).str.strip()
        values = values[~values.str.lower().isin(_MISSING)]
        if values.empty:
            continue
        marks = [_decimal_mark(v) for v in values]
        parseable = [m for m in marks if m is not None]
        share = len(parseable) / len(values)
        if share < threshold:
            continue
        unparsed = sorted({v for v, m in zip(values, marks) if m is None})[:5]
        decimals = [m for m in parseable if m]
        decimal = pd.Series(decimals).mode().iloc[0] if decimals else ""
        rows.append({
            "column": col,
            "non_null": len(values),
            "parseable_share": round(share, 3),
            "decimal": decimal,
            "unparsed_examples": unparsed,
        })
    return pd.DataFrame(
        rows,
        columns=["column", "non_null", "parseable_share", "decimal", "unparsed_examples"],
    )
