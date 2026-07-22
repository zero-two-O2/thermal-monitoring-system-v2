"""
calibration_loader.py

Loads the calibration blob exported from HALCON.

Author : Shubham
Project: Thermal Camera SDK
"""

import binascii

from utils import CALIBRATION_BLOB_FILE
from models import CameraCalibration


class CalibrationLoader:

    def __init__(self):

        self.camera = CameraCalibration()

        self.binary_blob = None

    def load(self):

        """
        Load the calibration blob from calibration_blob.txt
        """


        with open(CALIBRATION_BLOB_FILE, "r") as file:

            hex_string = file.read().strip()

        if hex_string.startswith("0x"):

            hex_string = hex_string[2:]

        self.binary_blob = binascii.unhexlify(hex_string)

        return self.binary_blob