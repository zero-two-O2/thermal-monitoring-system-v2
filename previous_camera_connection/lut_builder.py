"""
lut_builder.py

Builds temperature lookup tables for each calibration range.

Author : Shubham
"""

import numpy as np

from models import CameraCalibration
from temperature import TemperatureCalculator


class LUTBuilder:

    LUT_SIZE = 65536

    def __init__(self):

        pass

    def build(self,
              camera: CameraCalibration,
              range_index: int):

        """
        Build the LUT for one calibration range.
        """

        calibration_range = camera.get_range(range_index)

        print()
        print("=" * 70)
        print(f"Building LUT : Range {range_index}")
        print("=" * 70)

        lut = np.full(
            self.LUT_SIZE,
            np.nan,
            dtype=np.float32
        )

        valid_count = 0

        for raw in range(self.LUT_SIZE):

            temperature = TemperatureCalculator.raw_to_temperature(
                raw,
                calibration_range
            )

            if temperature is not None:

                lut[raw] = np.float32(temperature)

                valid_count += 1

        camera.set_lookup_table(
            range_index,
            lut
        )

        print(f"Finished Range {range_index}")
        print(f"Valid Entries : {valid_count}")
        print(f"Invalid Entries : {self.LUT_SIZE-valid_count}")

    def build_all(self,
                  camera: CameraCalibration):

        print()
        print("=" * 70)
        print("Generating Lookup Tables")
        print("=" * 70)

        for i in range(len(camera.ranges)):

            self.build(
                camera,
                i
            )

        print()
        print("=" * 70)
        print("Lookup Tables Complete")
        print("=" * 70)