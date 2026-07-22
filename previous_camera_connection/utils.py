"""
utils.py

Project constants and file locations.
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "Data"

CALIBRATION_DIR = DATA_DIR / "calibration"

RAW_DIR = DATA_DIR / "raw"

METADATA_DIR = DATA_DIR / "metadata"

OUTPUT_DIR = DATA_DIR / "output"


CALIBRATION_BLOB_FILE = CALIBRATION_DIR / "calibration_blob.txt"

CALIBRATION_INFO_FILE = CALIBRATION_DIR / "calibration_info.txt"

CAMERA_INFO_FILE = METADATA_DIR / "camera_info.txt"

RAW_IMAGE_FILE = RAW_DIR / "frame_0001.tif"


HEADER_SIZE = 16

MAX_SEGMENTS = 11

MAX_RANGES = 3