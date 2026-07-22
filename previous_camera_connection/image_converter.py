import numpy as np


class ImageConverter:

    @staticmethod
    def convert_image_to_temperature(raw_image, lut):
        """
        Convert uint16 detector image to float temperature image.
        """

        raw_image = raw_image.astype(np.uint16)

        temperature_image = lut[raw_image]

        return temperature_image.astype(np.float32)


    @staticmethod
    def get_temperature_statistics(temp_image):

        valid = temp_image[np.isfinite(temp_image)]

        if valid.size == 0:
            return None

        return {
            "min": float(valid.min()),
            "max": float(valid.max()),
            "mean": float(valid.mean())
        }


    @staticmethod
    def temperature_to_display(temp_image):

        valid = temp_image[np.isfinite(temp_image)]

        display = np.zeros(temp_image.shape, dtype=np.uint8)

        if valid.size == 0:
            return display

        tmin = valid.min()
        tmax = valid.max()

        if abs(tmax - tmin) < 1e-6:
            return display

        display = ((temp_image - tmin) /
                   (tmax - tmin) * 255.0)

        display = np.clip(display, 0, 255)

        return display.astype(np.uint8)


    @staticmethod
    def raw_to_display(raw_image):

        minimum = raw_image.min()
        maximum = raw_image.max()

        display = (raw_image.astype(np.float32) - minimum)

        display *= 255.0 / (maximum - minimum)

        return display.astype(np.uint8)