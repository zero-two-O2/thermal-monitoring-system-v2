"""
Hardware integration test for the Fluke TV46L.

Keyboard

Q -> Quit

N -> Manual NUC

S -> Camera Status

I -> Camera Information

P -> Packet Statistics
"""

import cv2
import numpy as np
import time

from camera.camera_info import CameraInfo
from camera.tv46l_camera import TV46LCamera
from configuration.settings import Settings


def normalize(image):
    image = image.astype(np.float32)
    mn = image.min()
    mx = image.max()
    if mx > mn:
        image = (image - mn) / (mx - mn)
    image *= 255
    return image.astype(np.uint8)

def main():
    # Change these values if required.
    camera_info = CameraInfo(
        device="3408e1d8dbbe_FlukeProcessInstruments_TV46L1260100039Hz",
        serial="HB25080011",
        model="TV46L-1-26010003@9Hz",
        vendor="Fluke Process Instruments",
        ip="169.254.91.157",
    )

    camera = TV46LCamera(
        camera_info,
        Settings,
    )

    print()

    print("Connecting...")

    camera.connect()

    camera.start()

    print("Waiting for first frame...")

    if not camera.wait_for_first_frame(10):

        print("No frames received.")

        camera.disconnect()

        return

    print("Camera Ready.")

    last_print = time.time()

    while True:

        frame = camera.get_latest_frame()

        if frame is not None:

            image = normalize(frame.image)

            cv2.imshow(
                "TV46L Thermal",
                image,
            )

        if time.time() - last_print >= 1:

            print(
                f"FPS={camera.get_fps()}   "
                f"Frames={camera.frame_count}"
            )

            last_print = time.time()

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):

            break

        elif key == ord("n"):

            print()

            print("Manual NUC")

            camera.manual_nuc()

        elif key == ord("s"):

            print()

            print(camera.status())

        elif key == ord("i"):

            print()

            print(camera.camera_information())

        elif key == ord("p"):

            print()

            stats = camera.get_stream_statistics()

            for k, v in stats.items():

                print(f"{k:45} {v}")

    print()

    print("Disconnecting...")

    camera.disconnect()

    cv2.destroyAllWindows()

    print("Finished.")


if __name__ == "__main__":

    main()