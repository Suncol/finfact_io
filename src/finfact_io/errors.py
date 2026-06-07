from __future__ import annotations


class FinfactError(Exception):
    """Base exception for finfact_io."""


class DataRootNotFoundError(FinfactError):
    """Raised when a configured data root does not exist."""


class DataFileNotFoundError(FinfactError):
    """Raised when a required data file is missing."""


class CsvEncodingError(FinfactError):
    """Raised when a CSV cannot be decoded with configured encodings."""


class CsvEncodingWarning(UserWarning):
    """Warns that a non-primary CSV encoding was required."""


class ZipMemberNotFoundError(FinfactError):
    """Raised when a requested zip member is absent."""


class SchemaError(FinfactError):
    """Raised when a data file misses required columns."""


class ArchiveModeError(FinfactError):
    """Raised when archive initialization options are invalid."""
