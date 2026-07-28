"""
acquisition_engine.py

Background acquisition engine.

Responsibilities
----------------
- Run acquisition thread
- Acquire frames from HalconDriver
- Store newest frames in a small queue
- Calculate acquisition statistics
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Optional

import numpy as np

from camera.services.halcon_driver import HalconDriver

from utilities import logger


class AcquisitionEngine:
    """
    Background frame acquisition engine.

    Producer
        HalconDriver

    Consumer
        Processing Pipeline
    """

    DEFAULT_QUEUE_SIZE = 2

    def __init__(
        self,
        driver: HalconDriver,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:

        self._driver = driver

        self._queue: queue.Queue[np.ndarray] = queue.Queue(
            maxsize=queue_size
        )

        self._running = False

        self._thread: Optional[threading.Thread] = None

        #
        # Statistics
        #

        self._frame_count = 0

        self._dropped_frames = 0

        self._fps = 0.0

        self._last_fps_time = time.perf_counter()

        self._fps_counter = 0

        #
        # Synchronization
        #

        self._lock = threading.Lock()

    # ==========================================================
    # Start / Stop
    # ==========================================================

    def start(self) -> None:

        if self._running:
            return

        logger.info(
            "Starting acquisition thread."
        )

        self._running = True

        self._thread = threading.Thread(

            target=self._acquisition_loop,

            daemon=True,

            name="AcquisitionEngine",

        )

        self._thread.start()

    def stop(self) -> None:

        if not self._running:
            return

        logger.info(
            "Stopping acquisition thread."
        )

        self._running = False

        if self._thread is not None:

            self._thread.join(timeout=2.0)

            self._thread = None

        self._clear_queue()

    # ==========================================================
    # Acquisition Loop
    # ==========================================================

    def _acquisition_loop(self) -> None:
        """
        Background acquisition loop.
        """

        logger.info(
            "Acquisition thread started."
        )

        print("[Acquisition] Grab Thread Started")

        while self._running:

            try:

                frame = self._driver.grab_frame()

                if frame is None:
                    continue

                print("[Acquisition] Frame Grabbed")

                self._push_frame(frame)

                print("[Acquisition] Frame Emitted")

                self._update_statistics()

            except Exception:

                logger.exception(
                    "Frame acquisition failed."
                )

                time.sleep(0.1)

        logger.info(
            "Acquisition thread stopped."
        )

    # ==========================================================
    # Queue
    # ==========================================================

    def _push_frame(
        self,
        frame: np.ndarray,
    ) -> None:
        """
        Push newest frame into queue.

        If queue is full,
        discard oldest frame.
        """

        try:

            self._queue.put_nowait(
                frame
            )

        except queue.Full:

            try:

                self._queue.get_nowait()

            except queue.Empty:

                pass

            self._queue.put_nowait(
                frame
            )

            self._dropped_frames += 1

    def get_frame(
        self,
        timeout: float | None = None,
    ) -> np.ndarray | None:
        """
        Return newest available frame.
        """

        try:

            return self._queue.get(
                timeout=timeout
            )

        except queue.Empty:

            return None
        
        # ==========================================================
    # Queue Utilities
    # ==========================================================

    def _clear_queue(self) -> None:
        """
        Remove every frame from the queue.
        """

        while True:

            try:

                self._queue.get_nowait()

            except queue.Empty:

                break

    def get_latest_frame(
        self,
    ) -> np.ndarray | None:
        """
        Return the newest available frame.

        Older queued frames are discarded.
        """

        latest = None

        while True:

            try:

                latest = self._queue.get_nowait()

            except queue.Empty:

                break

        return latest

    # ==========================================================
    # Statistics
    # ==========================================================

    def _update_statistics(self) -> None:

        self._frame_count += 1

        self._fps_counter += 1

        now = time.perf_counter()

        elapsed = now - self._last_fps_time

        if elapsed >= 1.0:

            with self._lock:

                self._fps = self._fps_counter / elapsed

                self._fps_counter = 0

                self._last_fps_time = now

    def get_statistics(
        self,
    ) -> dict:
        """
        Return acquisition statistics.
        """

        with self._lock:

            return {

                "running": self._running,

                "fps": round(self._fps, 2),

                "frame_count": self._frame_count,

                "dropped_frames": self._dropped_frames,

                "queue_size": self._queue.qsize(),

                "queue_capacity": self._queue.maxsize,

            }

    def reset_statistics(
        self,
    ) -> None:

        with self._lock:

            self._frame_count = 0

            self._fps_counter = 0

            self._fps = 0.0

            self._dropped_frames = 0

            self._last_fps_time = time.perf_counter()

    # ==========================================================
    # Status
    # ==========================================================

    def is_running(
        self,
    ) -> bool:

        return self._running

    @property
    def frame_count(
        self,
    ) -> int:

        return self._frame_count

    @property
    def fps(
        self,
    ) -> float:

        return self._fps

    @property
    def dropped_frames(
        self,
    ) -> int:

        return self._dropped_frames

    @property
    def queue_size(
        self,
    ) -> int:

        return self._queue.qsize()