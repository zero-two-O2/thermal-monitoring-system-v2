"""
position_manager.py

Manages all monitoring positions for a camera.
"""

from __future__ import annotations

from typing import Dict

from camera.models.position_model import PositionModel

from utilities import logger


class PositionManager:
    """
    Manages all positions belonging to one camera.
    """

    def __init__(self) -> None:

        self._positions: Dict[str, PositionModel] = {}

        self._current_position_id: str | None = None

    # ==========================================================
    # CRUD
    # ==========================================================

    def add_position(
        self,
        position: PositionModel,
    ) -> None:

        if position.position_id in self._positions:

            raise ValueError(
                f"Position '{position.position_id}' already exists."
            )

        self._positions[position.position_id] = position

        logger.info(
            f"Added position '{position.position_id}'."
        )

        if self._current_position_id is None:

            self._current_position_id = position.position_id

    def remove_position(
        self,
        position_id: str,
    ) -> None:

        if position_id not in self._positions:

            return

        del self._positions[position_id]

        logger.info(
            f"Removed position '{position_id}'."
        )

        if self._current_position_id == position_id:

            self._current_position_id = None

            if self._positions:

                self._current_position_id = next(
                    iter(self._positions)
                )

    def update_position(
        self,
        position: PositionModel,
    ) -> None:

        if position.position_id not in self._positions:

            raise KeyError(
                position.position_id
            )

        self._positions[position.position_id] = position

    def clear(
        self,
    ) -> None:

        self._positions.clear()

        self._current_position_id = None

    # ==========================================================
    # Queries
    # ==========================================================

    def get_position(
        self,
        position_id: str,
    ) -> PositionModel | None:

        return self._positions.get(
            position_id
        )

    def get_current_position(
        self,
    ) -> PositionModel | None:

        if self._current_position_id is None:

            return None

        return self._positions.get(
            self._current_position_id
        )

    def get_all_positions(
        self,
    ) -> list[PositionModel]:

        return sorted(

            self._positions.values(),

            key=lambda p: p.sequence,

        )

    @property
    def position_count(
        self,
    ) -> int:

        return len(
            self._positions
        )
    
        # ==========================================================
    # Current Position
    # ==========================================================

    def set_current_position(
        self,
        position_id: str,
    ) -> None:
        """
        Select the active position.
        """

        if position_id not in self._positions:

            raise KeyError(position_id)

        self._current_position_id = position_id

    # ==========================================================
    # Navigation
    # ==========================================================

    def first_position(
        self,
    ) -> PositionModel | None:

        positions = self.get_all_positions()

        if not positions:

            return None

        self._current_position_id = positions[0].position_id

        return positions[0]

    def last_position(
        self,
    ) -> PositionModel | None:

        positions = self.get_all_positions()

        if not positions:

            return None

        self._current_position_id = positions[-1].position_id

        return positions[-1]

    def next_position(
        self,
    ) -> PositionModel | None:

        positions = self.get_all_positions()

        if not positions:

            return None

        if self._current_position_id is None:

            return self.first_position()

        current_index = next(

            (
                index

                for index, position in enumerate(positions)

                if position.position_id
                == self._current_position_id
            ),

            None,

        )

        if current_index is None:

            return self.first_position()

        current_index += 1

        if current_index >= len(positions):

            current_index = 0

        position = positions[current_index]

        self._current_position_id = position.position_id

        return position

    def previous_position(
        self,
    ) -> PositionModel | None:

        positions = self.get_all_positions()

        if not positions:

            return None

        if self._current_position_id is None:

            return self.last_position()

        current_index = next(

            (
                index

                for index, position in enumerate(positions)

                if position.position_id
                == self._current_position_id
            ),

            None,

        )

        if current_index is None:

            return self.last_position()

        current_index -= 1

        if current_index < 0:

            current_index = len(positions) - 1

        position = positions[current_index]

        self._current_position_id = position.position_id

        return position

    # ==========================================================
    # Enable / Disable
    # ==========================================================

    def enable_position(
        self,
        position_id: str,
    ) -> None:

        position = self.get_position(
            position_id
        )

        if position is not None:

            position.enabled = True

    def disable_position(
        self,
        position_id: str,
    ) -> None:

        position = self.get_position(
            position_id
        )

        if position is not None:

            position.enabled = False

    # ==========================================================
    # Sequence
    # ==========================================================

    def move_position(
        self,
        position_id: str,
        new_sequence: int,
    ) -> None:
        """
        Change execution order.
        """

        position = self.get_position(
            position_id
        )

        if position is None:

            raise KeyError(position_id)

        position.sequence = new_sequence

    # ==========================================================
    # Utilities
    # ==========================================================

    def has_positions(
        self,
    ) -> bool:

        return bool(self._positions)

    def current_position_id(
        self,
    ) -> str | None:

        return self._current_position_id
    