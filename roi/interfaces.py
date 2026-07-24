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
from roi.runtime import RuntimeROI, RuntimeROIState


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
        """
        Save (create or update) one ROI configuration.

        Parameters
        ----------
        configuration : ROIConfiguration
            The ROI configuration to persist.
        """
        ...

    @abstractmethod
    def delete(
        self,
        roi_id: str,
    ) -> bool:
        """
        Delete one ROI configuration by ID.

        Parameters
        ----------
        roi_id : str
            Identifier of the ROI to delete.

        Returns
        -------
        bool
            True if the ROI was deleted, False if not found.
        """
        ...

    @abstractmethod
    def exists(
        self,
        roi_id: str,
    ) -> bool:
        """
        Check whether an ROI configuration exists.

        Parameters
        ----------
        roi_id : str
            Identifier of the ROI to check.

        Returns
        -------
        bool
            True if the ROI exists in persistent storage.
        """
        ...


class ROIManager(ABC):
    """
    Lifecycle manager for ROI configurations.

    Bridges the ROIRepository (persistence) and the
    RuntimeROIManager (runtime cache).

    Responsibilities
    ----------------
    - Load ROI configurations from the repository.
    - Activate ROIs for a given acquisition state.
    - Deactivate ROIs when the state changes.
    - Forward configuration changes to RuntimeROIManager.
    - Coordinate creation, deletion, and updates.

    Must never:
    - Contain HALCON or GUI code.
    - Process images or evaluate alarms.
    - Generate HRegions or Drawing Objects directly.
    - Persist data (delegates to ROIRepository).

    Notes
    -----
    - One ROIManager instance serves the entire application.
    - It manages the relationship between persistent
      configurations and runtime caches.
    """

    @abstractmethod
    def load_state(
        self,
        acquisition_state: AcquisitionState,
    ) -> None:
        """
        Load and activate all ROIs for a given acquisition state.

        Called when a camera changes position (or zoom, focus, etc.).
        Delegates to ROIRepository for loading and to
        RuntimeROIManager for cache creation.

        Parameters
        ----------
        acquisition_state : AcquisitionState
            The camera state to load ROIs for.
        """
        ...

    @abstractmethod
    def unload_state(
        self,
        acquisition_state: AcquisitionState,
    ) -> None:
        """
        Deactivate all ROIs for a given acquisition state.

        Called when a camera leaves the given state.
        Delegates to RuntimeROIManager to clear caches.

        Parameters
        ----------
        acquisition_state : AcquisitionState
            The camera state to unload ROIs for.
        """
        ...

    @abstractmethod
    def add_roi(
        self,
        configuration: ROIConfiguration,
    ) -> None:
        """
        Add a new ROI configuration.

        Persists via ROIRepository and updates runtime
        cache via RuntimeROIManager.

        Parameters
        ----------
        configuration : ROIConfiguration
            The ROI configuration to add.
        """
        ...

    @abstractmethod
    def remove_roi(
        self,
        roi_id: str,
    ) -> None:
        """
        Remove an ROI configuration.

        Deletes from ROIRepository and removes from
        RuntimeROIManager cache.

        Parameters
        ----------
        roi_id : str
            Identifier of the ROI to remove.
        """
        ...

    @abstractmethod
    def update_roi(
        self,
        configuration: ROIConfiguration,
    ) -> None:
        """
        Update an existing ROI configuration.

        Persists changes and marks the runtime cache as dirty.
        The cached HRegion will be regenerated on the
        next processing cycle.

        Parameters
        ----------
        configuration : ROIConfiguration
            The updated ROI configuration.
        """
        ...

    @abstractmethod
    def get_active_configurations(
        self,
        acquisition_state: AcquisitionState,
    ) -> list[ROIConfiguration]:
        """
        Get all active ROI configurations for a given state.

        Parameters
        ----------
        acquisition_state : AcquisitionState
            The camera state to query.

        Returns
        -------
        list[ROIConfiguration]
            Currently active ROI configurations.
        """
        ...


class RuntimeROIManager(ABC):
    """
    Manages the runtime ROI cache for one acquisition state.

    Creates RuntimeROI instances from ROIConfiguration objects,
    manages cached HRegions, and provides RuntimeROIs to the
    processing pipeline.

    Responsibilities
    ----------------
    - Create RuntimeROI instances from ROIConfiguration.
    - Generate and cache HALCON HRegions from geometry.
    - Mark regions as dirty when configuration changes.
    - Rebuild dirty regions before processing.
    - Provide RuntimeROIs to the ROI Processor.
    - Track runtime state and statistics for each ROI.

    Must never:
    - Persist data.
    - Process images or calculate temperature statistics.
    - Evaluate alarm conditions.
    - Contain GUI or Drawing Object code.

    Notes
    -----
    - One RuntimeROIManager exists per active acquisition state.
    - Created by ROIManager.load_state().
    - Destroyed by ROIManager.unload_state().
    """

    @abstractmethod
    def load(
        self,
        configurations: list[ROIConfiguration],
    ) -> None:
        """
        Load ROI configurations into the runtime cache.

        Creates RuntimeROI instances for each configuration.
        HRegions are NOT generated here; they are generated
        lazily when image dimensions are first known.

        Parameters
        ----------
        configurations : list[ROIConfiguration]
            The configurations to load.
        """
        ...

    @abstractmethod
    def unload(
        self,
    ) -> None:
        """
        Clear all RuntimeROI instances and cached regions.

        Called when the camera acquisition state changes.
        """
        ...

    @abstractmethod
    def get_all(
        self,
    ) -> list[RuntimeROI]:
        """
        Get all cached RuntimeROI instances for the current state.

        Returns
        -------
        list[RuntimeROI]
            All currently cached ROIs.
        """
        ...

    @abstractmethod
    def get_by_id(
        self,
        roi_id: str,
    ) -> RuntimeROI | None:
        """
        Get one RuntimeROI by its ID.

        Parameters
        ----------
        roi_id : str
            ROI identifier.

        Returns
        -------
        RuntimeROI | None
            The RuntimeROI if found, None otherwise.
        """
        ...

    @abstractmethod
    def get_active(
        self,
    ) -> list[RuntimeROI]:
        """
        Get only enabled, non-error RuntimeROI instances.

        Filters out disabled ROIs and ROIs in ERROR state.
        This is the primary method used by the processing pipeline.

        Returns
        -------
        list[RuntimeROI]
            Active and valid ROIs ready for processing.
        """
        ...

    @abstractmethod
    def mark_dirty(
        self,
        roi_id: str | None = None,
    ) -> None:
        """
        Mark cached HRegions as dirty (needs rebuild).

        If roi_id is provided, mark only that ROI.
        Otherwise, mark all cached regions as dirty.

        Parameters
        ----------
        roi_id : str | None
            Optional specific ROI to mark dirty.
        """
        ...

    @abstractmethod
    def rebuild_dirty_regions(
        self,
        image_shape: tuple[int, int],
    ) -> None:
        """
        Rebuild all dirty HRegions from geometry.

        Called before processing to ensure all cached regions
        are up-to-date. Uses geometry_to_hregion() internally.

        Parameters
        ----------
        image_shape : tuple[int, int]
            (height, width) of the current frame.
            Required because HRegion generation may depend on
            image dimensions for bounds checking.
        """
        ...

    @abstractmethod
    def update_state(
        self,
        roi_id: str,
        state: RuntimeROIState,
    ) -> None:
        """
        Update the runtime state of one ROI.

        Parameters
        ----------
        roi_id : str
            ROI identifier.
        state : RuntimeROIState
            New runtime state.
        """
        ...

    @abstractmethod
    def refresh_statistics(
        self,
        roi_id: str,
    ) -> None:
        """
        Refresh cached statistics for one ROI.

        Called after processing to update the statistics
        stored on the RuntimeROI. This does NOT recalculate
        statistics — it refreshes them from the processor.

        Parameters
        ----------
        roi_id : str
            ROI identifier whose statistics to refresh.
        """
        ...
