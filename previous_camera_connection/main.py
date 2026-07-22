import cv2
import time
import numpy as np

from calibration_loader import CalibrationLoader
from blob_parser import BlobParser
from descriptor_parser import DescriptorParser
from lut_builder import LUTBuilder

from models import CameraCalibration

from camera_manager import CameraManager
from camera_context import CameraContext

from live_camera import LiveCamera

from mouse import create_callback,get_mouse


def main():

    print("="*70)
    print("Fluke TV46L Multi Camera Viewer")
    print("="*70)

    calibration=CameraCalibration()

    loader=CalibrationLoader()
    blob=loader.load()

    print()
    print(f"Calibration Blob Size : {len(blob)} bytes")

    parser=BlobParser(blob)
    offset=parser.parse(calibration)

    descriptor=DescriptorParser(blob)
    descriptor.parse(calibration,offset)

    builder=LUTBuilder()
    builder.build_all(calibration)

    print()
    print("="*70)
    print("Calibration Ready")
    print("="*70)

    manager=CameraManager()
    manager.scan()
    manager.print_summary()

    if manager.count()==0:
        print("No Cameras Found")
        return

    contexts=[]

    print()
    print("="*70)
    print("Opening Cameras")
    print("="*70)

    for index in range(manager.count()):

        info=manager.get(index)

        camera=LiveCamera(info)
        camera.open()

        context=CameraContext(
            camera=camera,
            window_name=f"Camera {index+1}",
            lut=calibration.get_lookup_table(0)
        )

        contexts.append(context)

        cv2.namedWindow(
            context.window_name,
            cv2.WINDOW_NORMAL
        )

        cv2.setMouseCallback(
            context.window_name,
            create_callback(context.window_name)
        )

        print(f"Window Created : {context.window_name}")

    print()
    print("="*70)
    print("Initialization Complete")
    print("="*70)

    print()
    print(f"Cameras Opened : {len(contexts)}")
    print("Grab Threads Started")

    last_stats=time.time()
    last_nuc=time.time()

    print()
    print("="*70)
    print("Starting Live Acquisition")
    print("="*70)

    while True:

        #
        # Print statistics every minute
        #

        if time.time()-last_stats>60:

            print()
            print("="*70)
            print("STREAM STATISTICS")
            print("="*70)

            for context in contexts:
                context.camera.print_stream_statistics()

            last_stats=time.time()
        
        # Manual NUC every 3 minutes
        
        if time.time()-last_nuc>60:

            print()
            print("="*70)
            print("MANUAL NUC")
            print("="*70)

            # Request every camera almost simultaneously
            for context in contexts:
                context.camera.manual_nuc()
            last_nuc=time.time()

        # Display loop

        for context in contexts:
            frame=context.camera.grab_numpy()

            if frame is None:
                continue

            context.raw=frame

            context.temperature=context.lut[frame]

            context.min_temp=float(np.nanmin(context.temperature))
            context.max_temp=float(np.nanmax(context.temperature))
            context.avg_temp=float(np.nanmean(context.temperature))

            h,w=context.temperature.shape

            cx=w//2
            cy=h//2

            context.center_temp=float(
                context.temperature[
                    cy,
                    cx
                ]
            )

            mx,my=get_mouse(
                context.window_name
            )

            mx=max(
                0,
                min(mx,w-1)
            )

            my=max(
                0,
                min(my,h-1)
            )

            context.mouse_x=mx
            context.mouse_y=my

            context.mouse_temp=float(
                context.temperature[
                    my,
                    mx
                ]
            )

            display=cv2.normalize(
                context.temperature,
                None,
                0,
                255,
                cv2.NORM_MINMAX
            )

            display=display.astype(np.uint8)

            context.display=cv2.applyColorMap(
                display,
                cv2.COLORMAP_JET
            )

            cv2.line(
                context.display,
                (mx-10,my),
                (mx+10,my),
                (255,255,255),
                1
            )

            cv2.line(
                context.display,
                (mx,my-10),
                (mx,my+10),
                (255,255,255),
                1
            )

            cv2.putText(
                context.display,
                f"SN : {context.camera.serial}",
                (20,25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255,255,255),
                2
            )

            cv2.putText(
                context.display,
                f"Min : {context.min_temp:.2f} C",
                (20,50),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255,255,255),
                2
            )

            cv2.putText(
                context.display,
                f"Max : {context.max_temp:.2f} C",
                (20,75),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255,255,255),
                2
            )

            cv2.putText(
                context.display,
                f"Avg : {context.avg_temp:.2f} C",
                (20,100),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255,255,255),
                2
            )

            cv2.putText(
                context.display,
                f"Center : {context.center_temp:.2f} C",
                (20,125),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255,255,255),
                2
            )

            cv2.putText(
                context.display,
                f"Mouse : {context.mouse_temp:.2f} C",
                (20,150),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255,255,255),
                2
            )

            fps=context.camera.get_fps()

            cv2.putText(
                context.display,
                f"FPS : {fps}",
                (20,175),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255,255,255),
                2
            )

            context.next_frame()

            cv2.imshow(
                context.window_name,
                context.display
            )

        key=cv2.waitKey(1)

        if key==27:
            break

    print()
    print("="*70)
    print("Closing Cameras")
    print("="*70)

    for context in contexts:
        context.camera.close()

    cv2.destroyAllWindows()

if __name__=="__main__":
    main()  


        