#!/usr/bin/env python3
"""Decode the r2b Galileo H.264 streams on the CPU and republish as mono8.

Why this exists: NVIDIA's own isaac_ros_h264_decoder cannot run from a conda
prefix. libdecoder_node.so dlopens three libraries by absolute FHS path --

    /usr/lib/x86_64-linux-gnu/libnvbuf_fdmap.so
    /usr/lib/x86_64-linux-gnu/libnvbufsurface.so
    /usr/lib/x86_64-linux-gnu/libnvbufsurftransform.so

-- and an absolute dlopen cannot be redirected by RPATH, LD_LIBRARY_PATH or
patchelf. We ship all three in $PREFIX/lib, so the only fixes are a symlink farm
under /usr/lib (needs root, pollutes the host) or a patch upstream. It is the one
component in the whole stack that is not relocatable.

So NVDEC is out and this does the decode on the CPU with PyAV. cuVSLAM, the part
the demo is actually about, still runs on the GPU. Decode is the cheap half of
this pipeline anyway.
"""

from __future__ import annotations

import sys

import av
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage, Image

SIDES = ("left", "right")


class Decoder:
    """One H.264 decode context, fed Annex-B NAL units packet by packet."""

    def __init__(self) -> None:
        self.ctx = av.CodecContext.create("h264", "r")
        self.frames = 0
        self.errors = 0

    def decode(self, payload: bytes) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        try:
            for packet in self.ctx.parse(payload):
                for frame in self.ctx.decode(packet):
                    # gray8 gives us mono8 directly, which is what cuVSLAM wants.
                    out.append(frame.to_ndarray(format="gray"))
                    self.frames += 1
        except Exception:  # noqa: BLE001 - a corrupt packet must not kill the node
            self.errors += 1
        return out


class H264Bridge(Node):
    def __init__(self) -> None:
        super().__init__("h264_bridge")
        qos = QoSProfile(depth=20, reliability=ReliabilityPolicy.RELIABLE)
        self.decoders = {s: Decoder() for s in SIDES}
        self.pubs = {
            s: self.create_publisher(Image, f"/front/{s}/image_mono", qos)
            for s in SIDES
        }
        for s in SIDES:
            self.create_subscription(
                CompressedImage,
                f"/front_stereo_camera/{s}/image_compressed",
                lambda msg, side=s: self._on_packet(msg, side),
                qos,
            )
        self.create_timer(5.0, self._report)

    def _on_packet(self, msg: CompressedImage, side: str) -> None:
        for gray in self.decoders[side].decode(bytes(msg.data)):
            out = Image()
            # Keep the original stamp and frame: cuVSLAM matches the stereo pair on
            # timestamp and looks the extrinsics up in tf by frame_id.
            out.header = msg.header
            out.height, out.width = gray.shape[:2]
            out.encoding = "mono8"
            out.is_bigendian = 0
            out.step = out.width
            out.data = gray.tobytes()
            self.pubs[side].publish(out)

    def _report(self) -> None:
        parts = [f"{s}={self.decoders[s].frames}" for s in SIDES]
        errs = sum(self.decoders[s].errors for s in SIDES)
        self.get_logger().info(
            f"decoded frames {' '.join(parts)}" + (f" (errors {errs})" if errs else "")
        )


def main() -> int:
    rclpy.init()
    node = H264Bridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
