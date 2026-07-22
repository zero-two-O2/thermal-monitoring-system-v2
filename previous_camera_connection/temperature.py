"""
temperature.py
"""

import math
from models import CalibrationRange, UniverseSegment


class TemperatureCalculator:

    @staticmethod
    def solve(raw_power: float, segment: UniverseSegment):

        if segment.u2 == 0:
            return None

        d = segment.u1 ** 2 - 4.0 * segment.u2 * (segment.u0 - raw_power)

        if d < 0:
            return None

        temp = (-segment.u1 + math.sqrt(d)) / (2.0 * segment.u2)

        if segment.start_temp <= temp <= segment.end_temp:
            return temp

        return None

    @staticmethod
    def raw_to_temperature(raw_power: float,
                           calibration_range: CalibrationRange):

        #
        # Try every valid segment
        #
        for segment in calibration_range.segments[:calibration_range.num_segments]:

            temperature = TemperatureCalculator.solve(
                raw_power,
                segment
            )

            if temperature is not None:
                return temperature

        return None