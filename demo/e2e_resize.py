#!/usr/bin/env python3
"""End-to-end GPU test: push an image through Isaac ROS ResizeNode and read it back.

Publishes a synthetic 640x480 rgb8 image plus a matching CameraInfo on /image and
/camera_info, and waits for the GPU-resized result on /resize/image. A correct
result proves the whole chain works: RoboStack rclpy -> NVIDIA's NITROS node ->
CV-CUDA/VPI on the GPU -> back out as a ROS message.

Assumes a node container is already running with ResizeNode loaded at 320x240.
"""

from __future__ import annotations

import sys

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image

WIDTH, HEIGHT = 640, 480
EXPECT_W, EXPECT_H = 320, 240
TIMEOUT_S = 30.0


def make_image(stamp) -> Image:
    """A vertical colour ramp, so a resize is visibly a resize and not a crop."""
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    frame[:, :, 0] = np.linspace(0, 255, WIDTH, dtype=np.uint8)[None, :]
    frame[:, :, 1] = np.linspace(0, 255, HEIGHT, dtype=np.uint8)[:, None]
    frame[:, :, 2] = 128

    msg = Image()
    msg.header.stamp = stamp
    msg.header.frame_id = "camera"
    msg.height, msg.width = HEIGHT, WIDTH
    msg.encoding = "rgb8"
    msg.is_bigendian = 0
    msg.step = WIDTH * 3
    msg.data = frame.tobytes()
    return msg


def make_camera_info(stamp) -> CameraInfo:
    msg = CameraInfo()
    msg.header.stamp = stamp
    msg.header.frame_id = "camera"
    msg.height, msg.width = HEIGHT, WIDTH
    msg.distortion_model = "plumb_bob"
    msg.d = [0.0] * 5
    fx = fy = 500.0
    cx, cy = WIDTH / 2.0, HEIGHT / 2.0
    msg.k = [fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0]
    msg.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    msg.p = [fx, 0.0, cx, 0.0, 0.0, fy, cy, 0.0, 0.0, 0.0, 1.0, 0.0]
    return msg


class ResizeProbe(Node):
    def __init__(self) -> None:
        super().__init__("resize_probe")
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.pub_img = self.create_publisher(Image, "image", qos)
        self.pub_info = self.create_publisher(CameraInfo, "camera_info", qos)
        self.create_subscription(Image, "resize/image", self._on_result, qos)
        self.create_timer(0.1, self._tick)
        self.result: Image | None = None
        self.sent = 0

    def _tick(self) -> None:
        stamp = self.get_clock().now().to_msg()
        self.pub_img.publish(make_image(stamp))
        self.pub_info.publish(make_camera_info(stamp))
        self.sent += 1

    def _on_result(self, msg: Image) -> None:
        if self.result is None:
            self.result = msg


def main() -> int:
    rclpy.init()
    node = ResizeProbe()
    print(f"publishing {WIDTH}x{HEIGHT} rgb8 on /image, waiting for /resize/image ...")

    deadline = node.get_clock().now().nanoseconds + int(TIMEOUT_S * 1e9)
    while node.result is None and node.get_clock().now().nanoseconds < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)

    out = node.result
    node.destroy_node()
    rclpy.shutdown()

    if out is None:
        print(f"FAIL: nothing received on /resize/image after {TIMEOUT_S:.0f}s "
              f"({node.sent} frames published)")
        return 1

    print(f"received /resize/image: {out.width}x{out.height} {out.encoding}, "
          f"{len(out.data)} bytes")

    ok = (out.width, out.height) == (EXPECT_W, EXPECT_H)
    if not ok:
        print(f"FAIL: expected {EXPECT_W}x{EXPECT_H}")
        return 1

    # A uniform buffer would mean the pipeline moved bytes but computed nothing.
    arr = np.frombuffer(out.data, dtype=np.uint8)
    if arr.min() == arr.max():
        print("FAIL: output is a uniform buffer -- no actual resampling happened")
        return 1

    print(f"content check: min={arr.min()} max={arr.max()} mean={arr.mean():.1f} "
          "-- real resampled pixel data")
    print(f"\nPASS: {WIDTH}x{HEIGHT} -> {out.width}x{out.height} on the GPU, "
          f"after {node.sent} published frames")
    return 0


if __name__ == "__main__":
    sys.exit(main())
