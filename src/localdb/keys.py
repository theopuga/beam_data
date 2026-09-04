"""Identifier key standardization: registry of kinds, each with a cleaner.

Shipped kinds: postal_code, fsa, client_id, phone, email — plus the
country-aware postal kinds uk_postcode, cep, plz — registered at import.
New kinds register via `register_kind` without touching link logic; pass
overwrite=True to replace a shipped cleaner with a project-specific one.
"""

from collections.abc import Callable

import pandas as pd

_REGISTRY: dict[str, Callable[[pd.Series], pd.Series]] = {}


def register_kind(kind: str, cleaner: Callable[[pd.Series], pd.Series],
                  overwrite: bool = False) -> None:
    """Register a cleaning function under a key `kind` name."""
    if kind in _REGISTRY and not overwrite:
        raise ValueError(f"kind {kind!r} already registered; pass overwrite=True to replace")
    _REGISTRY[kind] = cleaner


def standardize(df: pd.DataFrame, column: str, kind: str) -> pd.DataFrame:
    """Apply the cleaning function registered for `kind` to df[column], in place.

    Values are coerced to pandas StringDtype first: missing values stay
    missing (pd.NA) rather than becoming the string "nan".
    """
    cleaner = _REGISTRY.get(kind)
    if cleaner is None:
        raise KeyError(f"Unknown key kind: {kind!r}. Registered: {sorted(_REGISTRY)}")
    df[column] = cleaner(df[column].astype("string"))
    return df


def _clean_postal_code(col: pd.Series) -> pd.Series:
    """Uppercase, drop spaces/hyphens; US ZIP+4 (9 digits) collapses to ZIP5."""
    s = col.str.upper().str.replace(r"[\s\-]", "", regex=True)
    return s.str.replace(r"^(\d{5})\d{4}$", r"\1", regex=True)


def _clean_fsa(col: pd.Series) -> pd.Series:
    """Canadian FSA: first 3 chars of a cleaned postal code (A1A); null otherwise."""
    return _clean_postal_code(col).str.extract(r"^([A-Z]\d[A-Z])", expand=False)


def _clean_uk_postcode(col: pd.Series) -> pd.Series:
    """UK postcode: uppercase, canonical single-space format (EC1A 1BB).

    Invalid formats (not outcode+incode) become null rather than guessed.
    """
    s = col.str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    parts = s.str.extract(r"^([A-Z]{1,2}\d[A-Z\d]?)(\d[A-Z]{2})$", expand=True)
    return parts[0].str.cat(parts[1], sep=" ")


def _clean_cep(col: pd.Series) -> pd.Series:
    """Brazilian CEP: digits only, canonical 12345-678 format; invalid -> null."""
    digits = col.str.replace(r"\D", "", regex=True)
    formatted = digits.str.replace(r"^(\d{5})(\d{3})$", r"\1-\2", regex=True)
    return formatted.where(digits.str.len() == 8)


def _clean_plz(col: pd.Series) -> pd.Series:
    """German/CH/AT-style PLZ: digits only (DE/CH 5, AT 4 — kept as-is)."""
    return col.str.replace(r"\D", "", regex=True)


def _clean_client_id(col: pd.Series) -> pd.Series:
    """Strip all whitespace, uppercase."""
    return col.str.replace(r"\s+", "", regex=True).str.upper()


def _clean_phone(col: pd.Series) -> pd.Series:
    """Digits only; NANP leading country code 1 dropped (11 -> 10 digits)."""
    s = col.str.replace(r"\D", "", regex=True)
    return s.str.replace(r"^1(\d{10})$", r"\1", regex=True)


def _clean_email(col: pd.Series) -> pd.Series:
    """Trim and lowercase."""
    return col.str.strip().str.lower()


register_kind("postal_code", _clean_postal_code)
register_kind("fsa", _clean_fsa)
register_kind("uk_postcode", _clean_uk_postcode)
register_kind("cep", _clean_cep)
register_kind("plz", _clean_plz)
register_kind("client_id", _clean_client_id)
register_kind("phone", _clean_phone)
register_kind("email", _clean_email)
