"""Reader registry: extension -> pandas loader."""

from localdb.readers.core import read, register_reader, supported_extensions

__all__ = ["read", "register_reader", "supported_extensions"]
