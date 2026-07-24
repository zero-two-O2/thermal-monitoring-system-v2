"""
interfaces.py

ROI subsystem interfaces for the Thermal Monitoring System.

Defines the contracts for the three core ROI subsystem
components:

1. ROIRepository       — Persistence layer (read/write ROI configs).
2. ROIManager          — Lifecycle management of ROI configurations.
3. RuntimeROIManager   — Lifecycle management of runtime ROI caches.

These are pure interface definitions (ABCs).
No implementation, no HALCON, no GUI code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from roi.acquisition_state import AcquisitionState
from roi.configuration import ROIConfiguration
from roi.runtime import RuntimeROI, RuntimeROIState, RuntimeROIStatistics


class ROIRepository(ABC):
    """
    Persistence layer for ROI configurations.

    Responsible for reading and writing ROIConfiguration objects
    to persistent storage (JSON files / database).

    Responsibilities
    ----------------
    - Load all ROIs for a given acquisition state.
    - Save a single ROI configuration.
    - Delete an ROI by ID.
    - Check if an ROI exists.

    Must never:
    - Contain HALCON or GUI code.
    - Manage runtime caches or state.
    - Process images or evaluate alarms.
    - Generate HRegions or Drawing Objects.

    Notes
    -----
    - Implementation will be provided in a later phase.
    - The repository deals only with ROIConfiguration (Layer 1).
    - It does not know about RuntimeROI or HRegions.
    """

    @abstractmethod
    def load_all(
        self,
        acquisition_state: AcquisitionState,
    ) -> list[ROIConfiguration]:
        """
        Load all ROI configurations for a given acquisition state.

        Parameters
        ----------
        acquisition_state : AcquisitionState
            The camera state (camera_id, pan, tilt, zoom, focus)
            for which to load ROIs.

        Returns
        -------
        list[ROIConfiguration]
            All configured ROIs for the given state.
            Empty list if none exist.
        """
        ...

    @abstractmethod
    def save(
        self,
        configuration: ROIConfiguration,
    ) -> None:
        """Save (create or update) one ROI configuration."""
        ...

    @abstractmethod
    def delete(
        self,
        roi_id: str,
    ) -> bool:
        """Delete one ROI configuration by ID."""
        ...

    @abstractmethod
    def exists(
        self,
        roi_id: str,
    ) -> bool:
        """Check whether an ROI configuration exists."""
        ...


class ROIManager(ABC):
    """
    Lifecycle manager for ROI configurations.

    Bridges the ROIRepository (persistence) and the
    RuntimeROIManager (runtime cache).
    """

    @abstractmethod
    def load_state(
        self,
        acquisition_state: AcquisitionState,
    ) -> None:
        """
        Load and activate all ROIs for a given acquisition state.

        Delegates to ROIRepository for loading and to
        RuntimeROIManager for cache creation.
        """
        ...

    @abstractmethod
    def unload_state(
        self,
        acquisition_state: AcquisitionState,
    ) -> None:
        """Deactivate all ROIs for a given acquisition state."""
        ...

    @abstractmethod
    def add_roi(
        self,
        configuration: ROIConfiguration,
    ) -> None:
        """Add a new ROI configuration."""
        ...

    @abstractmethod
    def remove_roi(
        self,
        roi_id: str,
    ) -> None:
        """Remove an ROI configuration."""
        ...

    @abstractmethod
    def update_roi(
        self,
        configuration: ROIConfiguration,
    ) -> None:
        """Update an existing ROI configuration."""
        ...

    @abstractmethod
    def get_active_configurations(
        self,
        acquisition_state: AcquisitionState,
    ) -> list[ROIConfiguration]:
        """Get all active ROI configurations for a given state."""
        ...


class RuntimeROIManager(ABC):
    """
    Manages the runtime ROI cache for one acquisition state.

    Creates RuntimeROI instances from ROIConfiguration objects,
    manages cached HRegions, and provides RuntimeROIs to the
    processing pipeline.

    Responsibilities (Rule 9)
    ------------------------
    - Load configurations into runtime cache.
    - Build and rebuild cached HRegions.
    - Mark regions as dirty when config changes.
    - Unload caches (release HALCON resources).
    - Refresh per-frame statistics from temperature image.
    - Expose active ROIs for the processing pipeline.

    Must never:
    - Acquire images or perform GUI operations.
    - Persist data.
    - Evaluate alarm conditions.
    """

    @abstractmethod
    def load(
        self,
        configurations: list[ROIConfiguration],
    ) -> None:
        """
        Load configurations into the runtime cache (Rule 8).

        Creates one RuntimeROI per configuration.
        HRegions are NOT generated here (lazy via rebuild_dirty_regions).
        """
        ...

    @abstractmethod
    def unload(
        self,
    ) -> None:
        """
        Clear all RuntimeROI instances and release HALCON resources (Rule 10).

        Called when the camera acquisition state changes.
        """
        ...

    @abstractmethod
    def get_all(
        self,
    ) -> list[RuntimeROI]:
        """All cached RuntimeROI instances for the current state."""
        ...

    @abstractmethod
    def get_by_id(
        self,
        roi_id: str,
    ) -> RuntimeROI | None:
        """O(1) lookup by ROI ID (Rule 12)."""
        ...

    @abstractmethod
    def get_active(
        self,
    ) -> list[RuntimeROI]:
        """
        Enabled, non-error RuntimeROI instances ready for processing (Rule 7).
        """
        ...

    @abstractmethod
    def mark_dirty(
        self,
        roi_id: str | None = None,
    ) -> None:
        """
        Mark cached HRegions as dirty (Rule 4).

        If roi_id is provided, mark only that ROI.
        Otherwise, mark all cached regions as dirty.
        """
        ...

    @abstractmethod
    def rebuild_dirty_regions(
        self,
        image_shape: tuple[int, int],
    ) -> None:
        """
        Rebuild all dirty HRegions from geometry (Rule 4).

        Uses geometry_to_hregion() internally.
        Failed conversions set RuntimeROIState.ERROR (Rule 7).
        Successfully built regions become RuntimeROIState.ACTIVE.

        Parameters
        ----------
        image_shape : tuple[int, int]
            (height, width) of the current frame.
            Some region generators need image bounds.
        """
        ...

    @abstractmethod
    def update_state(
        self,
        roi_id: str,
        state: RuntimeROIState,
    ) -> None:
        """Update the runtime state of one ROI."""
        ...

    @abstractmethod
    def refresh_statistics(
        self,
        roi_id: str,
        statistics: RuntimeROIStatistics,
    ) -> None:
        """
        Store computed statistics on a RuntimeROI (Rule 6).

        Called by the processing pipeline after temperature
        statistics have been extracted.

        This method does NOT compute statistics — it only
        stores the result on the RuntimeROI instance.
        """
        ...