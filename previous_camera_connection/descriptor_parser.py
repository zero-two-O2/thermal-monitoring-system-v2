"""
descriptor_parser.py

Parses all calibration descriptors.
"""

import struct

from models import CalibrationRange
from models import UniverseSegment


class DescriptorParser:

    SEGMENT_SIZE = 20
    DESCRIPTOR_SIZE = 248

    def __init__(self, blob):

        self.blob = blob

    def parse(self, camera, offset):

        for range_index in range(3):

            calibration_range, offset = self.parse_range(offset)

            camera.ranges.append(calibration_range)

        return offset

    def parse_range(self, offset):

        pos = offset

        cal_min = struct.unpack_from("<f", self.blob, pos)[0]
        pos += 4

        cal_max = struct.unpack_from("<f", self.blob, pos)[0]
        pos += 4

        disp_min = struct.unpack_from("<f", self.blob, pos)[0]
        pos += 4

        disp_max = struct.unpack_from("<f", self.blob, pos)[0]
        pos += 4

        manual_span = struct.unpack_from("<f", self.blob, pos)[0]
        pos += 4

        auto_span = struct.unpack_from("<f", self.blob, pos)[0]
        pos += 4

        num_segments = struct.unpack_from("<I", self.blob, pos)[0]
        pos += 4

        calibration_range = CalibrationRange(

            calibration_min=cal_min,
            calibration_max=cal_max,

            display_min=disp_min,
            display_max=disp_max,

            manual_palette_span=manual_span,
            auto_palette_span=auto_span,

            num_segments=num_segments

        )

        #
        # Read all 11 polynomial segments
        #

        for _ in range(11):

            u0, u1, u2, start_temp, end_temp = struct.unpack_from(
                "<5f",
                self.blob,
                pos
            )

            pos += self.SEGMENT_SIZE

            calibration_range.segments.append(

                UniverseSegment(

                    u0=u0,

                    u1=u1,

                    u2=u2,

                    start_temp=start_temp,

                    end_temp=end_temp

                )

            )

        return calibration_range, pos