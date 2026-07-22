"""
live_camera.py

Threaded Fluke TV46L Camera
"""

import time
import threading

import halcon as ha
import numpy as np
import traceback

class LiveCamera:

    def __init__(self,camera_info):

        self.info=camera_info
        self.device=camera_info.device
        self.serial=camera_info.serial
        self.model=camera_info.model
        self.vendor=camera_info.vendor
        self.ip=camera_info.ip
        self.status=camera_info.status
        self.acq=None
        self.running=False
        self.thread=None
        self.lock=threading.Lock()
        self.latest_raw=None
        self.latest_temperature=None
        self.latest_display=None
        self.frame_counter=0
        self.last_frame_time=0
        self.timeout_counter=0
        self.nuc_requested=False
        self.last_seen_packets=0
        self.last_lost_packets=0
        self.min_temp=0.0
        self.max_temp=0.0
        self.avg_temp=0.0
        self.center_temp=0.0
        self.mouse_temp=0.0
        self.profile_count=0

        self.grab_total=0.0
        self.convert_total=0.0

        self.grab_max=0.0
        self.convert_max=0.0

    # Open Camera
    def open(self):
        self.acq=ha.open_framegrabber(
            "GigEVision2",
            0,
            0,
            0,
            0,
            0,
            0,
            "progressive",
            -1,
            "default",
            -1,
            "false",
            "default",
            self.device,
            0,
            -1
        )

        try:
            ha.set_framegrabber_param(
                self.acq,
                "[Stream]DeviceStreamChannelNegotiatePacketSize",
                1
            )
        except:
            pass

        print(
            ha.get_framegrabber_param(
                self.acq,
                "[Stream]DeviceStreamChannelPacketSize"
            )
        )

        ha.set_framegrabber_param(
            self.acq,
            "[Stream]GevStreamReceiveSocketSize",
            1048576
        )
        


        ha.set_framegrabber_param(
            self.acq,
            "FLK_TI_StreamDataSourceSelector",
            "IR_Data"
        )

        ha.set_framegrabber_param(
            self.acq,
            "bits_per_channel",
            16
        )

        try:
            ha.set_framegrabber_param(
                self.acq,
                "num_buffers",
                32
            )
        except:
            pass

        # Disable automatic NUC
        try:

            ha.set_framegrabber_param(
                self.acq,
                "FLK_TI_ControlFeature_REControlCmd",
                "FLK_TI_ControlFeature_REControlCmd_DisableAutomaticFineOffsets"
            )

            print(f"{self.serial}: Automatic Fine Offset Disabled")

        except Exception as e:

            print(f"{self.serial}: Could not disable Automatic Fine Offset")
            print(e)

        # Continuous acquisition
        ha.grab_image_start(
            self.acq,
            -1
        )

        self.running=True

        self.start_thread()

        print()
        print("="*70)
        print("Camera Opened")
        print("="*70)
        print("Model :",self.model)
        print("Serial:",self.serial)
        print("Vendor:",self.vendor)
        print("IP    :",self.ip)

    # ---------------------------------------------------------
    # Start Acquisition Thread
    # ---------------------------------------------------------

    def start_thread(self):

        self.thread=threading.Thread(
            target=self.grab_loop,
            daemon=True,
            name=f"Grab-{self.serial}"
        )

        self.thread.start()

    # ---------------------------------------------------------
    # Acquisition Thread
    # ---------------------------------------------------------

    def grab_loop(self):

        while self.running:

            try:

                #
                # Manual NUC requested
                #

                if self.nuc_requested:

                    print(f"{self.serial}: Manual NUC")

                    #
                    # Request Fine Offset
                    #

                    ha.set_framegrabber_param(
                        self.acq,
                        "FLK_TI_ControlFeature_REControlCmd",
                        "FLK_TI_ControlFeature_REControlCmd_RequestFineOffset"
                    )

                    #
                    # Execute Fine Offset
                    #

                    ha.set_framegrabber_param(
                        self.acq,
                        "FLK_TI_ControlFeature_REControlCmd",
                        "FLK_TI_ControlFeature_REControlCmd_ExecuteFineOffset"
                    )
                    # Firmware needs a very small amount of time.
                    # Do NOT stop acquisition.
                    time.sleep(0.05)
                    # Flush a few bad frames produced during shutter motion.

                    for _ in range(3):

                        try:

                            image=ha.grab_image_async(
                                self.acq,
                                0
                            )

                        except:
                            pass

                    self.nuc_requested=False

                t0=time.perf_counter()
                image=ha.grab_image_async(
                    self.acq,
                    100
                )
                t1=time.perf_counter()
                
                frame=ha.himage_as_numpy_array(
                    image
                )
                t2=time.perf_counter()

                grab_ms=(t1-t0)*1000
                convert_ms=(t2-t1)*1000

                self.profile_count+=1

                self.grab_total+=grab_ms
                self.convert_total+=convert_ms

                self.grab_max=max(self.grab_max,grab_ms)
                self.convert_max=max(self.convert_max,convert_ms)

                if self.profile_count>=300:

                    print()
                    print("="*60)
                    print(self.serial)
                    print("="*60)

                    print(f"Average Grab    : {self.grab_total/self.profile_count:.3f} ms")
                    print(f"Average Convert : {self.convert_total/self.profile_count:.3f} ms")
                    print(f"Maximum Grab    : {self.grab_max:.3f} ms")
                    print(f"Maximum Convert : {self.convert_max:.3f} ms")

                    self.profile_count=0
                    self.grab_total=0.0
                    self.convert_total=0.0
                    self.grab_max=0.0
                    self.convert_max=0.0

                with self.lock:

                    self.latest_raw=frame.copy()

                    self.frame_counter+=1

                    self.last_frame_time=time.time()

            except Exception as e:

                print()
                print("=" * 60)
                print(self.serial)
                print("Grab Exception")
                print("=" * 60)

                traceback.print_exc()

                self.timeout_counter += 1

                time.sleep(0.001)

    # ---------------------------------------------------------
    # Return Latest Frame
    # ---------------------------------------------------------

    def grab_numpy(self):

        with self.lock:

            if self.latest_raw is None:
                return None

            return self.latest_raw.copy()

    # ---------------------------------------------------------
    # Latest Frame Without Copy (optional)
    # ---------------------------------------------------------

    def get_latest_frame(self):

        with self.lock:
            return self.latest_raw

    # ---------------------------------------------------------
    # Manual NUC
    # ---------------------------------------------------------

    def manual_nuc(self):

        self.nuc_requested=True

    # ---------------------------------------------------------
    # Is Camera Alive
    # ---------------------------------------------------------

    def is_alive(self):

        if self.last_frame_time==0:
            return False

        return (time.time()-self.last_frame_time)<2.0

    # ---------------------------------------------------------
    # FPS
    # ---------------------------------------------------------

    def get_fps(self):

        now=time.time()

        if not hasattr(self,"fps_timer"):

            self.fps_timer=now
            self.last_frame_counter=self.frame_counter
            self.fps=0

            return 0

        if now-self.fps_timer>=1:

            self.fps=self.frame_counter-self.last_frame_counter

            self.last_frame_counter=self.frame_counter

            self.fps_timer=now

        return self.fps

    # ---------------------------------------------------------
    # Stream Statistics
    # ---------------------------------------------------------

    def print_stream_statistics(self):

        print()
        print("="*60)
        print(self.serial)
        print("="*60)

        params=[
            "[Stream]GevStreamSeenPacketCount",
            "[Stream]GevStreamLostPacketCount",
            "[Stream]GevStreamDeliveredPacketCount",
            "[Stream]GevStreamUnavailablePacketCount",
            "[Stream]GevStreamDuplicatePacketCount",
            "[Stream]GevStreamResendPacketCount"
        ]

        for p in params:

            try:

                print(
                    p,
                    ha.get_framegrabber_param(
                        self.acq,
                        p
                    )
                )

            except:
                pass

        print("Frames Grabbed :",self.frame_counter)
        print("Timeouts       :",self.timeout_counter)
        print("Alive          :",self.is_alive())
        print("FPS            :",self.get_fps())

    # ---------------------------------------------------------
    # Stop Thread
    # ---------------------------------------------------------

    def stop_thread(self):

        self.running=False

        if self.thread is not None:

            self.thread.join(
                timeout=2
            )

            self.thread=None

    # ---------------------------------------------------------
    # Close Camera
    # ---------------------------------------------------------

    def close(self):

        self.stop_thread()

        if self.acq is not None:

            try:

                ha.close_framegrabber(
                    self.acq
                )

            except:
                pass

            self.acq=None

        print()
        print("="*70)
        print(f"{self.serial} Closed")
        print("="*70)

    



