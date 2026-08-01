#!/usr/bin/env python3
"""Run a real YOLOv8n model through Isaac ROS and visualize its detections."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

import numpy as np
from PIL import Image as PILImage, ImageDraw, ImageOps
import rclpy
from rclpy.node import Node
import rerun as rr
from sensor_msgs.msg import CameraInfo, Image
from vision_msgs.msg import Detection2DArray

WIDTH = 640
HEIGHT = 640
CACHE = Path(__file__).resolve().parent / ".cache"
MODEL = CACHE / "yolov8n.onnx"
ENGINE = CACHE / "yolov8n.plan"
INPUT_IMAGE = CACHE / "bus.jpg"
RESULT_IMAGE = CACHE / "yolov8_result.png"
RECORDING = CACHE / "yolov8_result.rrd"

# This is an Ultralytics 8.2.67 export of the official COCO YOLOv8n weights.
MODEL_URL = (
    "https://huggingface.co/salim4n/yolov8n-detect-onnx/resolve/main/"
    "yolov8n-onnx-web/yolov8n.onnx"
)
MODEL_SHA256 = "162ec5e9d2886fc411e4b81811c731e81a72c8f85571de1e0ab040833d92d4f2"
IMAGE_URL = "https://ultralytics.com/images/bus.jpg"
IMAGE_SHA256 = "c02019c4979c191eb739ddd944445ef408dad5679acab6fd520ef9d434bfbc63"

COCO_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
)


def download(url: str, path: Path, expected_sha256: str) -> None:
    """Download an asset once and reject incomplete or changed content."""
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256:
        return

    temporary = path.with_suffix(path.suffix + ".download")
    print(f"Downloading {url}\n       -> {path}")
    try:
        with urllib.request.urlopen(url) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        if digest != expected_sha256:
            raise RuntimeError(
                f"SHA-256 mismatch for {path.name}: expected {expected_sha256}, got {digest}"
            )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_image(path: Path) -> np.ndarray:
    """Letterbox the sample to the network size using YOLO's padding color."""
    with PILImage.open(path) as source:
        source = source.convert("RGB")
        source.thumbnail((WIDTH, HEIGHT), PILImage.Resampling.LANCZOS)
        padded = ImageOps.pad(
            source, (WIDTH, HEIGHT), method=PILImage.Resampling.LANCZOS,
            color=(114, 114, 114), centering=(0.5, 0.5),
        )
        return np.asarray(padded).copy()


class Demo(Node):
    def __init__(self, pixels: np.ndarray) -> None:
        super().__init__("isaac_forge_yolov8_demo")
        self.pixels = pixels
        self.result: Detection2DArray | None = None
        self.image_pub = self.create_publisher(Image, "/image", 10)
        self.info_pub = self.create_publisher(CameraInfo, "/camera_info", 10)
        self.create_subscription(
            Detection2DArray, "/detections_output", self._detected, 10)

    def _detected(self, message: Detection2DArray) -> None:
        if message.detections:
            self.result = message

    def publish_frame(self) -> None:
        stamp = self.get_clock().now().to_msg()
        image = Image()
        image.header.stamp = stamp
        image.header.frame_id = "demo_camera"
        image.height = HEIGHT
        image.width = WIDTH
        image.encoding = "rgb8"
        image.is_bigendian = 0
        image.step = WIDTH * 3
        image.data = self.pixels.tobytes()

        info = CameraInfo()
        info.header = image.header
        info.height = HEIGHT
        info.width = WIDTH
        info.distortion_model = "plumb_bob"
        info.k = [500.0, 0.0, 320.0, 0.0, 500.0, 320.0, 0.0, 0.0, 1.0]
        info.p = [500.0, 0.0, 320.0, 0.0, 0.0, 500.0, 320.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        self.image_pub.publish(image)
        self.info_pub.publish(info)


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def class_name(class_id: str) -> str:
    try:
        index = int(class_id)
    except ValueError:
        return class_id
    return COCO_CLASSES[index] if 0 <= index < len(COCO_CLASSES) else class_id


def visualize(pixels: np.ndarray, result: Detection2DArray, show_viewer: bool) -> None:
    centers, sizes, labels = [], [], []
    annotated = PILImage.fromarray(pixels)
    draw = ImageDraw.Draw(annotated)

    for detection in result.detections:
        if not detection.results:
            continue
        hypothesis = detection.results[0].hypothesis
        center = detection.bbox.center.position
        width, height = detection.bbox.size_x, detection.bbox.size_y
        label = f"{class_name(hypothesis.class_id)} {hypothesis.score:.2f}"
        centers.append([center.x, center.y])
        sizes.append([width, height])
        labels.append(label)
        x0, y0 = center.x - width / 2, center.y - height / 2
        x1, y1 = center.x + width / 2, center.y + height / 2
        draw.rectangle((x0, y0, x1, y1), outline=(255, 60, 60), width=3)
        draw.text((x0 + 3, max(0, y0 - 13)), label, fill=(255, 60, 60), stroke_width=2,
                  stroke_fill=(0, 0, 0))

    annotated.save(RESULT_IMAGE)
    rr.init("isaac_forge_yolov8", spawn=show_viewer)
    if not show_viewer:
        rr.save(str(RECORDING))
    rr.log("camera/image", rr.Image(pixels))
    rr.log(
        "camera/image/detections",
        rr.Boxes2D(centers=centers, sizes=sizes, labels=labels),
    )
    print(f"Annotated image: {RESULT_IMAGE}")
    if not show_viewer:
        print(f"Rerun recording: {RECORDING} (open with `rerun {RECORDING}`)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
        download(IMAGE_URL, INPUT_IMAGE, IMAGE_SHA256)
    except (OSError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    pixels = prepare_image(INPUT_IMAGE)
    print("Starting Isaac ROS with the real COCO YOLOv8n model.")
    print("TensorRT may take a few minutes to build the first engine...")

    command = [
        "ros2", "launch", "isaac_ros_yolov8", "yolov8_tensor_rt.launch.py",
        f"model_file_path:={MODEL}",
        f"engine_file_path:={ENGINE}",
        "input_image_width:=640",
        "input_image_height:=640",
        "network_image_width:=640",
        "network_image_height:=640",
        "image_mean:=[0.0,0.0,0.0]",
        # ImageToTensorNode already scales uint8 pixels to [0, 1]. YOLOv8 expects
        # that range directly, so applying another /255 here suppresses every box.
        "image_stddev:=[1.0,1.0,1.0]",
        "input_binding_names:=[images]",
        "output_binding_names:=[output0]",
        "input_tensor_names:=[input_tensor]",
        "output_tensor_names:=[output_tensor]",
        "confidence_threshold:=0.25",
        "nms_threshold:=0.45",
    ]
    launch_process = subprocess.Popen(command, start_new_session=True)

    rclpy.init()
    node = Demo(pixels)
    print("Waiting for a non-empty Detection2DArray; Rerun opens after inference...")
    deadline = time.monotonic() + 360
    try:
        while time.monotonic() < deadline and node.result is None:
            if launch_process.poll() is not None:
                print(f"error: ROS launch exited with {launch_process.returncode}", file=sys.stderr)
                return 1
            node.publish_frame()
            rclpy.spin_once(node, timeout_sec=0.25)

        if node.result is None:
            print("error: timed out waiting for a YOLOv8 detection", file=sys.stderr)
            return 1

        print(f"\nYOLOv8 found {len(node.result.detections)} object(s):")
        for detection in node.result.detections:
            if not detection.results:
                continue
            hypothesis = detection.results[0].hypothesis
            print(f"  {class_name(hypothesis.class_id):14s} {hypothesis.score:.2f}")
        visualize(pixels, node.result, show_viewer=not args.no_viewer)
        print("\nSuccess: image -> CUDA/NITROS -> TensorRT -> YOLOv8 -> Rerun")
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()
        stop_process(launch_process)


if __name__ == "__main__":
    raise SystemExit(main())
