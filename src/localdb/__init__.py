"""localdb: query already-downloaded data files as a local database.

No connections, no servers: a folder of CSV/Parquet/JSON files (or a SQLite
file) is treated as the database itself.

    import localdb

    df = localdb.read("data/clients.csv")          # single file
    db = localdb.connect("data/downloads/")        # folder as database
    db.list_tables()
    df = db.get_table("clients")
    df = db.query("SELECT * FROM clients JOIN refs USING (id)")  # optional duckdb
"""

from pathlib import Path

from localdb.catalog import load_catalog
from localdb.database import Database
from localdb.readers.core import read, register_reader, supported_extensions

__version__ = "0.1.0"

__all__ = [
    "Database",
    "__version__",
    "connect",
    "load_catalog",
    "read",
    "register_reader",
    "supported_extensions",
]


def connect(path: str | Path) -> Database:
    """Open a downloaded data folder (or SQLite file) as a Database."""
    return Database(path)
