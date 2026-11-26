"""iact-perf: a community database of published Cherenkov telescope performances."""

from . import units  # noqa: F401  (registers the Crab unit with astropy)
from .catalog import validate_repository
from .database import Database, load
from .records import Record, read_record, write_record
from .schema import SCHEMA_VERSION

__all__ = [
    "SCHEMA_VERSION",
    "Database",
    "Record",
    "load",
    "read_record",
    "validate_repository",
    "write_record",
]
__version__ = "0.1.0.dev0"
