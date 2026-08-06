"""
halcon_mvtec_prototype.py

MVTec HALCON Architecture Prototype

Validates the exact MVTec batched workflow before integration.

Architecture (4 stages, no extra layers):
1. Initialization: open camera, load calibration, load ROI coordinates, create HALCON regions (once)
2. Frame acquisition: acquire image, convert to temperature, display image (per frame)
3. ROI statistics: intensity/min_max_gray directly on cached region tuples (per type, no loops)
4. Display: Image, ROI Regions, Text, Performance Text (in that order)

No worker threads, label caches, OpenCV compositors, or FPS optimization code.

All region generation happens in initialization (ROI create/move/delete/load).
The frame loop only reads cached region tuples, never recreates them.
"""

from __future__ import annotations
import csv
import sys
import time
from typing import Callable

import halcon as ha
import numpy as np
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, 
                             QMainWindow, QVBoxLayout, QWidget)

from calibration.calibration_manager import CalibrationManager
from configuration.settings import Settings

# Constants for the MVTec architecture
FEED_W = 640
FEED_H = 480

# HALCON parameter values (from Halcon_Parameters.md)
# TV46LCamera camera parameters
CAMERA_PARAMS = {
    "device_identifier": "HB25100002",  # Device identifier from discovery
    "bits_per_channel": 16,
    "stream_data_source": "IR_Data",
    "frame_rate": 9,
    "pixel_size": (5.6, 5.6),
}

# Configuration
RUN_BENCHMARK = True
BENCHMARK_COUNTS = (50, 100, 250, 500, 1000, 2000)
BENCHMARK_FRAMES = 15
BENCHMARK_WARMUP = 5

# ROI storage - parallel arrays exactly as MVTec spec
class GroupedROIStorage:
    """ROI storage with parallel arrays, one per shape type."""
    
    def __init__(self):
        # Rectangle1 ROIs
        self.rect1_rows = np.array([], dtype=np.float32)
        self.rect1_cols = np.array([], dtype=np.float32)
        self.rect1_rows2 = np.array([], dtype=np.float32)
        self.rect1_cols2 = np.array([], dtype=np.float32)
        self.rect1_names = np.array([], dtype=str)
        self.rect1_enabled = np.array([], dtype=bool)
        
        # Circle ROIs
        self.circle_rows = np.array([], dtype=np.float32)
        self.circle_cols = np.array([], dtype=np.float32)
        self.circle_radii = np.array([], dtype=np.float32)
        self.circle_names = np.array([], dtype=str)
        self.circle_enabled = np.array([], dtype=bool)
        
        # Ellipse ROIs
        self.ellipse_rows = np.array([], dtype=np.float32)
        self.ellipse_cols = np.array([], dtype=np.float32)
        self.ellipse_phis = np.array([], dtype=np.float32)
        self.ellipse_radii1 = np.array([], dtype=np.float32)
        self.ellipse_radii2 = np.array([], dtype=np.float32)
        self.ellipse_names = np.array([], dtype=str)
        self.ellipse_enabled = np.array([], dtype=bool)
        
        # Polygon ROIs (stored as parallel row/col arrays)
        self.polygon_rows = np.array([], dtype=np.float32)
        self.polygon_cols = np.array([], dtype=np.float32)
        self.polygon_names = np.array([], dtype=str)
        self.polygon_enabled = np.array([], dtype=bool)

# RegionCache - holds generated HALCON region objects (one per type, never recreated)
class RegionCache:
    """Caches HALCON region objects, regenerated only when ROI geometry changes."""
    
    def __init__(self):
        self.rect1_region = ha.gen_empty_region()
        self.circle_region = ha.gen_empty_region()
        self.ellipse_region = ha.gen_empty_region()
        self.polygon_region = ha.gen_empty_region()
        self.dirty = True

# HALCON-based display
class ThermalView(QFrame):
    """Minimal PyQt wrapper for HALCON window with basic display only."""
    
    def __init__(self, parent=None, log_fn: Callable[[str], None] | None = None):
        super().__init__(parent)
        self._log_fn = log_fn
        self._halcon_window = None
        self._temperature_image = None
        self._display_image = None
        self.setMinimumSize(FEED_W, FEED_H)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
    
    def create_halcon_window(self):
        """Create HALCON window for display."""
        try:
            if self._halcon_window is None:
                self._halcon_window = ha.open_window(
                    0, 0, self.width(), self.height(), 0, "visible", ""
                )
            return True
        except Exception as exc:
            if self._log_fn:
                self._log_fn(f"Failed to create HALCON window: {exc}")
            return False
    
    def display_frame(self, temperature_image: np.ndarray):
        """Display a single frame using HALCON native operators only."""
        if self._halcon_window is None:
            if not self.create_halcon_window():
                return 0.0
        
        t0 = time.perf_counter()
        
        try:
            # Convert temperature image to display (8-bit grayscale)
            temp_min = float(np.nanmin(temperature_image))
            temp_max = float(np.nanmax(temperature_image))
            if temp_max <= temp_min:
                temp_max = temp_min + 1.0
            
            normalized = np.clip((temperature_image - temp_min) / (temp_max - temp_min), 0, 1)
            display = (normalized * 255).astype(np.uint8)
            self._display_image = display
            
            # Create HALCON image from numpy array
            halcon_image = ha.himage_from_numpy_array(display)
            
            # Clear and display image
            ha.clear_window(self._halcon_window)
            ha.disp_obj(halcon_image, self._halcon_window)
            
            # Display performance text (HALCON native)
            ha.disp_text(self._halcon_window, 
                        f"FPS: {1000/(time.perf_counter() - t0):.1f}",
                        "window", 10, 20, "white", ["size", "box"], [12, "false"])
            
            ha.flush_buffer(self._halcon_window)
            
            return (time.perf_counter() - t0) * 1000.0
            
        except Exception as exc:
            if self._log_fn:
                self._log_fn(f"Display error: {exc}")
            return 0.0
    
    def show(self):
        super().show()
        if self._halcon_window is None:
            self.create_halcon_window()

# Main prototype class
class MVTecPrototype:
    """MVTec HALCON architecture prototype."""
    
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.window = QMainWindow()
        self.window.setWindowTitle("MVTec HALCON Prototype")
        
        # Create main widget with minimal GUI
        self.main_widget = QWidget()
        self.main_layout = QHBoxLayout(self.main_widget)
        
        # Camera display area (HALCON window)
        self.thermal_view = ThermalView()
        self.main_layout.addWidget(self.thermal_view)
        
        # ROI statistics panel
        self.stats_panel = self._create_stats_panel()
        self.main_layout.addWidget(self.stats_panel)
        
        self.window.setCentralWidget(self.main_widget)
        self.window.resize(FEED_W + 300, FEED_H)
        
        # MVTec architecture components
        self.roi_storage = GroupedROIStorage()
        self.region_cache = RegionCache()
        self.calibration = CalibrationManager()
        self.camera_info = []
        
        # Performance tracking
        self.frame_times = []
        self.current_frame = 0
        
    def _create_stats_panel(self):
        """Create simple statistics panel."""
        panel = QFrame()
        panel.setFrameStyle(QFrame.StyledPanel)
        panel.setMinimumWidth(250)
        layout = QVBoxLayout(panel)
        
        title = QLabel("Statistics")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        
        self.stats_label = QLabel("No frame processed")
        layout.addWidget(self.stats_label)
        
        self.fps_label = QLabel("FPS: 0.0")
        layout.addWidget(self.fps_label)
        
        self.roi_count_label = QLabel("ROIs: 0")
        layout.addWidget(self.roi_count_label)
        
        layout.addStretch()
        return panel
    
    def initialize(self):
        """Stage 1: Initialization - open camera, load calibration, create ROIs."""
        print("=" * 60)
        print("Stage 1: Initialization")
        print("=" * 60)
        
        # Initialize calibration
        print("Initializing calibration...")
        self.calibration.initialize()
        
        # Create ROIs (parallel arrays)
        print("Creating ROIs using parallel arrays (MVTec spec)...")
        
        # Add some Rectangle1 ROIs
        rect1_count = 10
        self.roi_storage.rect1_rows = np.random.uniform(50, 100, rect1_count).astype(np.float32)
        self.roi_storage.rect1_cols = np.random.uniform(50, 100, rect1_count).astype(np.float32)
        self.roi_storage.rect1_rows2 = np.random.uniform(150, 200, rect1_count).astype(np.float32)
        self.roi_storage.rect1_cols2 = np.random.uniform(150, 200, rect1_count).astype(np.float32)
        self.roi_storage.rect1_names = np.array([f"Rect1_{i}" for i in range(rect1_count)])
        self.roi_storage.rect1_enabled = np.ones(rect1_count, dtype=bool)
        
        # Add Circle ROIs
        circle_count = 5
        self.roi_storage.circle_rows = np.random.uniform(250, 300, circle_count).astype(np.float32)
        self.roi_storage.circle_cols = np.random.uniform(250, 300, circle_count).astype(np.float32)
        self.roi_storage.circle_radii = np.random.uniform(20, 40, circle_count).astype(np.float32)
        self.roi_storage.circle_names = np.array([f"Circle_{i}" for i in range(circle_count)])
        self.roi_storage.circle_enabled = np.ones(circle_count, dtype=bool)
        
        # Mark region cache dirty to regenerate
        self.region_cache.dirty = True
        
        print(f"Created {rect1_count} Rectangle1 ROIs and {circle_count} Circle ROIs")
        print("Initialization complete")
    
    def _create_halcon_regions(self):
        """Create HALCON region objects from stored ROI arrays (only once)."""
        print("Creating HALCON region objects from stored ROI arrays...")
        
        # Create Rectangle1 regions
        if len(self.roi_storage.rect1_rows) > 0:
            self.region_cache.rect1_region = ha.gen_rectangle1(
                self.roi_storage.rect1_rows.tolist(),
                self.roi_storage.rect1_cols.tolist(),
                self.roi_storage.rect1_rows2.tolist(),
                self.roi_storage.rect1_cols2.tolist()
            )
        
        # Create Circle regions
        if len(self.roi_storage.circle_rows) > 0:
            self.region_cache.circle_region = ha.gen_circle(
                self.roi_storage.circle_rows.tolist(),
                self.roi_storage.circle_cols.tolist(),
                self.roi_storage.circle_radii.tolist()
            )
        
        # Create Ellipse regions
        if len(self.roi_storage.ellipse_rows) > 0:
            self.region_cache.ellipse_region = ha.gen_ellipse(
                self.roi_storage.ellipse_rows.tolist(),
                self.roi_storage.ellipse_cols.tolist(),
                self.roi_storage.ellipse_phis.tolist(),
                self.roi_storage.ellipse_radii1.tolist(),
                self.roi_storage.ellipse_radii2.tolist()
            )
        
        # Create Polygon regions
        if len(self.roi_storage.polygon_rows) > 0 and len(self.roi_storage.polygon_cols) > 0:
            rows_list = self.roi_storage.polygon_rows.flatten().tolist()
            cols_list = self.roi_storage.polygon_cols.flatten().tolist()
            self.region_cache.polygon_region = ha.gen_region_polygon(rows_list, cols_list)
        
        print("HALCON region objects created successfully")
    
    def _get_batch_statistics(self, temperature_image: np.ndarray) -> dict:
        """Stage 3: Batch statistics directly on cached region tuples."""
        print("Running batch statistics (MVTec architecture)...")
        
        # Convert numpy array to HALCON image
        halcon_image = ha.himage_from_numpy_array(temperature_image)
        
        results = {
            "rect1_stats": {},
            "circle_stats": {},
            "ellipse_stats": {},
            "polygon_stats": {}
        }
        
        # Process Rectangle1 regions
        if len(self.roi_storage.rect1_enabled) > 0 and np.any(self.roi_storage.rect1_enabled):
            rect1_indices = np.where(self.roi_storage.rect1_enabled)[0]
            if len(rect1_indices) > 0:
                mean, dev = ha.intensity(
                    self.region_cache.rect1_region,
                    halcon_image
                )
                results["rect1_stats"] = {
                    "mean": float(np.mean(mean)),
                    "std": float(np.mean(dev)),
                    "min": float(np.min(mean)),
                    "max": float(np.max(mean))
                }
        
        # Process Circle regions
        if len(self.roi_storage.circle_enabled) > 0 and np.any(self.roi_storage.circle_enabled):
            circle_indices = np.where(self.roi_storage.circle_enabled)[0]
            if len(circle_indices) > 0:
                mean, dev = ha.intensity(
                    self.region_cache.circle_region,
                    halcon_image
                )
                results["circle_stats"] = {
                    "mean": float(np.mean(mean)),
                    "std": float(np.mean(dev)),
                    "min": float(np.min(mean)),
                    "max": float(np.max(mean))
                }
        
        # Process Ellipse regions
        if len(self.roi_storage.ellipse_enabled) > 0 and np.any(self.roi_storage.ellipse_enabled):
            ellipse_indices = np.where(self.roi_storage.ellipse_enabled)[0]
            if len(ellipse_indices) > 0:
                mean, dev = ha.intensity(
                    self.region_cache.ellipse_region,
                    halcon_image
                )
                results["ellipse_stats"] = {
                    "mean": float(np.mean(mean)),
                    "std": float(np.mean(dev)),
                    "min": float(np.min(mean)),
                    "max": float(np.max(mean))
                }
        
        # Process Polygon regions
        if len(self.roi_storage.polygon_enabled) > 0 and np.any(self.roi_storage.polygon_enabled):
            polygon_indices = np.where(self.roi_storage.polygon_enabled)[0]
            if len(polygon_indices) > 0:
                mean, dev = ha.intensity(
                    self.region_cache.polygon_region,
                    halcon_image
                )
                results["polygon_stats"] = {
                    "mean": float(np.mean(mean)),
                    "std": float(np.mean(dev)),
                    "min": float(np.min(mean)),
                    "max": float(np.max(mean))
                }
        
        return results
    
    def _simulate_camera_frame(self) -> np.ndarray:
        """Stage 2: Simulate camera frame acquisition and temperature conversion."""
        print("Simulating camera frame acquisition...")
        
        # Generate synthetic temperature data (simulating 16-bit thermal image)
        temperature_image = np.random.normal(
            50.0,  # mean temperature
            10.0,  # std deviation
            (FEED_H, FEED_W)
        ).astype(np.float32)
        
        # Clip to realistic range
        temperature_image = np.clip(temperature_image, -20.0, 120.0)
        
        return temperature_image
    
    def _process_frame(self):
        """Process a single frame through the MVTec pipeline."""
        print(f"Processing frame {self.current_frame + 1}...")
        
        t0 = time.perf_counter()
        
        # Stage 2: Frame acquisition
        temperature_image = self._simulate_camera_frame()
        acquire_ms = (time.perf_counter() - t0) * 1000
        
        # Create HALCON regions if cache dirty
        if self.region_cache.dirty:
            self._create_halcon_regions()
            self.region_cache.dirty = False
        
        # Stage 3: Batch statistics (directly on cached regions)
        stats_t0 = time.perf_counter()
        self._get_batch_statistics(temperature_image)
        stats_ms = (time.perf_counter() - stats_t0) * 1000
        
        # Update GUI
        self.stats_label.setText(f"Frame: {self.current_frame + 1}")
        total_rois = (len(self.roi_storage.rect1_enabled) + len(self.roi_storage.circle_enabled) +
                     len(self.roi_storage.ellipse_enabled) + len(self.roi_storage.polygon_enabled))
        self.roi_count_label.setText(f"ROIs: {total_rois}")
        
        fps = 1000.0 / (time.perf_counter() - t0) if (time.perf_counter() - t0) > 0 else 0.0
        self.fps_label.setText(f"FPS: {fps:.1f}")
        
        print(f"Frame processed in {acquire_ms:.2f}ms (acquire), {stats_ms:.2f}ms (stats)")
        
        # Stage 4: Display (HALCON native)
        display_ms = self.thermal_view.display_frame(temperature_image)
        
        total_ms = (time.perf_counter() - t0) * 1000
        print(f"Total frame time: {total_ms:.2f}ms")
        
        # Record for benchmark
        self.frame_times.append(total_ms)
        self.current_frame += 1
        
        return total_ms
    
    def run_benchmark(self):
        """Run benchmark exactly as specified."""
        print("=" * 60)
        print("Running MVTec Architecture Benchmark")
        print("=" * 60)
        print("Benchmarking ROI counts:", BENCHMARK_COUNTS)
        
        results = []
        
        for count in BENCHMARK_COUNTS:
            print(f"\n--- Benchmarking {count} ROIs ---")
            
            # Reset prototype for this test
            self.roi_storage = GroupedROIStorage()
            self.region_cache = RegionCache()
            
            # Adjust ROI counts based on total
            rect1_count = min(count // 2, 100)
            circle_count = min(count // 4, 50)
            
            # Create random ROIs
            self.roi_storage.rect1_rows = np.random.uniform(50, 100, rect1_count).astype(np.float32)
            self.roi_storage.rect1_cols = np.random.uniform(50, 100, rect1_count).astype(np.float32)
            self.roi_storage.rect1_rows2 = np.random.uniform(150, 200, rect1_count).astype(np.float32)
            self.roi_storage.rect1_cols2 = np.random.uniform(150, 200, rect1_count).astype(np.float32)
            self.roi_storage.rect1_names = np.array([f"Rect1_{i}" for i in range(rect1_count)])
            self.roi_storage.rect1_enabled = np.ones(rect1_count, dtype=bool)
            
            self.roi_storage.circle_rows = np.random.uniform(250, 300, circle_count).astype(np.float32)
            self.roi_storage.circle_cols = np.random.uniform(250, 300, circle_count).astype(np.float32)
            self.roi_storage.circle_radii = np.random.uniform(20, 40, circle_count).astype(np.float32)
            self.roi_storage.circle_names = np.array([f"Circle_{i}" for i in range(circle_count)])
            self.roi_storage.circle_enabled = np.ones(circle_count, dtype=bool)
            
            # Warmup
            print("Warming up...")
            for _ in range(BENCHMARK_WARMUP):
                self._process_frame()
            
            # Benchmark
            frame_times = []
            for i in range(BENCHMARK_FRAMES):
                total_ms = self._process_frame()
                frame_times.append(total_ms)
            
            # Calculate statistics
            median_time = np.median(frame_times)
            min_time = np.min(frame_times)
            p95_time = np.percentile(frame_times, 95)
            fps = 1000.0 / median_time if median_time > 0 else 0.0
            
            result = {
                "rois": count,
                "median_ms": median_time,
                "min_ms": min_time,
                "p95_ms": p95_time,
                "fps": fps,
                "total_frames": BENCHMARK_FRAMES
            }
            
            results.append(result)
            
            print(f"Results for {count} ROIs: {fps:.1f} FPS, {median_time:.2f}ms median")
            
            # Brief pause between tests
            time.sleep(0.5)
        
        # Save benchmark results
        self._save_benchmark_results(results)
        
        # Display summary
        print("\n" + "=" * 60)
        print("BENCHMARK SUMMARY")
        print("=" * 60)
        print("ROIs | Median (ms) | P95 (ms) | FPS")
        print("-" * 50)
        for result in results:
            print(f"{result['rois']:4d} | {result['median_ms']:10.2f} | {result['p95_ms']:7.2f} | {result['fps']:5.1f}")
        
    def _save_benchmark_results(self, results):
        """Save benchmark results to CSV."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"benchmark_mvtec_prototype_{timestamp}.csv"
        
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = ['rois', 'median_ms', 'min_ms', 'p95_ms', 'fps', 'total_frames']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for result in results:
                writer.writerow(result)
        
        print(f"\nBenchmark results saved to: {filename}")
    
    def run_live_demo(self):
        """Run continuous live demo."""
        print("=" * 60)
        print("Running Live Demo")
        print("=" * 60)
        print("Press Ctrl+C to stop")
        
        timer = QTimer()
        timer.timeout.connect(self._process_frame)
        timer.start(1000 // Settings.TARGET_FPS)  # Run at target FPS
        
        # Start Qt event loop
        self.window.show()
        self.app.exec_()

if __name__ == "__main__":
    if RUN_BENCHMARK:
        prototype = MVTecPrototype()
        prototype.initialize()
        prototype.run_benchmark()
    else:
        prototype = MVTecPrototype()
        prototype.initialize()
        prototype.run_live_demo()