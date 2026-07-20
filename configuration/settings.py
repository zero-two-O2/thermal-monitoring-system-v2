"""
settings.py

Contains all configurable settings for the application.
Edit this file to change application behaviour.
"""
from dataclasses import dataclass, field
from pathlib import Path

@dataclass(slots=True)
class Settings:
    # ==========================================================
    # Camera
    # ==========================================================
    MAX_CAMERAS: int = 8
    DEFAULT_CAMERA_PORT: int = 55000
    CONNECTION_TIMEOUT: float = 5.0
    RECONNECT_INTERVAL: float = 5.0
    TARGET_FPS: int = 10
    # ==========================================================
    # Processing
    # ==========================================================
    ENABLE_VISIBLE_STREAM: bool = True
    ENABLE_THERMAL_STREAM: bool = True
    ENABLE_TEMPERATURE_DATA: bool = True
    # ==========================================================
    # Recording
    # ==========================================================
    ENABLE_RECORDING: bool = True
    RECORDING_DURATION: int = 20
    RECORDING_FOLDER: Path = Path("recordings")
    # ==========================================================
    # Database
    # ==========================================================
    ENABLE_DATABASE: bool = False
    DATABASE_PATH: Path = Path("database/thermal_monitor.db")
    # ==========================================================
    # Logging
    # ==========================================================
    ENABLE_LOGGING: bool = True
    LOG_FOLDER: Path = Path("logs")
    LOG_LEVEL: str = "INFO"
    # ==========================================================
    # GUI
    # ==========================================================
    WINDOW_TITLE: str = "Thermal Monitoring System"
    WINDOW_WIDTH: int = 1600
    WINDOW_HEIGHT: int = 900
    DARK_THEME: bool = True
    # ==========================================================
    # Alarm
    
    DEFAULT_HIGH_TEMPERATURE: float = 80.0
    DEFAULT_LOW_TEMPERATURE: float = 0.0
    # ==========================================================
    # Misc
   
    PROJECT_NAME: str = "Thermal Monitoring System"
    VERSION: str = "2.0.0"

    # Calibration

    CALIBRATION_FILE = Path(
        "assets/calibration/calibration_blob.txt"
    )