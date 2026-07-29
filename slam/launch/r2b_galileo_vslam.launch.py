"""cuVSLAM on NVIDIA's r2b Galileo dataset, running on RoboStack conda packages.

Fully GPU pipeline, all in one rclcpp_components node container so NITROS can hand
buffers between stages without leaving the device:

    /front_stereo_camera/{left,right}/image_compressed   (H.264, from the bag)
        -> DecoderNode              NVDEC hardware decode
        -> ImageFormatConverterNode  -> mono8 via CV-CUDA
        -> VisualSlamNode            cuVSLAM stereo tracking
        -> /visual_slam/tracking/odometry + slam_path

NVDEC needs two things that are now fixed in the recipe rather than patched into a
vendor binary: the decoder is source-built with the upstream fix for absolute
DT_NEEDED entries (ISSUES.md #2), and it is built against CUDA 13 headers rather than
the build machine's CUDA 12 (see README.md). The byte-patching phase that used to
rewrite sonames in libdecoder_node.so is gone.
Set USE_NVDEC=0 to fall back to the CPU decoder in h264_bridge.py.

Only the front stereo pair is used. The bag has four pairs, so num_cameras could go
to 8, but two is enough to show real tracking and keeps the graph readable.

The images are NOT rectified -- camera_info reports a rational_polynomial model
with non-zero distortion coefficients -- so rectified_images is false and cuVSLAM
undistorts internally. That avoids an extra RectifyNode per camera.
"""

import os

from launch import LaunchDescription
from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode

# From the bag's /tf_static tree: base_link -> front_stereo_camera ->
# front_stereo_camera_{left,right} -> ..._optical
LEFT_FRAME = 'front_stereo_camera_left_optical'
RIGHT_FRAME = 'front_stereo_camera_right_optical'
BASE_FRAME = 'base_link'

WIDTH, HEIGHT = 1920, 1200

USE_NVDEC = os.environ.get('USE_NVDEC', '1') != '0'


def _decoder(side: str) -> ComposableNode:
    return ComposableNode(
        package='isaac_ros_h264_decoder',
        plugin='nvidia::isaac_ros::h264_decoder::DecoderNode',
        name=f'decoder_{side}',
        remappings=[
            ('image_compressed', f'/front_stereo_camera/{side}/image_compressed'),
            ('image_uncompressed', f'/front/{side}/image_raw'),
        ],
    )


def _to_mono(side: str) -> ComposableNode:
    return ComposableNode(
        package='isaac_ros_image_proc',
        plugin='nvidia::isaac_ros::image_proc::ImageFormatConverterNode',
        name=f'format_{side}',
        parameters=[{
            'encoding_desired': 'mono8',
            'image_width': WIDTH,
            'image_height': HEIGHT,
        }],
        remappings=[
            ('image_raw', f'/front/{side}/image_raw'),
            ('image', f'/front/{side}/image_mono'),
        ],
    )


def generate_launch_description() -> LaunchDescription:
    visual_slam = ComposableNode(
        package='isaac_ros_visual_slam',
        plugin='nvidia::isaac_ros::visual_slam::VisualSlamNode',
        name='visual_slam',
        parameters=[{
            'num_cameras': 2,
            'min_num_images': 2,
            'enable_localization_n_mapping': True,
            'enable_slam_visualization': True,
            'enable_landmarks_view': True,
            'enable_observations_view': True,
            # The bag's images are distorted; let cuVSLAM undistort.
            'rectified_images': False,
            'camera_optical_frames': [LEFT_FRAME, RIGHT_FRAME],
            'base_frame': BASE_FRAME,
            'publish_tf': True,
            'image_jitter_threshold_ms': 40.0,
        }],
        remappings=[
            ('visual_slam/image_0', '/front/left/image_mono'),
            ('visual_slam/camera_info_0', '/front_stereo_camera/left/camera_info'),
            ('visual_slam/image_1', '/front/right/image_mono'),
            ('visual_slam/camera_info_1', '/front_stereo_camera/right/camera_info'),
        ],
    )

    nodes = [visual_slam]
    if USE_NVDEC:
        nodes = [
            _decoder('left'), _decoder('right'),
            _to_mono('left'), _to_mono('right'),
            visual_slam,
        ]

    return LaunchDescription([
        ComposableNodeContainer(
            name='vslam_container',
            namespace='',
            package='rclcpp_components',
            executable='component_container_mt',
            composable_node_descriptions=nodes,
            output='screen',
            arguments=['--ros-args', '--log-level', 'info'],
        ),
    ])
