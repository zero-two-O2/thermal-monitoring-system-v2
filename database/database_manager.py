"""
database_manager.py

SQLite persistence layer for configuration, cameras, alarm settings and ROIs.

Responsibilities
----------------
- database creation / schema creation
- configuration reads and writes
- alarm settings reads and writes
- camera metadata reads and writes
- ROI reads and writes
- one-time JSON -> SQLite migration (config.json / rois.json)

The database is used only at startup, on configuration changes and on ROI
reload. It must NEVER be part of the per-frame processing path; the frame
loop reads configuration and ROIs from memory only.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thermal_monitor.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_number INTEGER UNIQUE,
    serial TEXT,
    ip TEXT,
    model TEXT,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS application_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS alarm_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    temperature_limit REAL,
    enabled INTEGER,
    use_max_temperature INTEGER
);

CREATE TABLE IF NOT EXISTS rois (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER,
    roi_name TEXT,
    y1 INTEGER,
    x1 INTEGER,
    y2 INTEGER,
    x2 INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1
);
"""


class DatabaseManager:
    """Owns the SQLite connection and all persistence operations.

    A fresh connection is opened per operation so the manager is safe to
    use from the GUI thread and from camera worker threads without shared
    connection state. All operations are only invoked off the frame path.
    """

    def __init__(self, db_path: str = DATABASE_PATH) -> None:
        self._db_path = db_path
        self.initialize()

    @property
    def db_path(self) -> str:
        return self._db_path

    # ==========================================================
    # Low-level helpers
    # ==========================================================

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        """Create the database file and schema if they do not exist."""
        try:
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
                conn.commit()
        except Exception:
            logger.exception("Failed to create database schema at %s", self._db_path)
            raise

    @staticmethod
    def _row_count(conn: sqlite3.Connection, table: str) -> int:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row is not None else 0

    @staticmethod
    def _flatten(section: dict, prefix: str = "") -> Dict[str, object]:
        """Flatten a nested config dict into dot-notation keys."""
        result: Dict[str, object] = {}
        for key, value in section.items():
            dot_key = f"{prefix}{key}"
            if isinstance(value, dict):
                result.update(DatabaseManager._flatten(value, f"{dot_key}."))
            else:
                result[dot_key] = value
        return result

    @staticmethod
    def _encode(value: object) -> str:
        """Serialise a config value for storage (JSON round-trips types)."""
        return json.dumps(value)

    @staticmethod
    def _decode(raw: str) -> object:
        try:
            return json.loads(raw)
        except Exception:
            return raw

    # ==========================================================
    # Configuration
    # ==========================================================

    def get_all_settings(self) -> Dict[str, object]:
        """Return all application settings as dot-notation key -> value."""
        settings: Dict[str, object] = {}
        try:
            with self._connect() as conn:
                for row in conn.execute("SELECT key, value FROM application_settings"):
                    settings[row["key"]] = self._decode(row["value"])
        except Exception:
            logger.exception("Failed to read application settings")
        return settings

    def save_all_settings(self, settings: Dict[str, object]) -> None:
        """Persist a full settings dict (dot-notation keys)."""
        try:
            with self._connect() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO application_settings (key, value) VALUES (?, ?)",
                    [(key, self._encode(value)) for key, value in settings.items()],
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to write application settings")

    def save_setting(self, key: str, value: object) -> None:
        """Persist a single application setting."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO application_settings (key, value) VALUES (?, ?)",
                    (key, self._encode(value)),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to write application setting %s", key)

    def has_settings(self) -> bool:
        try:
            with self._connect() as conn:
                return self._row_count(conn, "application_settings") > 0
        except Exception:
            return False

    # ==========================================================
    # Alarm settings
    # ==========================================================

    def get_alarm_settings(self) -> Optional[Dict[str, object]]:
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM alarm_settings WHERE id = 1").fetchone()
            if row is None:
                return None
            return {
                "temperature_limit": row["temperature_limit"],
                "enabled": bool(row["enabled"]),
                "use_max_temperature": bool(row["use_max_temperature"]),
            }
        except Exception:
            logger.exception("Failed to read alarm settings")
            return None

    def save_alarm_settings(self, limit: float, enabled: bool, use_max_temperature: bool) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO alarm_settings "
                    "(id, temperature_limit, enabled, use_max_temperature) VALUES (1, ?, ?, ?)",
                    (float(limit), int(bool(enabled)), int(bool(use_max_temperature))),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to write alarm settings")

    # ==========================================================
    # Cameras
    # ==========================================================

    def upsert_camera(
        self,
        camera_number: int,
        serial: str,
        ip: str,
        model: str,
        enabled: bool = True,
    ) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO cameras (camera_number, serial, ip, model, enabled) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(camera_number) DO UPDATE SET "
                    "serial = excluded.serial, ip = excluded.ip, "
                    "model = excluded.model, enabled = excluded.enabled",
                    (int(camera_number), serial, ip, model, int(bool(enabled))),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to save camera metadata for camera %s", camera_number)

    def get_cameras(self) -> List[Dict[str, object]]:
        cameras: List[Dict[str, object]] = []
        try:
            with self._connect() as conn:
                for row in conn.execute(
                    "SELECT id, camera_number, serial, ip, model, enabled FROM cameras "
                    "ORDER BY camera_number"
                ):
                    cameras.append(
                        {
                            "id": row["id"],
                            "camera_number": row["camera_number"],
                            "serial": row["serial"],
                            "ip": row["ip"],
                            "model": row["model"],
                            "enabled": bool(row["enabled"]),
                        }
                    )
        except Exception:
            logger.exception("Failed to read cameras")
        return cameras

    # ==========================================================
    # ROIs
    # ==========================================================

    def save_rois(self, rois: List[Dict[str, object]], camera_id: Optional[int] = None) -> None:
        """Replace all ROI rows for a camera (or the shared set when camera_id is None)."""
        try:
            with self._connect() as conn:
                if camera_id is None:
                    conn.execute("DELETE FROM rois")
                else:
                    conn.execute("DELETE FROM rois WHERE camera_id = ?", (camera_id,))
                conn.executemany(
                    "INSERT INTO rois (camera_id, roi_name, y1, x1, y2, x2, enabled) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            camera_id,
                            roi["name"],
                            int(roi["y1"]),
                            int(roi["x1"]),
                            int(roi["y2"]),
                            int(roi["x2"]),
                            int(bool(roi.get("enabled", True))),
                        )
                        for roi in rois
                    ],
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to write ROIs to database")

    def get_rois(self, camera_id: Optional[int] = None) -> List[Dict[str, object]]:
        """Return ROI definitions; rows carry name/y1/x1/y2/x2."""
        rois: List[Dict[str, object]] = []
        try:
            with self._connect() as conn:
                if camera_id is None:
                    rows = conn.execute(
                        "SELECT roi_name, y1, x1, y2, x2, enabled FROM rois "
                        "ORDER BY id"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT roi_name, y1, x1, y2, x2, enabled FROM rois "
                        "WHERE camera_id = ? ORDER BY id",
                        (camera_id,),
                    ).fetchall()
                for row in rows:
                    if not row["enabled"]:
                        continue
                    rois.append(
                        {
                            "name": row["roi_name"],
                            "y1": row["y1"],
                            "x1": row["x1"],
                            "y2": row["y2"],
                            "x2": row["x2"],
                        }
                    )
        except Exception:
            logger.exception("Failed to read ROIs from database")
        return rois

    def has_rois(self) -> bool:
        try:
            with self._connect() as conn:
                return self._row_count(conn, "rois") > 0
        except Exception:
            return False

    # ==========================================================
    # JSON -> SQLite migration
    # ==========================================================

    def migrate_from_json(self, config_path: str, rois_path: str) -> None:
        """One-time import of config.json / rois.json into SQLite.

        Import runs only for tables that are currently empty, so a
        populated database is never overwritten and ROIs are never
        duplicated on every startup. The JSON files are kept as backup
        and are never deleted.
        """
        try:
            with self._connect() as conn:
                if self._row_count(conn, "application_settings") == 0:
                    raw = self._read_json(config_path)
                    if isinstance(raw, dict):
                        settings = self._flatten(raw)
                        conn.executemany(
                            "INSERT OR REPLACE INTO application_settings (key, value) VALUES (?, ?)",
                            [(key, self._encode(value)) for key, value in settings.items()],
                        )
                        conn.commit()
                        logger.info("Migrated configuration from %s into SQLite", config_path)

                if self._row_count(conn, "alarm_settings") == 0:
                    raw = self._read_json(config_path)
                    if isinstance(raw, dict):
                        alarm = raw.get("alarm") if isinstance(raw.get("alarm"), dict) else {}
                        conn.execute(
                            "INSERT OR REPLACE INTO alarm_settings "
                            "(id, temperature_limit, enabled, use_max_temperature) "
                            "VALUES (1, ?, ?, ?)",
                            (
                                float(alarm.get("temperature_limit", 80.0)),
                                int(bool(alarm.get("enabled", True))),
                                int(bool(alarm.get("use_max_temperature", True))),
                            ),
                        )
                        conn.commit()

                if self._row_count(conn, "rois") == 0:
                    roi_list = self._read_json(rois_path)
                    if isinstance(roi_list, list) and roi_list:
                        conn.executemany(
                            "INSERT INTO rois (camera_id, roi_name, y1, x1, y2, x2, enabled) "
                            "VALUES (NULL, ?, ?, ?, ?, ?, 1)",
                            [
                                (
                                    roi.get("name", f"ROI {i + 1}"),
                                    int(roi["y1"]),
                                    int(roi["x1"]),
                                    int(roi["y2"]),
                                    int(roi["x2"]),
                                )
                                for i, roi in enumerate(roi_list)
                            ],
                        )
                        conn.commit()
                        logger.info("Migrated ROIs from %s into SQLite", rois_path)
        except Exception:
            logger.exception("JSON -> SQLite migration failed")

    @staticmethod
    def _read_json(path: str):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            logger.warning("Unable to read JSON file for migration: %s", path)
            return None
