"""
blob_parser.py

Parses the calibration blob header.
"""

import struct

from models import CameraCalibration


class BlobParser:

    HEADER_SIZE = 16

    def __init__(self, blob: bytes):

        self.blob = blob

    def parse(self, camera: CameraCalibration):

        (
            camera.magic,
            camera.enabled_ranges,
            camera.enabled_mask,
            encoded_date,
        ) = struct.unpack_from("<IIII", self.blob, 0)

        run = encoded_date & 0x03

        day = (encoded_date >> 2) & 0x1F

        month = (encoded_date >> 7) & 0x0F

        year = ((encoded_date >> 11) & 0x1F) + 2000

        camera.calibration_date = (
            f"{day:02d}/{month:02d}/{year}"
        )

        print()

        print("=" * 60)

        print("Calibration Header")

        print("=" * 60)

        print(f"Magic              : 0x{camera.magic:08X}")

        print(f"Enabled Ranges     : {camera.enabled_ranges}")

        print(f"Enabled Mask       : 0x{camera.enabled_mask:08X}")

        print(f"Calibration Date   : {camera.calibration_date}")

        print(f"Run Number         : {run}")

        print()

        return BlobParser.HEADER_SIZE