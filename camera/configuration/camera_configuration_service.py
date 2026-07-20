"""
camera_configuration_service.py

Provides access to camera configuration records.

This class is responsible for reading and writing logical camera
configuration from the application's database.

It never communicates with HALCON or camera hardware.
"""

from __future__ import annotations

from typing import Dict

from camera.configuration.camera_configuration import CameraConfiguration
from utilities.logger import logger


class CameraConfigurationService:
    """
    Loads and stores camera configuration.
    """

    def __init__(self, database) -> None:
        """
        Parameters
        ----------
        database
            Database manager instance.
        """

        self._database = database

        self._cache: Dict[str, CameraConfiguration] = {}

    # ==========================================================
    # Public
    # ==========================================================

    def load_all(self) -> None:
        """
        Load every camera configuration from the database.
        """

        self._cache.clear()

        rows = self._database.fetch_all(
            """
            SELECT

                camera_id,
                serial_number,
                gui_tile,
                friendly_name,
                location,
                expected_ip,
                enabled,
                description

            FROM camera_configuration

            ORDER BY gui_tile
            """
        )

        for row in rows:

            config = CameraConfiguration(
                camera_id=row["camera_id"],
                serial_number=row["serial_number"],
                gui_tile=row["gui_tile"],
                friendly_name=row["friendly_name"],
                location=row["location"],
                expected_ip=row["expected_ip"],
                enabled=bool(row["enabled"]),
                description=row["description"],
            )
            self._cache[
                config.serial_number
            ] = config
        logger.info(
            f"Loaded {len(self._cache)} camera configuration(s)."
        )

    # ----------------------------------------------------------

    def get_by_serial(
        self,
        serial_number: str,
    ) -> CameraConfiguration | None:
        return self._cache.get(serial_number)

    # ----------------------------------------------------------

    def get_all(self) -> list[CameraConfiguration]:
        return list(self._cache.values())

    # ----------------------------------------------------------

    def exists(
        self,
        serial_number: str,
    ) -> bool:
        return serial_number in self._cache

    # ----------------------------------------------------------

    def add(
        self,
        configuration: CameraConfiguration,
    ) -> None:
        """
        Add a new camera configuration.
        """
        self._database.execute(
            """
            INSERT INTO camera_configuration
            (
                camera_id,
                serial_number,
                gui_tile,
                friendly_name,
                location,
                expected_ip,
                enabled,
                description
            )
            VALUES
            (
                ?,?,?,?,?,?,?,?
            )
            """,
            (
                configuration.camera_id,
                configuration.serial_number,
                configuration.gui_tile,
                configuration.friendly_name,
                configuration.location,
                configuration.expected_ip,
                configuration.enabled,
                configuration.description,
            ),
        )
        self._cache[
            configuration.serial_number
        ] = configuration

    # ----------------------------------------------------------

    def update(
        self,
        configuration: CameraConfiguration,
    ) -> None:
        """
        Update an existing configuration.
        """
        self._database.execute(
            """
            UPDATE camera_configuration
            SET
                gui_tile=?,
                friendly_name=?,
                location=?,
                expected_ip=?,
                enabled=?,
                description=?
            WHERE serial_number=?
            """,
            (
                configuration.gui_tile,
                configuration.friendly_name,
                configuration.location,
                configuration.expected_ip,
                configuration.enabled,
                configuration.description,
                configuration.serial_number,
            ),
        )
        self._cache[
            configuration.serial_number
        ] = configuration

    # ----------------------------------------------------------

    def delete(
        self,
        serial_number: str,
    ) -> None:
        """
        Remove a camera configuration.
        """
        self._database.execute(
            """
            DELETE FROM camera_configuration
            WHERE serial_number=?
            """,
            (
                serial_number,
            ),
        )
        self._cache.pop(
            serial_number,
            None,
        )

    # ----------------------------------------------------------

    def reload(self) -> None:
        """
        Reload all configuration from the database.
        """
        self.load_all()