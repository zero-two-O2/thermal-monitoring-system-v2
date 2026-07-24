class PersistenceError(Exception):
    """Base exception for all persistence layer errors."""


class SchemaVersionError(PersistenceError):
    """Raised when the schema version is unknown or unsupported."""


class ValidationError(PersistenceError):
    """Raised when a file fails validation."""


class FileNotFoundError(PersistenceError):
    """Raised when a required ROI file does not exist."""


class CorruptedFileError(PersistenceError):
    """Raised when a file cannot be parsed or contains invalid data."""


class DuplicateROIError(ValidationError):
    """Raised when duplicate ROI IDs are found in the same file."""


class MissingFieldError(ValidationError):
    """Raised when a required field is missing from a file."""
