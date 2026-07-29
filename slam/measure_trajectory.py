#!/usr/bin/env python3
"""Record cuVSLAM output while the r2b Galileo bag plays, then report on it.

Success is not "the node loaded" -- it is that cuVSLAM produced a trajectory that
moves. So this subscribes to /visual_slam/tracking/odometry, integrates the path
length, and compares against the wheel odometry the bag carries on /chassis/odom.
"""

from __future__ import annotations

import math
import sys

import rclpy
from nav_msgs.msg import Odometry, Path
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy


def dist(a, b) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


class TrajectoryProbe(Node):
    def __init__(self) -> None:
        super().__init__('trajectory_probe')
        qos = QoSProfile(depth=200, reliability=ReliabilityPolicy.RELIABLE)
        self.vo: list[tuple[float, float, float]] = []
        self.wheel: list[tuple[float, float, float]] = []
        self.slam_path_len = 0
        self.create_subscription(Odometry, '/visual_slam/tracking/odometry',
                                 self._on_vo, qos)
        self.create_subscription(Odometry, '/chassis/odom', self._on_wheel, qos)
        self.create_subscription(Path, '/visual_slam/tracking/slam_path',
                                 self._on_path, qos)

    @staticmethod
    def _xyz(msg: Odometry) -> tuple[float, float, float]:
        p = msg.pose.pose.position
        return (p.x, p.y, p.z)

    def _on_vo(self, msg: Odometry) -> None:
        self.vo.append(self._xyz(msg))

    def _on_wheel(self, msg: Odometry) -> None:
        self.wheel.append(self._xyz(msg))

    def _on_path(self, msg: Path) -> None:
        self.slam_path_len = max(self.slam_path_len, len(msg.poses))


def path_length(pts: list[tuple[float, float, float]]) -> float:
    return sum(dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))


def main() -> int:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0

    rclpy.init()
    node = TrajectoryProbe()
    print(f'recording cuVSLAM odometry for {duration:.0f}s ...', flush=True)

    deadline = node.get_clock().now().nanoseconds + int(duration * 1e9)
    while node.get_clock().now().nanoseconds < deadline:
        rclpy.spin_once(node, timeout_sec=0.2)

    vo, wheel, slam_poses = node.vo, node.wheel, node.slam_path_len
    node.destroy_node()
    rclpy.shutdown()

    print()
    print(f'  /visual_slam/tracking/odometry   {len(vo):5d} msgs')
    print(f'  /visual_slam/tracking/slam_path  {slam_poses:5d} poses')
    print(f'  /chassis/odom (wheel, ground ref){len(wheel):5d} msgs')

    if not vo:
        print('\nFAIL: cuVSLAM published no odometry')
        return 1

    vo_len = path_length(vo)
    net = dist(vo[0], vo[-1])
    print()
    print(f'  cuVSLAM path length   {vo_len:8.2f} m')
    print(f'  cuVSLAM net displacement {net:6.2f} m')
    if wheel:
        wheel_len = path_length(wheel)
        print(f'  wheel odom path length{wheel_len:8.2f} m')
        if wheel_len > 0.5:
            err = abs(vo_len - wheel_len) / wheel_len * 100.0
            print(f'  agreement with wheel odom: {100 - err:.1f}% '
                  f'({err:.1f}% difference in path length)')

    # A stuck tracker still publishes odometry, it just never moves.
    if vo_len < 0.10:
        print(f'\nFAIL: trajectory is {vo_len:.3f} m -- tracker never moved')
        return 1

    print(f'\nPASS: cuVSLAM tracked {vo_len:.2f} m over {len(vo)} poses on the GPU')
    return 0


if __name__ == '__main__':
    sys.exit(main())
