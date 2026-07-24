from collections.abc import Callable

from roi.persistence.exceptions import SchemaVersionError
from roi.persistence.migration.v1 import migrate_v1
from roi.persistence.schema import CURRENT_SCHEMA_VERSION

_MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    1: migrate_v1,
}


def migrate(data: dict) -> dict:
    version = data.get("schema_version", 0)
    if not isinstance(version, int) or version < 0:
        raise SchemaVersionError(f"Invalid schema_version: {version}")

    while version < CURRENT_SCHEMA_VERSION:
        next_ver = version + 1
        migrator = _MIGRATIONS.get(next_ver)
        if migrator is None:
            raise SchemaVersionError(
                f"No migration path from version {version} to {next_ver}"
            )
        data = migrator(data)
        data["schema_version"] = next_ver
        version = next_ver

    return data
