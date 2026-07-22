import numpy as np

from calibration_loader import CalibrationLoader
from blob_parser import BlobParser
from descriptor_parser import DescriptorParser
from lut_builder import LUTBuilder
from image_converter import ImageConverter


class ThermalSDK:

    def __init__(self):

        self.calibration = None
        self.lookup_tables = []

        self.initialized = False


    # --------------------------------------------------
    # Initialize SDK
    # --------------------------------------------------

    def initialize(self):

        print("\nLoading Calibration...")

        blob = CalibrationLoader.load()

        header = BlobParser.parse(blob)

        self.calibration = DescriptorParser.parse(blob)

        self.calibration.magic = header.magic
        self.calibration.enabled_ranges = header.enabled_ranges
        self.calibration.enabled_mask = header.enabled_mask
        self.calibration.calibration_date = header.calibration_date

        print("Building Lookup Tables...")

        self.lookup_tables.clear()

        for calibration_range in self.calibration.ranges:

            lut = LUTBuilder.build(calibration_range)

            self.lookup_tables.append(lut)

        self.initialized = True

        print("SDK Ready.\n")


    # --------------------------------------------------
    # Return Camera Calibration
    # --------------------------------------------------

    def get_calibration(self):

        return self.calibration


    # --------------------------------------------------
    # Convert one detector value
    # --------------------------------------------------

    def detector_to_temperature(self,
                                detector_value,
                                range_index=0):

        if not self.initialized:
            raise RuntimeError("SDK not initialized.")

        lut = self.lookup_tables[range_index]

        return float(lut[int(detector_value)])


    # --------------------------------------------------
    # Convert an entire image
    # --------------------------------------------------

    def convert_image(self,
                      raw_image,
                      range_index=0):

        if not self.initialized:
            raise RuntimeError("SDK not initialized.")

        lut = self.lookup_tables[range_index]

        return ImageConverter.convert_image_to_temperature(
            raw_image,
            lut
        )


    # --------------------------------------------------
    # Display Image
    # --------------------------------------------------

    def display_image(self,
                      raw_image):

        return ImageConverter.raw_to_display(raw_image)


    # --------------------------------------------------
    # Temperature Display
    # --------------------------------------------------

    def display_temperature_image(self,
                                  temperature_image):

        return ImageConverter.temperature_to_display(
            temperature_image
        )


    # --------------------------------------------------
    # Image Statistics
    # --------------------------------------------------

    def statistics(self,
                   temperature_image):

        return ImageConverter.get_temperature_statistics(
            temperature_image
        )


    # --------------------------------------------------
    # Pixel Temperature
    # --------------------------------------------------

    def pixel_temperature(self,
                          temperature_image,
                          row,
                          column):

        return float(
            temperature_image[row, column]
        )


    # --------------------------------------------------
    # Select Calibration Range
    # --------------------------------------------------

    def range_info(self):

        info = []

        for i, r in enumerate(self.calibration.ranges):

            info.append({

                "Range": i,

                "MinTemp": r.calibration_min,

                "MaxTemp": r.calibration_max,

                "Segments": r.num_segments

            })

        return info