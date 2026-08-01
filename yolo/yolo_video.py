#!/usr/bin/env python3
"""Stream a camera or video through Isaac ROS YOLOv8 and display it in Rerun."""

from __future__ import annotations

import argparse
from collections import deque
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
import rerun as rr
from sensor_msgs.msg import CameraInfo, Image
from vision_msgs.msg import Detection2DArray

from yolo_demo import (
    CACHE, COCO_CLASSES, ENGINE, HEIGHT, MODEL, MODEL_SHA256, MODEL_URL, WIDTH,
    class_name, download, stop_process,
)

RECORDING = CACHE / "yolov8_video.rrd"
SAMPLE_VIDEO = CACHE / "person-bicycle-car-detection.mp4"
SAMPLE_VIDEO_URL = (
    "https://raw.githubusercontent.com/intel-iot-devkit/sample-videos/master/"
    "person-bicycle-car-detection.mp4"
)
SAMPLE_VIDEO_SHA256 = "452b11b7e0efbd019f1d9570d0c790e90416ad4ad29eec6003872d08443140ef"


def letterbox(frame: np.ndarray) -> np.ndarray:
    """Convert a BGR frame to a 640x640 RGB YOLO input without stretching it."""
    height, width = frame.shape[:2]
    scale = min(WIDTH / width, HEIGHT / height)
    resized = cv2.resize(
        frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_LINEAR
    )
    canvas = np.full((HEIGHT, WIDTH, 3), 114, dtype=np.uint8)
    y = (HEIGHT - resized.shape[0]) // 2
    x = (WIDTH - resized.shape[1]) // 2
    canvas[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
    return cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)


class VideoDemo(Node):
    def __init__(self) -> None:
        super().__init__("isaac_forge_yolov8_video")
        self.results: deque[Detection2DArray] = deque()
        self.image_pub = self.create_publisher(Image, "/image", 10)
        self.info_pub = self.create_publisher(CameraInfo, "/camera_info", 10)
        self.create_subscription(Detection2DArray, "/detections_output", self._detected, 10)

    def _detected(self, message: Detection2DArray) -> None:
        self.results.append(message)

    def publish_frame(self, pixels: np.ndarray) -> tuple[int, int]:
        stamp = self.get_clock().now().to_msg()
        image = Image()
        image.header.stamp = stamp
        image.header.frame_id = "video_camera"
        image.height = HEIGHT
        image.width = WIDTH
        image.encoding = "rgb8"
        image.step = WIDTH * 3
        image.data = pixels.tobytes()

        info = CameraInfo()
        info.header = image.header
        info.height = HEIGHT
        info.width = WIDTH
        info.distortion_model = "plumb_bob"
        info.k = [500.0, 0.0, 320.0, 0.0, 500.0, 320.0, 0.0, 0.0, 1.0]
        info.p = [500.0, 0.0, 320.0, 0.0, 0.0, 500.0, 320.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        self.image_pub.publish(image)
        self.info_pub.publish(info)
        return stamp.sec, stamp.nanosec

    def infer(self, pixels: np.ndarray, launch_process: subprocess.Popen[bytes]) -> Detection2DArray:
        """Publish one frame and wait for its matching decoder output."""
        while True:
            wanted = self.publish_frame(pixels)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if launch_process.poll() is not None:
                    raise RuntimeError(f"ROS launch exited with {launch_process.returncode}")
                rclpy.spin_once(self, timeout_sec=0.05)
                while self.results:
                    result = self.results.popleft()
                    stamp = result.header.stamp
                    if (stamp.sec, stamp.nanosec) == wanted:
                        return result
            # The first image can be published before the NITROS graph has connected.
            print("Waiting for the Isaac ROS graph to become ready...", flush=True)


def log_frame(frame_number: int, pixels: np.ndarray, result: Detection2DArray) -> None:
    centers, sizes, labels, class_ids = [], [], [], []
    for detection in result.detections:
        if not detection.results:
            continue
        hypothesis = detection.results[0].hypothesis
        center = detection.bbox.center.position
        centers.append([center.x, center.y])
        sizes.append([detection.bbox.size_x, detection.bbox.size_y])
        labels.append(f"{class_name(hypothesis.class_id)} {hypothesis.score:.2f}")
        try:
            class_ids.append(int(hypothesis.class_id))
        except ValueError:
            class_ids.append(0)

    rr.set_time("frame", sequence=frame_number)
    rr.log("camera/image", rr.Image(pixels))
    rr.log(
        "camera/image/detections",
        rr.Boxes2D(
            centers=centers,
            sizes=sizes,
            labels=labels,
            class_ids=class_ids,
            show_labels=True,
        ),
    )


def parse_source(value: str) -> int | str:
    return int(value) if value.isdigit() else value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", default="sample",
        help="'sample', camera index, video path, or stream URL (default: sample)",
    )
    parser.add_argument("--loop", action="store_true", help="loop when a video file ends")
    parser.add_argument("--max-frames", type=int, default=0, help="stop after N frames; 0 is unlimited")
    parser.add_argument(
        "--no-viewer", action="store_true",
        help="write a .rrd recording instead of spawning the Rerun viewer",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if shutil.which("nvidia-smi") is None:
        print("error: this demo requires an NVIDIA GPU and driver", file=sys.stderr)
        return 2

    CACHE.mkdir(exist_ok=True)
    try:
        download(MODEL_URL, MODEL, MODEL_SHA256)
        if args.source == "sample":
            download(SAMPLE_VIDEO_URL, SAMPLE_VIDEO, SAMPLE_VIDEO_SHA256)
    except (OSError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    source = str(SAMPLE_VIDEO) if args.source == "sample" else parse_source(args.source)
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        print(f"error: could not open video source {args.source!r}", file=sys.stderr)
        return 2

    rr.init("isaac_forge_yolov8_video", spawn=not args.no_viewer)
    if args.no_viewer:
        rr.save(str(RECORDING))
    rr.log(
        "camera/image/detections",
        rr.AnnotationContext([
            rr.ClassDescription(info=rr.AnnotationInfo(id=index, label=name))
            for index, name in enumerate(COCO_CLASSES)
        ]),
        static=True,
    )

    command = [
        "ros2", "launch", "isaac_ros_yolov8", "yolov8_tensor_rt.launch.py",
        f"model_file_path:={MODEL}", f"engine_file_path:={ENGINE}",
        "input_image_width:=640", "input_image_height:=640",
        "network_image_width:=640", "network_image_height:=640",
        "image_mean:=[0.0,0.0,0.0]", "image_stddev:=[1.0,1.0,1.0]",
        "input_binding_names:=[images]", "output_binding_names:=[output0]",
        "input_tensor_names:=[input_tensor]", "output_tensor_names:=[output_tensor]",
        "confidence_threshold:=0.25", "nms_threshold:=0.45",
    ]
    launch_process = subprocess.Popen(command, start_new_session=True)
    rclpy.init()
    node = VideoDemo()
    frame_number = 0
    print(f"Streaming {args.source!r} through YOLOv8; press Ctrl-C to stop.")
    try:
        while not args.max_frames or frame_number < args.max_frames:
            ok, frame = capture.read()
            if not ok:
                if args.loop and not isinstance(source, int):
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                break
            pixels = letterbox(frame)
            result = node.infer(pixels, launch_process)
            log_frame(frame_number, pixels, result)
            frame_number += 1
            if frame_number % 30 == 0:
                print(f"Processed {frame_number} frames", flush=True)
    except KeyboardInterrupt:
        pass
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        capture.release()
        node.destroy_node()
        rclpy.shutdown()
        stop_process(launch_process)

    print(f"Processed {frame_number} frames")
    if args.no_viewer:
        print(f"Rerun recording: {RECORDING}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
