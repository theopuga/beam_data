"""localdb: connect to tables you already downloaded.

No connections, no servers: a folder of CSV/Parquet/JSON files (or a SQLite
file) is a set of tables you can open by name and join with SQL.

    import localdb

    df = localdb.read("data/clients.csv")          # single file
    ts = localdb.tables("data/downloads/")         # the folder's tables
    ts.names()                                     # ["clients", "refs", ...]
    df = ts.get("clients")
    df = ts.query("SELECT * FROM clients JOIN refs USING (id)")  # needs localdb[sql]
"""

from pathlib import Path

from localdb.catalog import load_catalog
from localdb.readers.core import read, register_reader, supported_extensions
from localdb.tables import Tables

__version__ = "0.1.0"

__all__ = [
    "Tables",
    "__version__",
    "load_catalog",
    "read",
    "register_reader",
    "supported_extensions",
    "tables",
]


def tables(path: str | Path) -> Tables:
    """Connect to the tables in a downloaded data folder (or SQLite file)."""
    return Tables(path)
