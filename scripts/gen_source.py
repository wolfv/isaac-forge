#!/usr/bin/env python3
"""Generate source-build rattler-build recipes for Isaac ROS packages.

Companion to gen_repack.py. Where that one unpacks NVIDIA's debs, this one compiles
published source against RoboStack, which is what we want wherever source exists.

Per-package build traits are detected from the actual CMakeLists.txt rather than
guessed: whether CUDA has to be enabled, whether it is a rosidl interface package,
whether it needs Eigen, and so on. Run it after ./scripts/fetch_sources.sh has
populated the source cache.

    python scripts/gen_source.py                 # all packages in PACKAGES
    python scripts/gen_source.py <name> [...]    # just these
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_repack import DROP, EXTERNAL, MAP  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECIPES = os.path.join(ROOT, "recipes")
CACHE = os.path.join(ROOT, ".srccache")

# Upstream tarballs. NVIDIA sources are pinned to the v5.0-0 release tag (or release-5.0 commit where the tag is pending); osrf's
# negotiated has no tags at all, so it is pinned to a commit.
REPOS = {
    "isaac_ros_nitros": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_nitros/archive/refs/tags/v5.0-0.tar.gz",
        sha256="dfba350fcaecf100b9d01d174c3acc8c5757d44ef4726d4bccbef721c117c4e9"),
    "isaac_ros_common": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_common/archive/refs/tags/v5.0-0.tar.gz",
        sha256="1878a57b9e9aa44c3d4b74e7f7f9b32ecdf461ce20b43ce09ede31518662ab8c"),
    "isaac_ros_image_pipeline": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_image_pipeline/archive/refs/tags/v5.0-0.tar.gz",
        sha256="26f2e85b6e86f1414f7dafb362ec70c13a3e93802a56fe9b75f59a5cbac0b42b"),
    "isaac_ros_visual_slam": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/archive/refs/tags/v5.0-0.tar.gz",
        sha256="94c9b4c71ea11105d5bfa6c949895db24d19ae088ef722bea98c3cdbc15c25b2"),
    "isaac_ros_benchmark": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_benchmark/archive/refs/tags/v5.0-0.tar.gz",
        sha256="0e5e14c01996ca6c05826889f085ca8bf4cb41490e953b541fb5b34daf8dff35"),
    "ros2_benchmark": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/ros2_benchmark/archive/refs/tags/v5.0-0.tar.gz",
        sha256="eb4e719905eb9a91045e48fb7bba93c8f05904ee5d92e0f69cb0c76443046cbc"),
    "isaac_ros_cumotion": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_cumotion/archive/refs/tags/v5.0-0.tar.gz",
        sha256="8a5d685a0227bf545c8e07dcf248f19855ec163d82d6c92612859ef510d65d1e"),
    # release-5.0 still carries this interface at version 4.6.0; cloud control needs it.
    "isaac_ros_manipulation": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_manipulation/archive/f5c47880e42ec10aa2e94c856d9992bc6b936fb3.tar.gz",
        sha256="7746da33bc0700ad0dd9067e0ad0fbc2da986185a1233d52d7c7fccbeb186de8"),
    "isaac_ros_image_segmentation": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_image_segmentation/archive/refs/tags/v5.0-0.tar.gz",
        sha256="21185fae90c38dfa42fe501a4921dd0b9c6c014c9225136dd8326e38d2e4638d"),
    "isaac_ros_pose_estimation": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_pose_estimation/archive/refs/tags/v5.0-0.tar.gz",
        sha256="5e5138211051336013a9800b8dbd296e254e154b523da5305cf5f2d29a082fca"),
    "isaac_ros_dnn_inference": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_dnn_inference/archive/c16ac2c8669051ae1f3c6d77684f91fb25756f21.tar.gz",
        sha256="0d72343a522e699ca4fcece08e5cb1af0d4cb3797d68a59e1de579c41c71ed8a"),
    "isaac_ros_object_detection": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_object_detection/archive/refs/tags/v5.0-0.tar.gz",
        sha256="464feaafa73022b434664756499951a608d04b9b6c2825c74f87a1e0aaabce21"),
    "isaac_ros_mapping_and_localization": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_mapping_and_localization/archive/refs/tags/v5.0-0.tar.gz",
        sha256="b4be0a658aa6a5cd02ef3bdfc0d600c2f0dccb8ed46844a08d61b9f8888752b0"),
    "rosidl": dict(
        url="https://github.com/ros2/rosidl/archive/00d13c5139b5eb2000b5b190a558cac5eb9e8bf2.tar.gz",
        sha256="c4d7f8ce216277561d393751bc3f77ef2e5384f5bc4b679b40da9f057331e89f",
        homepage="https://github.com/ros2/rosidl"),
    "rosidl_buffer_backends": dict(
        url="https://github.com/ros2/rosidl_buffer_backends/archive/7e723061d03b347bedea69009b003f33e9b53314.tar.gz",
        sha256="2b065cdc5387290a3514987a3673a61665e99afc25c09c0bc4b3a46057b9fa71",
        homepage="https://github.com/ros2/rosidl_buffer_backends"),
    "negotiated": dict(
        url="https://github.com/osrf/negotiated/archive/"
            "eac198b55dcd052af5988f0f174902913c5f20e7.tar.gz",
        sha256="01aed43adef3e6ef3d9e1879d3a2910d6acdcf802e6ea2905ab4626e21d7af05",
        homepage="https://github.com/osrf/negotiated"),
    "isaac_ros_nvblox": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_nvblox/archive/refs/tags/v5.0-0.tar.gz",
        sha256="487bb927e1e6118908c7ab54b5d2be449f98d30481f118d231bb51069acd6f7a"),
    # Repositories published in the Isaac ROS 5.0 release. Repositories without a
    # v5.0-0 tag remain outside this source-build set.
    "isaac_ros_apriltag": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_apriltag/archive/refs/tags/v5.0-0.tar.gz",
        sha256="83fe79ca7202cc8214cc77350e1bdd5427703a27736d9f8bf94cc1112b35cac9"),
    "isaac_ros_compression": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_compression/archive/refs/tags/v5.0-0.tar.gz",
        sha256="28da59a0b5818c3c5862fca1d11944837b8e215b33d9db5dab4dfaab7b1991bc"),
    "isaac_ros_teleop": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_teleop/archive/refs/tags/v5.0-0.tar.gz",
        sha256="78a4eb21e9e554455294bcdb2ee2de00e624ea9412d892be125ccc1b3506a863"),
    "isaac_ros_dnn_stereo_depth": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_dnn_stereo_depth/archive/refs/tags/v5.0-0.tar.gz",
        sha256="2f5f9723c51275c37ab9be8f8846a7a4bdbbc5fef1a75bffa1febda734af7279"),
    "isaac_ros_cloud_control": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_cloud_control/archive/refs/tags/v5.0-0.tar.gz",
        sha256="f45fe5425833424a5ee7b3a8ec027d17c397d9ee339ce43ba7fc58e48aa59176"),
    "isaac_ros_data_tools": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_data_tools/archive/refs/tags/v5.0-0.tar.gz",
        sha256="f248aa65a6dbf3ca1dec74c5da908f59f2519a2e0e17a341fc2f32ca9c1da708"),
    "isaac_ros_jetson": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_jetson/archive/refs/tags/v5.0-0.tar.gz",
        sha256="c8f96bc0c4128fa53ceef76dd00dd2272801c171a0094163a4de612dcc5fbe1f"),
    "isaac_ros_examples": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_examples/archive/refs/tags/v5.0-0.tar.gz",
        sha256="69220ac65fe2bf6060e14799c129c802d8787e52460179dab60dfbc1c713f7c2"),
    # Five more. isaac_ros_nova, isaac_ros_depth_segmentation and isaac_ros_argus_camera
    # were checked at the same time and all three return 404 for v4.5-0 -- see ISSUES.md #23,
    # which now covers four repositories rather than two.
    "isaac_ros_deploy": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_deploy/archive/4cee440f70ce8d6ddd1ba9c542fe8c3900f00003.tar.gz",
        sha256="df7d2b06e1786eed46d6ca38425352e11c5c349c26b6ef70c8ceb6fedb895860"),
    "isaac_ros_learned_policies": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_learned_policies/archive/refs/tags/v5.0-0.tar.gz",
        sha256="674bc98cffb8bc01b30cc97cab0a2bcfa492a96fa2eb5556e3edce7748811922"),
    "isaac_ros_physical_ai": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_physical_ai/archive/refs/tags/v5.0-0.tar.gz",
        sha256="4874fd814e1dee519e532807d8cffbb7e04aabc6dbda1993d9639a85c1f9d480"),
    "isaac_ros_robots": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_robots/archive/refs/tags/v5.0-0.tar.gz",
        sha256="e7fe907bcfccb32a2c0c253c3b76cf01b81c2c5885e4369bc37c4df0b646843c"),
    "isaac_ros_sipl_camera": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_sipl_camera/archive/refs/tags/v5.0-0.tar.gz",
        sha256="da98b51e54f6c1923d42543ad95579b576341c191aa5b104691762e6ef0030f4"),
    # Documented as part of Isaac ROS 5.0, but kept in its own repository rather than
    # the original 35-repository source inventory. Pure URDF/mesh/launch data.
    "sensor_mounting_rig": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/sensor_mounting_rig/archive/refs/tags/v5.0-0.tar.gz",
        sha256="b14e5649d0717b5bca95f0cd093380f8cc095c4bbef3aaca166b475c6e94b2ac"),
    # Public ROS interfaces used by unitree_g1_bridge. Pin the commit because upstream
    # publishes no releases and the master branch moves.
    "unitree_ros2": dict(
        url="https://github.com/unitreerobotics/unitree_ros2/archive/"
            "668d1ec5a05d1c38d3306bdca7d59f2ba3581a88.tar.gz",
        sha256="3e96da843c611878e28148ce113d978e5464dec922fc06dcd8c340f8232a6883",
        homepage="https://github.com/unitreerobotics/unitree_ros2"),
    # Not NVIDIA's, and not in RoboStack either -- see the note on
    # ros-jazzy-topic-based-ros2-control below. Pinned to a commit because there is no
    # jazzy release to pin to.
    "topic_based_ros2_control": dict(
        url="https://github.com/PickNikRobotics/topic_based_ros2_control/archive/"
            "6bd8d55e1c4ad3188770fe5c8b93b942bcede4a2.tar.gz",
        sha256="32168384d0913bd052533289b3d3b9a330ba47055d613f771a7697d6f65c214c",
        homepage="https://github.com/PickNikRobotics/topic_based_ros2_control"),
}

# conda package name -> (repo, path within the repo). Order here is the build order:
# interfaces and leaf libraries first, so a plain sequential build resolves.
PACKAGES = [
    # rosidl interface packages -- no Isaac deps, safe to go first
    ("ros-jazzy-isaac-ros-tensor-list-interfaces", "isaac_ros_common", "isaac_ros_tensor_list_interfaces"),
    ("ros-jazzy-isaac-ros-pointcloud-interfaces", "isaac_ros_common", "isaac_ros_pointcloud_interfaces"),
    ("ros-jazzy-isaac-ros-visual-slam-interfaces", "isaac_ros_visual_slam", "isaac_ros_visual_slam_interfaces"),
    ("ros-jazzy-ros2-benchmark-interfaces", "ros2_benchmark", "ros2_benchmark_interfaces"),
    ("ros-jazzy-negotiated-interfaces", "negotiated", "negotiated_interfaces"),
    ("ros-jazzy-negotiated", "negotiated", "negotiated"),
    # Buffer backends introduced by ROS 2 Rolling and used by Isaac ROS 5.0.
    ("ros-jazzy-rosidl-buffer", "rosidl", "rosidl_buffer"),
    ("ros-jazzy-rosidl-buffer-backend", "rosidl", "rosidl_buffer_backend"),
    ("ros-jazzy-rosidl-buffer-backend-registry", "rosidl", "rosidl_buffer_backend_registry"),
    ("ros-jazzy-cuda-buffer-backend-msgs", "rosidl_buffer_backends",
     "cuda_buffer_backend/cuda_buffer_backend_msgs"),
    ("ros-jazzy-tensor-msgs", "rosidl_buffer_backends", "tensor_msgs"),
    ("ros-jazzy-cuda-buffer", "rosidl_buffer_backends", "cuda_buffer_backend/cuda_buffer"),
    ("ros-jazzy-cuda-buffer-backend", "rosidl_buffer_backends",
     "cuda_buffer_backend/cuda_buffer_backend"),
    # small libraries and interfaces
    ("ros-jazzy-isaac-common", "isaac_ros_common", "isaac_common"),
    ("ros-jazzy-isaac-ros-common", "isaac_ros_common", "isaac_ros_common"),
    ("ros-jazzy-isaac-ros-tensor-msgs", "isaac_ros_common", "isaac_ros_tensor_msgs"),
    ("ros-jazzy-isaac-ros-topic-tools", "isaac_ros_common", "isaac_ros_topic_tools"),
    ("ros-jazzy-isaac-ros-gpu-partitioning", "isaac_ros_common", "isaac_ros_gpu_partitioning"),
    ("ros-jazzy-isaac-ros-r2b-galileo", "isaac_ros_common", "isaac_ros_r2b_galileo"),
    ("ros-jazzy-teleop-ros2-interfaces", "isaac_ros_teleop", "teleop_ros2_interfaces"),
    # utility and conversion libraries
    ("ros-jazzy-cvcuda-conversions", "isaac_ros_image_pipeline", "cvcuda_conversions"),
    ("ros-jazzy-pointcloud-conversions", "isaac_ros_image_pipeline", "pointcloud_conversions"),
    ("ros-jazzy-tensorrt-conversions", "isaac_ros_dnn_inference", "tensorrt_conversions"),
    ("ros-jazzy-triton-conversions", "isaac_ros_dnn_inference", "triton_conversions"),
    ("ros-jazzy-vpi-conversions", "isaac_ros_image_pipeline", "vpi_conversions"),
    ("ros-jazzy-isaac-ros-vpi-utils", "isaac_ros_image_pipeline", "isaac_ros_vpi_utils"),
    ("ros-jazzy-isaac-ros-cvcuda-utils", "isaac_ros_image_pipeline", "isaac_ros_cvcuda_utils"),
    ("ros-jazzy-isaac-ros-image-proc", "isaac_ros_image_pipeline", "isaac_ros_image_proc"),
    ("ros-jazzy-isaac-ros-h264-decoder", "isaac_ros_compression", "isaac_ros_h264_decoder"),
    # benchmark harness
    ("ros-jazzy-ros2-benchmark", "ros2_benchmark", "ros2_benchmark"),
    ("ros-jazzy-isaac-ros-benchmark", "isaac_ros_benchmark", "isaac_ros_benchmark"),
    ("ros-jazzy-isaac-ros-image-proc-benchmark", "isaac_ros_benchmark", "benchmarks/isaac_ros_image_proc_benchmark"),
    # --- the manipulation stack ------------------------------------------------
    # Interfaces it needs from sibling repos, then the manipulation packages
    # themselves. The two bringup packages follow near the end, after their complete
    # DNN + nvblox closure. Their optional Triton launch path is omitted at runtime;
    # TensorRT supplies the usable inference backend.
    # topic_based_ros2_control is the ros2_control hardware interface both robot
    # description packages name for their Isaac Sim configuration. It has never been
    # released for jazzy -- rosdistro carries it for humble only, and ros-controls has
    # since superseded it with topic_based_hardware_interfaces -- so RoboStack, which
    # builds what rosdistro releases, cannot have it and `rosdep install` on jazzy cannot
    # resolve it either. It is BSD-licensed, four dependencies wide and builds clean, so
    # it is built here from the upstream commit. See ISSUES.md.
    ("ros-jazzy-topic-based-ros2-control", "topic_based_ros2_control", "."),
    # robotiq_controllers used to be built here. It is in robostack-jazzy now (0.0.1,
    # the same release tag), so the duplicate is gone and the dependency resolves from
    # the channel -- which was always the right outcome: its sibling robotiq_description
    # was already there and this was only ever a selection gap.
    ("ros-jazzy-isaac-ros-cumotion-interfaces", "isaac_ros_cumotion", "isaac_ros_cumotion_interfaces"),
    ("ros-jazzy-isaac-ros-segment-anything2-interfaces", "isaac_ros_image_segmentation", "isaac_ros_segment_anything2_interfaces"),
    ("ros-jazzy-isaac-ros-manipulation-interfaces", "isaac_ros_manipulation",
     "isaac_ros_manipulation_interfaces"),
    # ament_python leaves
    ("ros-jazzy-isaac-common-py", "isaac_ros_common", "isaac_common_py"),
    ("ros-jazzy-isaac-ros-launch-utils", "isaac_ros_common", "isaac_ros_launch_utils"),
    # isaac_ros_test is a test harness, but not an optional one:
    # isaac_ros_manipulation_ros_python_utils/test_utils.py imports IsaacROSBaseTest at
    # module level and __init__.py re-exports it, so `import
    # isaac_ros_manipulation_ros_python_utils` fails without it. That is also where the
    # pytorch dependency comes from -- isaac_ros_test/__init__.py pulls in
    # mock_model_generator, which imports torch.
    ("ros-jazzy-isaac-ros-test", "isaac_ros_common", "isaac_ros_test"),
    # C++ / rosidl on top of the python utilities
    # --- cuMotion, which the last two manipulation packages need -----------------
    # The cuMotion library itself is already packaged: libcumotion.so.1.1.0, its headers
    # and its CMake config ship inside ros-jazzy-isaac-ros-nitros, registered in the
    # ament index as the `cumotion` resource, exactly like cuVSLAM. These four packages
    # are the ROS layer over it and build from source.
    #
    # nvblox_msgs comes from isaac_ros_nvblox and is a plain rosidl package. packages.json
    # marks everything that depends on it `ros1`, which is an artefact of the inventory
    # keying packages by name: isaac_ros_noetic_interfaces ships a *different*
    # nvblox_msgs, a catkin package, and it wins the name collision. The jazzy one has no
    # ROS 1 dependency at all.
    ("ros-jazzy-nvblox-msgs", "isaac_ros_nvblox", "nvblox_msgs"),
    ("ros-jazzy-cumotion-vendor", "isaac_ros_nitros", "cumotion_vendor"),
    ("ros-jazzy-isaac-ros-cumotion-robot-description", "isaac_ros_cumotion", "isaac_ros_cumotion_robot_description"),
    ("ros-jazzy-isaac-ros-cumotion", "isaac_ros_cumotion", "isaac_ros_cumotion"),
    ("ros-jazzy-isaac-ros-cumotion-object-attachment", "isaac_ros_cumotion", "isaac_ros_cumotion_object_attachment"),
    # Needs cuMotion's object attachment and the Robotiq gripper controller, so it comes
    # after both.
    # Last of the manipulation packages: it needs isaac_ros_cumotion_moveit, so it only
    # became reachable once cuMotion built against eigen 5.
    # The MoveIt plugin: cuMotion (Eigen 3 ABI) and moveit_core (Eigen 5) in one
    # translation unit. Only buildable because of the eigen decision in TRAIT_DEPS.
    ("ros-jazzy-isaac-ros-cumotion-moveit", "isaac_ros_cumotion", "isaac_ros_cumotion_moveit"),
    # --- pose estimation, and the two DNN-inference packages it needs ------------
    #
    # isaac_ros_dnn_inference is where TensorRT lives, so the whole repo reads as
    # blocked -- but only two of its four packages touch it. isaac_ros_tensor_proc and
    # isaac_ros_dnn_image_encoder are CV-CUDA tensor plumbing with no inference engine
    # anywhere in their manifests or their CMakeLists, and everything under them
    # (isaac_ros_image_proc, managed_nitros, nitros, the type adapters, libcvcuda) is
    # already built here. The two actual inference nodes follow below, backed by the
    # packaged TensorRT and source-built Triton C APIs.
    #
    # That distinction is what puts isaac_ros_foundationpose in reach: TensorRT appears
    # in its manifest only as an <exec_depend>, never as a <depend>, so nothing about
    # TensorRT runs at configure time. See DROP_DEPS for what that costs at runtime.
    ("ros-jazzy-isaac-ros-tensor-proc", "isaac_ros_dnn_inference", "isaac_ros_tensor_proc"),
    ("ros-jazzy-isaac-ros-dnn-image-encoder", "isaac_ros_dnn_inference", "isaac_ros_dnn_image_encoder"),
    # Pure CPU pose filtering -- six composable nodes over vision_msgs and tf2, with no
    # Isaac dependency beyond isaac_ros_common's cmake. The one package in
    # isaac_ros_pose_estimation that never needed anything from the DNN stack.
    ("ros-jazzy-isaac-ros-pose-proc", "isaac_ros_pose_estimation", "isaac_ros_pose_proc"),
    # Asset-download scripts. Nothing to compile, but it is a <depend> of
    # isaac_ros_foundationpose, so ament_auto_find_build_dependencies needs it present at
    # configure time.
    ("ros-jazzy-isaac-ros-foundationpose-models-install", "isaac_ros_pose_estimation",
     "isaac_ros_foundationpose_models_install"),
    ("ros-jazzy-isaac-ros-foundationpose", "isaac_ros_pose_estimation", "isaac_ros_foundationpose"),
    # The last two looked blocked on TensorRT and Triton, and are not. Neither includes a
    # single header from isaac_ros_tensor_rt or isaac_ros_triton: each builds an
    # OpenCV-and-Eigen decoder node that takes a TensorList off a topic and emits poses,
    # and the inference is a separate composable node the launch file puts beside it. The
    # manifests declare those backends as <depend> rather than <exec_depend>, and
    # ament_auto_find_build_dependencies turns every <depend> into a REQUIRED
    # find_package -- so an over-declaration, not a real dependency, is the whole blocker.
    # PATCHES demotes them; see the patch commit messages, both prepared for upstream.
    ("ros-jazzy-isaac-ros-dope", "isaac_ros_pose_estimation", "isaac_ros_dope"),
    ("ros-jazzy-isaac-ros-centerpose", "isaac_ros_pose_estimation", "isaac_ros_centerpose"),
    # --- object detection ---------------------------------------------------------
    #
    # All eight packages in isaac_ros_object_detection, and this repo needed no manifest
    # patches at all: unlike isaac_ros_dope and isaac_ros_centerpose, every package here
    # already declares its inference backend the right way. isaac_ros_rtdetr,
    # isaac_ros_yolov8 and isaac_ros_grounding_dino carry
    # <exec_depend>isaac_ros_tensor_rt, so nothing about TensorRT runs at configure time,
    # and isaac_ros_detectnet has isaac_ros_triton as a <test_depend> only. packages.json
    # still marks four of them `tensorrt` because it reads manifests without distinguishing
    # the dependency kind -- see the note in README.md.
    #
    # isaac_ros_nitros_bridge_interfaces is the one dependency that had to come along. It
    # lives in isaac_ros_common rather than isaac_ros_nitros_bridge despite the name, and
    # is a plain rosidl package, so it costs nothing.
    ("ros-jazzy-isaac-ros-nitros-bridge-interfaces", "isaac_ros_common", "isaac_ros_nitros_bridge_interfaces"),
    ("ros-jazzy-isaac-ros-grounding-dino-interfaces", "isaac_ros_object_detection", "isaac_ros_grounding_dino_interfaces"),
    # Asset scripts. All three hit the install_isaac_ros_asset() rewrite -- see detect().
    ("ros-jazzy-isaac-ros-rtdetr-models-install", "isaac_ros_object_detection", "isaac_ros_rtdetr_models_install"),
    ("ros-jazzy-isaac-ros-grounding-dino-models-install", "isaac_ros_object_detection", "isaac_ros_grounding_dino_models_install"),
    # DetectNet needs no DNN package at all: its Triton dependency is a <test_depend>.
    ("ros-jazzy-isaac-ros-detectnet", "isaac_ros_object_detection", "isaac_ros_detectnet"),
    # Depends on isaac_ros_detectnet, so it follows it.
    ("ros-jazzy-isaac-ros-peoplenet-models-install", "isaac_ros_object_detection", "isaac_ros_peoplenet_models_install"),
    ("ros-jazzy-isaac-ros-yolov8", "isaac_ros_object_detection", "isaac_ros_yolov8"),
    ("ros-jazzy-isaac-ros-rtdetr", "isaac_ros_object_detection", "isaac_ros_rtdetr"),
    ("ros-jazzy-isaac-ros-grounding-dino", "isaac_ros_object_detection", "isaac_ros_grounding_dino"),
    # --- the TensorRT inference node -----------------------------------------------
    #
    # The backend every DNN pipeline above actually defaults to. linux-64 uses
    # conda-forge TensorRT 11 through recipes/tensorrt-conda-forge; Jetson keeps the
    # native NVIDIA payload in recipes/tensorrt.
    #
    # Its Triton sibling used to be blocked by a private-artifactory FetchContent URL;
    # recipes/triton-server plus the patch below replace that hidden input.
    ("ros-jazzy-isaac-ros-tensor-rt", "isaac_ros_dnn_inference", "isaac_ros_tensor_rt"),
    # The public x86_64 server tarball is missing upstream, but recipes/triton-server
    # now builds the C API from source. A small patch replaces FetchContent with its
    # exported CMake target.
    ("ros-jazzy-isaac-ros-triton", "isaac_ros_dnn_inference", "isaac_ros_triton"),
    # --- the previously unattempted packages, first batch -------------------------
    #
    # Everything here is in a repo already cached, needs no new REPOS entry, and follows a
    # pattern already validated: rosidl interfaces, NITROS type adapters, and the image
    # pipeline. gxf_isaac_utils is the one GXF extension in this batch that compiles its own
    # pipeline. None of the nine unbuilt GXF extensions is here, and gxf_isaac_utils is the
    # instructive one: unlike the other eight it is not an INTERFACE target, it compiles five
    # of its own .cpp files -- so it looks source-buildable. It also *links* a prebuilt
    # lib/gxf_x86_64_cuda_13_0/libgxf_utils.so, which in the release tarball is a 132-byte
    # git-lfs pointer, so the link fails with
    #
    #   ld: .../libgxf_utils.so:1: syntax error
    #
    # -- text being read as an object file. Compiling its sources cannot help when the blob
    # they link against is not published, so all nine go through gen_repack.py. This is the
    ("ros-jazzy-isaac-ros-apriltag-interfaces", "isaac_ros_common", "isaac_ros_apriltag_interfaces"),
    ("ros-jazzy-isaac-ros-nova-interfaces", "isaac_ros_common", "isaac_ros_nova_interfaces"),
    ("ros-jazzy-isaac-ros-test-cmake", "isaac_ros_common", "isaac_ros_test_cmake"),
    ("ros-jazzy-isaac-ros-nitros-bridge-ros2", "isaac_ros_nitros", "isaac_ros_nitros_bridge/isaac_ros_nitros_bridge_ros2"),
    ("ros-jazzy-isaac-ros-stereo-image-proc", "isaac_ros_image_pipeline", "isaac_ros_stereo_image_proc"),
    ("ros-jazzy-isaac-ros-depth-image-proc", "isaac_ros_image_pipeline", "isaac_ros_depth_image_proc"),
    ("ros-jazzy-isaac-ros-image-pipeline", "isaac_ros_image_pipeline", "isaac_ros_image_pipeline"),
    # --- mapping and localization ---------------------------------------------------
    #
    # Two of this repo's four packages. The other two -- isaac_mapping_ros and
    # isaac_ros_visual_global_localization -- both <depend> on isaac_ros_visual_mapping, and
    # isaac_mapping_ros additionally does find_package(isaac_ros_visual_mapping REQUIRED)
    # plus five ament_target_dependencies() against it. No such package exists at v4.5-0 in
    # this repo or anywhere else in the 4.5 source set, so neither can configure. That is a
    # dangling dependency upstream rather than anything missing here -- ISSUES.md #22.
    ("ros-jazzy-isaac-ros-pointcloud-utils", "isaac_ros_mapping_and_localization", "isaac_ros_pointcloud_utils"),
    ("ros-jazzy-isaac-ros-occupancy-grid-localizer", "isaac_ros_mapping_and_localization", "isaac_ros_occupancy_grid_localizer"),
    # --- nvblox --------------------------------------------------------------------
    #
    # nvblox_msgs was already built for cuMotion; this is the rest of the repo. Leaves
    # first, the metapackage last. nvblox_test is absent because it requires the test
    # datasets as build inputs; nvblox_examples_bringup is included with its unavailable
    # optional Triton launch backend omitted from runtime dependencies below.
    ("ros-jazzy-nvblox-ros-common", "isaac_ros_nvblox", "nvblox_ros_common"),
    ("ros-jazzy-nvblox-ros-python-utils", "isaac_ros_nvblox", "nvblox_ros_python_utils"),
    ("ros-jazzy-nvblox-test-data", "isaac_ros_nvblox", "nvblox_test_data"),
    ("ros-jazzy-nvblox-message-adapters", "isaac_ros_nvblox", "nvblox_message_adapters"),
    ("ros-jazzy-nvblox-nav2", "isaac_ros_nvblox", "nvblox_nav2"),
    ("ros-jazzy-nvblox-rviz-plugin", "isaac_ros_nvblox", "nvblox_rviz_plugin"),
    ("ros-jazzy-realsense-splitter", "isaac_ros_nvblox", "nvblox_examples/realsense_splitter"),
    ("ros-jazzy-multi-realsense-emitter-synchronizer", "isaac_ros_nvblox", "nvblox_examples/multi_realsense_emitter_synchronizer"),
    ("ros-jazzy-semantic-label-conversion", "isaac_ros_nvblox", "nvblox_examples/semantic_label_conversion"),
    ("ros-jazzy-nvblox-image-padding", "isaac_ros_nvblox", "nvblox_examples/nvblox_image_padding"),
    ("ros-jazzy-cuvslam-vendor", "isaac_ros_nitros", "cuvslam_vendor"),
    ("ros-jazzy-isaac-ros-cuvslam", "isaac_ros_visual_slam", "isaac_ros_cuvslam"),
    ("ros-jazzy-nvblox-examples-bringup", "isaac_ros_nvblox", "nvblox_examples/nvblox_examples_bringup"),
    ("ros-jazzy-nvblox-ros", "isaac_ros_nvblox", "nvblox_ros"),
    ("ros-jazzy-isaac-ros-nvblox", "isaac_ros_nvblox", "isaac_ros_nvblox"),
    # --- eight more repos, in dependency order -------------------------------------
    #
    # Ordered by hand from packages.json's internal_closure, so a sequential build
    # resolves: every entry below has all of its Isaac dependencies above it.
    #
    # isaac_ros_apriltag is the one that should have been here from the start. cuAprilTag
    # runs in demo/ and has since the first week, but only the *interfaces* package was
    # ever packaged -- the node itself was reached through the deb overlay and never got a
    # recipe. Its whole closure (nitros, managed_nitros, the image type adapters,
    # isaac_ros_image_proc) has been built for weeks.
    ("ros-jazzy-cuapriltags-vendor", "isaac_ros_nitros", "cuapriltags_vendor"),
    ("ros-jazzy-isaac-ros-apriltag", "isaac_ros_apriltag", "isaac_ros_apriltag"),
    # The encoder, beside the decoder that was built long ago. Same repo, same NVENC/NVDEC
    # family, and it inherits the CUDA-header fix README.md describes for the decoder.
    ("ros-jazzy-isaac-ros-h264-encoder", "isaac_ros_compression", "isaac_ros_h264_encoder"),
    ("ros-jazzy-isaac-teleop-core", "isaac_ros_teleop", "isaac_teleop_core"),
    ("ros-jazzy-isaac-ros-teleop", "isaac_ros_teleop", "isaac_ros_teleop"),
    # --- stereo depth: ESS and FoundationStereo -----------------------------------
    #
    # packages.json marks three of these five `needs_new_ros_pkg`, which resolved to
    # TensorRT. That is now packaged, and the pattern is the one pose/ and detect/ already
    # established: the decoder and the two model-install packages carry no inference
    # engine at all, and ESS and FoundationStereo reach it through a separate composable
    # node rather than a header. Model-install packages come first because both consumers
    # <depend> on them, and ament_auto_find_build_dependencies() makes that a REQUIRED
    # find_package -- the same ordering constraint isaac_ros_foundationpose had.
    ("ros-jazzy-isaac-ros-dnn-stereo-decoder", "isaac_ros_dnn_stereo_depth", "isaac_ros_dnn_stereo_decoder"),
    ("ros-jazzy-isaac-ros-ess-models-install", "isaac_ros_dnn_stereo_depth", "isaac_ros_ess_models_install"),
    ("ros-jazzy-isaac-ros-foundationstereo-models-install", "isaac_ros_dnn_stereo_depth",
     "isaac_ros_foundationstereo_models_install"),
    ("ros-jazzy-isaac-ros-ess", "isaac_ros_dnn_stereo_depth", "isaac_ros_ess"),
    ("ros-jazzy-isaac-ros-foundationstereo", "isaac_ros_dnn_stereo_depth", "isaac_ros_foundationstereo"),
    # --- image segmentation: the Triton label is wrong here too --------------------
    #
    # packages.json marks five of these six `triton`, and this is the third repo in a row
    # where that label is a manifest-reading artefact rather than a dependency. Measured
    # the same way as detect/: grep for nvinfer, tritonserver or an isaac_ros_triton
    # include across every .cpp/.hpp/.cu/.h in all six packages returns **zero** hits. The
    # manifests declare it as <exec_depend> (unet, segformer) or <test_depend>
    # (segment_anything, segment_anything2), and ament_auto_find_build_dependencies() sees
    # neither kind -- so nothing about Triton runs at configure time.
    #
    # Triton is packaged now; these packages remain independently installable because
    # their manifests correctly describe it as an optional runtime backend.
    ("ros-jazzy-isaac-ros-unet-kernels", "isaac_ros_image_segmentation", "isaac_ros_unet_kernels"),
    ("ros-jazzy-isaac-ros-unet", "isaac_ros_image_segmentation", "isaac_ros_unet"),
    ("ros-jazzy-isaac-ros-peoplesemseg-models-install", "isaac_ros_image_segmentation",
     "isaac_ros_peoplesemseg_models_install"),
    ("ros-jazzy-isaac-ros-segformer", "isaac_ros_image_segmentation", "isaac_ros_segformer"),
    ("ros-jazzy-isaac-ros-segment-anything", "isaac_ros_image_segmentation", "isaac_ros_segment_anything"),
    ("ros-jazzy-isaac-ros-segment-anything2", "isaac_ros_image_segmentation", "isaac_ros_segment_anything2"),
    # --- the rest of cuMotion ------------------------------------------------------
    #
    # isaac_ros_cumotion_controllers is not here: it needs isaac_ros_inverse_dynamics,
    # which lives in isaac_ros_deploy and is the only thing standing between this repo and
    # a complete isaac_ros_cumotion.
    ("ros-jazzy-isaac-ros-cumotion-examples", "isaac_ros_cumotion", "isaac_ros_cumotion_examples"),
    ("ros-jazzy-isaac-ros-cumotion-robot-segmenter", "isaac_ros_cumotion", "isaac_ros_cumotion_robot_segmenter"),
    # --- small python tool repos ---------------------------------------------------
    ("ros-jazzy-isaac-ros-tensor-inspector", "isaac_ros_data_tools", "isaac_ros_tensor_inspector"),
    # Only the service interfaces, which are a plain rosidl package.
    #
    # isaac_ros_jetson_stats itself is left out, and not because it is Jetson-only: it
    # does `import jtop`, which is the jetson-stats distribution on PyPI, and conda-forge
    # has no such package. A recipe would generate cleanly and then fail to solve. It is
    # the one genuinely missing dependency found in this whole pass, and it is worth
    # little -- jtop reads tegrastats, so the node cannot function on x86_64 anyway.
    ("ros-jazzy-isaac-ros-jetson-stats-services", "isaac_ros_jetson", "isaac_ros_jetson_stats_services"),
    # --- the example launch packages -----------------------------------------------
    #
    # Four ament_python packages that are launch-file collections. isaac_ros_realsense,
    # _usb_cam and _zed each want a camera driver at *runtime* that RoboStack does not
    # carry; none of that is a build dependency, so the packages themselves are cheap.
    ("ros-jazzy-isaac-ros-examples", "isaac_ros_examples", "isaac_ros_examples"),
    ("ros-jazzy-isaac-ros-realsense", "isaac_ros_examples", "isaac_ros_realsense"),
    ("ros-jazzy-isaac-ros-usb-cam", "isaac_ros_examples", "isaac_ros_usb_cam"),
    ("ros-jazzy-isaac-ros-zed", "isaac_ros_examples", "isaac_ros_zed"),
    # --- isaac_ros_cloud_control, all thirteen -------------------------------------
    #
    # The largest untouched repo with no recorded blocker on any of its packages, and the
    # VDA5050 fleet-interface layer: MQTT bridge, order/state message set, action handlers
    # and the mission client on top. Five ament_python packages, eight ament_cmake, and
    # nothing NVIDIA-proprietary underneath -- no GXF, no NITROS type adapter, no CUDA.
    # The order below is the topological one; vda5050_msgs has to lead because five of the
    # others generate against it.
    ("ros-jazzy-vda5050-msgs", "isaac_ros_cloud_control", "vda5050_msgs"),
    ("ros-jazzy-isaac-ros-cloud-control-interface", "isaac_ros_cloud_control", "isaac_ros_cloud_control_interface"),
    ("ros-jazzy-isaac-ros-scene-recorder-interface", "isaac_ros_cloud_control", "isaac_ros_scene_recorder_interface"),
    ("ros-jazzy-isaac-ros-json-info-generator", "isaac_ros_cloud_control", "isaac_ros_json_info_generator"),
    ("ros-jazzy-isaac-ros-mega-controller", "isaac_ros_cloud_control", "isaac_ros_mega_controller"),
    ("ros-jazzy-isaac-ros-mega-node-monitor", "isaac_ros_cloud_control", "isaac_ros_mega_node_monitor"),
    ("ros-jazzy-isaac-ros-mqtt-bridge", "isaac_ros_cloud_control", "isaac_ros_mqtt_bridge"),
    ("ros-jazzy-vda5050-action-handler", "isaac_ros_cloud_control", "vda5050_action_handler"),
    ("ros-jazzy-isaac-ros-vda5050-client", "isaac_ros_cloud_control", "isaac_ros_vda5050_client"),
    ("ros-jazzy-isaac-ros-scene-recorder", "isaac_ros_cloud_control", "isaac_ros_scene_recorder"),
    ("ros-jazzy-vda5050-action-handler-plugins", "isaac_ros_cloud_control", "vda5050_action_handler_plugins"),
    ("ros-jazzy-isaac-ros-vda5050-client-bringup", "isaac_ros_cloud_control", "isaac_ros_vda5050_client_bringup"),
    ("ros-jazzy-isaac-ros-mission-client", "isaac_ros_cloud_control", "isaac_ros_mission_client"),
    ("ros-jazzy-isaac-ros-humanoid-task-server", "isaac_ros_cloud_control", "isaac_ros_humanoid_task_server"),
    # --- isaac_ros_deploy, and what it unblocks -------------------------------------
    #
    # Ordered by a topological sort over the five repos' package.xml files rather than by
    # hand. isaac_ros_inverse_dynamics is the interesting one: it is the single dependency
    # that has been keeping isaac_ros_cumotion_controllers -- and with it a complete
    # isaac_ros_cumotion -- out of reach.
    #
    # packages.json marks four of these seven `triton`, which is a transitive label rather
    # than a direct one: only isaac_ros_deploy_converters and _bringup name
    # isaac_ros_triton at all, both as <exec_depend>. DROP_DEPS handles those two.
    ("ros-jazzy-isaac-deploy-core", "isaac_ros_deploy", "isaac_deploy/isaac_deploy_core"),
    ("ros-jazzy-isaac-ros-deploy-interfaces", "isaac_ros_deploy", "isaac_deploy/isaac_ros_deploy_interfaces"),
    ("ros-jazzy-isaac-ros-inverse-dynamics", "isaac_ros_deploy", "isaac_deploy/isaac_ros_inverse_dynamics"),
    ("ros-jazzy-isaac-ros-deploy-converters", "isaac_ros_deploy", "isaac_deploy/isaac_ros_deploy_converters"),
    ("ros-jazzy-isaac-ros-deploy-ros2-control", "isaac_ros_deploy", "isaac_deploy/isaac_ros_deploy_ros2_control"),
    ("ros-jazzy-isaac-ros-deploy-bringup", "isaac_ros_deploy", "isaac_deploy/isaac_ros_deploy_bringup"),
    ("ros-jazzy-isaac-ros-deploy", "isaac_ros_deploy", "isaac_ros_deploy"),
    ("ros-jazzy-isaac-ros-deploy-reference-applications", "isaac_ros_deploy",
     "isaac_deploy/isaac_ros_deploy_reference_applications"),
    # The last isaac_ros_cumotion package, reachable now that inverse_dynamics is above it.
    ("ros-jazzy-isaac-ros-cumotion-controllers", "isaac_ros_cumotion", "isaac_ros_cumotion_controllers"),
    # --- learned policies, robots, physical AI --------------------------------------
    #
    # Every external dependency of these three repos resolves from robostack-jazzy --
    # including mujoco_ros2_control, pinocchio, foxglove_bridge and realsense2_camera,
    # each of which looked like a likely gap and is not.
    #
    # unitree_g1_bridge uses only Unitree's public ROS messages, not the native SDK.
    # Package that interface directly from unitree_ros2, then build the Python bridge.
    ("ros-jazzy-unitree-api", "unitree_ros2", "cyclonedds_ws/src/unitree/unitree_api"),
    ("ros-jazzy-isaac-ros-agile-unitree-g1", "isaac_ros_learned_policies", "isaac_ros_agile_unitree_g1"),
    ("ros-jazzy-isaac-ros-franka-fr3-reach", "isaac_ros_learned_policies", "isaac_ros_franka_fr3_reach"),
    ("ros-jazzy-isaac-ros-robots-tools", "isaac_ros_robots", "isaac_ros_robots_tools"),
    ("ros-jazzy-unitree-g1-description", "isaac_ros_robots", "unitree_g1/unitree_g1_description"),
    ("ros-jazzy-unitree-hg-ros2-control", "isaac_ros_robots", "unitree_hg/unitree_hg_ros2_control"),
    ("ros-jazzy-unitree-g1-bringup", "isaac_ros_robots", "unitree_g1/unitree_g1_bringup"),
    ("ros-jazzy-isaac-ros-data-flywheel", "isaac_ros_physical_ai", "isaac_ros_data_flywheel"),
    # isaac_ros_sipl_camera is deliberately absent on linux-64. Its CMakeLists returns
    # before ament_package() unless CMAKE_SYSTEM_PROCESSOR is aarch64, so an x86_64 build
    # installs zero files. SIPL is NVIDIA DRIVE's ARM64-only camera SDK; publishing an
    # empty package here would falsely claim that the node exists.
    # The Thor/RealSense mounting rig is different: it is platform-independent URDF and
    # mesh data from a separately documented, tagged Isaac ROS 5.0 repository.
    ("ros-jazzy-thor-devkit-realsense-rig-description", "sensor_mounting_rig",
     "thor_devkit_realsense_rig_description"),
    # --- the benchmark suite: 25 of its 29 packages --------------------------------
    #
    # ros2_benchmark, isaac_ros_benchmark and isaac_ros_image_proc_benchmark have been built
    # since bench/ (which reports 2495 fps through ResizeNode). What was never packaged is
    # the other 28 per-node benchmark packages -- one per pipeline -- and they were out of
    # reach for a plain reason: each one <depend>s on the node it measures, and most of those
    # nodes did not exist here yet. ESS, FoundationStereo, U-Net, SegFormer, apriltag, the
    # h264 encoder and cuMotion's controllers all landed above, so the suite came with them.
    #
    # Order is a topological sort over the repo's package.xml files: isaac_ros_moveit_benchmark
    # before the four robot benchmarks, and the two ur5 description/config packages before the
    # ur5 pair that consumes them.
    #
    # The final four benchmarks require isaac_ros_triton as a real <depend>. They become
    # buildable now that the packaged Triton core replaces NVIDIA's private tarball.
    ("ros-jazzy-isaac-ros-apriltag-benchmark", "isaac_ros_benchmark", "benchmarks/isaac_ros_apriltag_benchmark"),
    ("ros-jazzy-isaac-ros-centerpose-benchmark", "isaac_ros_benchmark", "benchmarks/isaac_ros_centerpose_benchmark"),
    ("ros-jazzy-isaac-ros-dnn-image-encoder-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_dnn_image_encoder_benchmark"),
    ("ros-jazzy-isaac-ros-dope-benchmark", "isaac_ros_benchmark", "benchmarks/isaac_ros_dope_benchmark"),
    ("ros-jazzy-isaac-ros-ess-benchmark", "isaac_ros_benchmark", "benchmarks/isaac_ros_ess_benchmark"),
    ("ros-jazzy-isaac-ros-foundationpose-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_foundationpose_benchmark"),
    ("ros-jazzy-isaac-ros-foundationstereo-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_foundationstereo_benchmark"),
    ("ros-jazzy-isaac-ros-grounding-dino-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_grounding_dino_benchmark"),
    ("ros-jazzy-isaac-ros-h264-decoder-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_h264_decoder_benchmark"),
    ("ros-jazzy-isaac-ros-h264-encoder-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_h264_encoder_benchmark"),
    ("ros-jazzy-isaac-ros-occupancy-grid-localizer-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_occupancy_grid_localizer_benchmark"),
    ("ros-jazzy-isaac-ros-rtdetr-benchmark", "isaac_ros_benchmark", "benchmarks/isaac_ros_rtdetr_benchmark"),
    ("ros-jazzy-isaac-ros-segformer-benchmark", "isaac_ros_benchmark", "benchmarks/isaac_ros_segformer_benchmark"),
    ("ros-jazzy-isaac-ros-detectnet-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_detectnet_benchmark"),
    ("ros-jazzy-isaac-ros-segment-anything-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_segment_anything_benchmark"),
    ("ros-jazzy-isaac-ros-segment-anything2-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_segment_anything2_benchmark"),
    ("ros-jazzy-isaac-ros-triton-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_triton_benchmark"),
    ("ros-jazzy-isaac-ros-stereo-image-proc-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_stereo_image_proc_benchmark"),
    ("ros-jazzy-isaac-ros-tensor-rt-benchmark", "isaac_ros_benchmark", "benchmarks/isaac_ros_tensor_rt_benchmark"),
    ("ros-jazzy-isaac-ros-unet-benchmark", "isaac_ros_benchmark", "benchmarks/isaac_ros_unet_benchmark"),
    # The MoveIt planning benchmarks: the harness, then the robot descriptions, then the four
    # planner comparisons that use them. isaac_ros_franka_* and isaac_ros_ur5_* each pit
    # cuMotion against OMPL on the same scene.
    ("ros-jazzy-isaac-ros-moveit-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_moveit_benchmark/isaac_ros_moveit_benchmark"),
    ("ros-jazzy-ur5-gripper-moveit-config", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_moveit_benchmark/robot_configs/ur5_gripper_moveit_config"),
    ("ros-jazzy-ur5-robotiq-85-description", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_moveit_benchmark/robot_descriptions/ur5_robotiq_85_description"),
    ("ros-jazzy-isaac-ros-franka-cumotion-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_moveit_benchmark/isaac_ros_moveit_robot_benchmark/franka/isaac_ros_franka_cumotion_benchmark"),
    ("ros-jazzy-isaac-ros-franka-ompl-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_moveit_benchmark/isaac_ros_moveit_robot_benchmark/franka/isaac_ros_franka_ompl_benchmark"),
    ("ros-jazzy-isaac-ros-ur5-cumotion-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_moveit_benchmark/isaac_ros_moveit_robot_benchmark/ur5/isaac_ros_ur5_cumotion_benchmark"),
    ("ros-jazzy-isaac-ros-ur5-ompl-benchmark", "isaac_ros_benchmark",
     "benchmarks/isaac_ros_moveit_benchmark/isaac_ros_moveit_robot_benchmark/ur5/isaac_ros_ur5_ompl_benchmark"),
    # Complete the manipulation stack after every package used by its reference launch
    # graph is available. The asset package installs the on-target model setup utility;
    # it does not download models during this build because BUILD_TESTING is disabled.
]

DEP_TAG = re.compile(
    r"<(build_depend|buildtool_depend|build_export_depend|exec_depend|depend"
    r"|buildtool_export_depend|test_depend)([^>]*)>([^<]+)<")

# Dependencies that only matter for linting or tests.
TEST_ONLY = {
    "ament_lint_auto", "ament_lint_common", "ament_cmake_gtest", "ament_cmake_pytest",
    "ament_flake8", "ament_pep257", "ament_copyright", "ament_cmake_copyright",
    "ament_cmake_lint_cmake", "launch_testing", "launch_testing_ament_cmake",
    "launch_testing_ros", "python3-pytest", "isaac_ros_test", "isaac_ros_test_cmake",
    "python3-flaky",
}

# Extra host requirements keyed on what the CMakeLists actually does.
TRAIT_DEPS = {
    # The CUDA *compiler* is not listed here -- it belongs in build:, and is added as
    # ${{ compiler('cuda') }} below. Only the libraries and headers go in host.
    "cuda":   ["cuda-version 13.*", "cuda-cudart-dev", "cuda-nvtx-dev"],
    # Unpinned, which means eigen 5 today -- and that is a measured decision.
    #
    # cuMotion's API is Eigen-typed: libcumotion.so takes and returns Eigen::VectorXd,
    # Vector3d and Quaterniond, and NVIDIA compiled it against Eigen 3. Its
    # cumotionConfig.cmake said so with `find_dependency(Eigen3 3.3)`, which eigen's
    # SameMajorVersion rule turns into a hard rejection of the eigen 5.0.1 robostack-jazzy
    # now uses -- and taking that at face value costs isaac_ros_cumotion_moveit,
    # isaac_ros_manipulation_gear_assembly and isaac_ros_manipulation_flexiv_driver_utils.
    #
    # The constraint is stricter than the ABI. What crosses the boundary is
    # Eigen::Matrix<double,3,1,0,3,1> and Eigen::Quaternion<double,0> by const reference:
    # identical template signature (hence the symbols link) and identical layout in both
    # versions. recipes/ros-jazzy-isaac-ros-nitros/build.sh removes the floor from the
    # installed config, and manip/ik.sh + manip/fk_check.py check the consequence -- cuMotion
    # returns the same 26 IK solutions and lands 0.000 mm from the requested pose. See
    # ISSUES.md #13.
    "eigen":  ["eigen"],
    "vpi":    ["vpi"],
    "yamlcpp": ["yaml-cpp"],
    "rosidl": ["ros-jazzy-rosidl-default-generators", "ros-jazzy-rosidl-default-runtime"],
    "python": ["python", "pyyaml"],
    "ament_auto": ["ros-jazzy-ament-cmake-auto"],
    "opencv": ["libopencv 4.13.*"],
    # Pinned, and both bounds are load-bearing. conda-forge's libcvcuda-dev 0.16
    # ships lib/cmake/{cvcuda,nvcv_types}/*-config.cmake; 0.17 makes DataType's
    # native conversion explicit, while the adapted Isaac headers require 0.16.
    # The 0.14 deb repack this repo used before it (still sitting in some output/ trees) ships
    # only headers and two .so symlinks. isaac_ros_foundationpose is the first package
    # here to call find_package(nvcv_types REQUIRED) rather than naming the libraries
    # directly, so with the older one in a local channel -- which outranks conda-forge --
    # it fails at configure with "Could not find a package configuration file provided
    # by nvcv_types". Say the version, so an unindexed leftover cannot win.
    "cvcuda": ["libcvcuda >=0.16,<0.17", "libcvcuda-dev >=0.16,<0.17"],
    # No extra requirements -- these two rewrite a CMake call rather than adding a
    # dependency. Present because emit() indexes TRAIT_DEPS by every detected trait.
    "asset": [],
    "eigenfloor": [],
}


# Dependencies a package needs but does not declare. Keyed by conda package name.
#
# Every entry here is an upstream manifest bug, not a packaging preference: the build
# fails without it. Kept separate from TRAIT_DEPS because these are not detectable from
# the CMakeLists by pattern -- they come from ament_target_dependencies() naming a
# package that ament_auto_find_build_dependencies() was never told to find.
EXTRA_DEPS = {
    # This dependency is conditional on ROS_DISTRO != lyrical. The generic parser skips
    # conditional manifest entries; Isaac Forge targets Jazzy, whose CMake requires it.
    "ros-jazzy-isaac-deploy-core": ["ros-jazzy-tl-expected"],
    # Upstream's manifest omits rosidl_buffer although CMake requires it directly.
    "ros-jazzy-rosidl-buffer-backend-registry": ["ros-jazzy-rosidl-buffer"],
    # reshape_node calls
    #   ament_target_dependencies(reshape_node rclcpp rclcpp_components isaac_ros_cvcuda_utils)
    # and package.xml never mentions isaac_ros_cvcuda_utils. ament_target_dependencies
    # hard-errors on a package find_package() has not located, so configure fails outright
    # rather than degrading. See ISSUES.md.
    "ros-jazzy-isaac-ros-tensor-proc": ["ros-jazzy-isaac-ros-cvcuda-utils"],
}

# Declared dependencies deliberately left out, with the reason. Keyed by conda package
# name -> {rosdep key: why}.
#
# This is only ever for <exec_depend>s that name a *sibling demo pipeline* rather than
# something the package's own code loads. A run dependency on an unbuildable package makes
# the environment unsolvable, so keeping the manifest verbatim would cost the package
# itself for no gain -- and everything dropped here is reachable by installing it
# alongside once it exists.
DROP_DEPS = {
    # ament_cmake_ros_core is newer than Jazzy; these targets only use it to select C++20,
    # which the accompanying patches request directly from CMake.
    "ros-jazzy-rosidl-buffer": {
        "ament_cmake_ros_core": "replaced by target_compile_features(cxx_std_20)",
    },
    "ros-jazzy-rosidl-buffer-backend-registry": {
        "ament_cmake_ros_core": "replaced by target_compile_features(cxx_std_20)",
    },
    # A Python bridge generates no interfaces. Upstream carries this as build metadata,
    # but keeping it would unnecessarily install a code generator at runtime.
    "ros-jazzy-unitree-g1-bridge": {
        "rosidl_generator_dds_idl": "build-only generator unused by this ament_python package",
    },
    "ros-jazzy-isaac-ros-foundationpose": {
        # The three inference/perception stages of NVIDIA's reference launch graph, all
        # of which need TensorRT. The FoundationPose node consumes their *topics*; it
        # neither links nor dlopens them, and its own two engine files are loaded by a
        # separate isaac_ros_tensor_rt node in the same launch file.
        "isaac_ros_tensor_rt": "needs TensorRT; a separate node in the launch graph",
        "isaac_ros_rtdetr": "needs TensorRT; supplies the detection2_d input topic",
        "isaac_ros_dnn_stereo_decoder": "needs TensorRT; ESS depth, one of two depth options",
        # Not blocked, just not built here yet -- and equally launch-only.
        "isaac_ros_stereo_image_proc": "launch-only; the other depth option",
        "isaac_ros_nitros_topic_tools": "launch-only topic throttling",
        # rviz2 resolves fine from robostack-jazzy, but it is a visualization tool for
        # the demo launch files, and making a composable-node library drag in Qt to
        # install is not a trade worth taking.
        "rviz2": "launch-only visualization",
    },
    # Demoted to <exec_depend> by this package's patch, which is the correct manifest but
    # still leaves an unbuildable run dep. The decoder does not load them; the launch file
    # composes them as separate nodes, so installing them alongside once TensorRT exists is
    # all that is needed.
    "ros-jazzy-isaac-ros-dope": {
        "isaac_ros_tensor_rt": "needs TensorRT; a separate node in the launch graph",
    },
    "ros-jazzy-isaac-ros-centerpose": {
        "isaac_ros_tensor_rt": "needs TensorRT; one of two interchangeable backends",
        "isaac_ros_triton": "needs Triton; the other backend",
    },
    # isaac_ros_image_segmentation. All four declare Triton correctly, as
    # <exec_depend> -- so it never reaches configure and none of the four contains a
    # single Triton or TensorRT reference in its own sources (checked across every
    # .cpp/.hpp/.cu/.h: zero hits). What it does reach is `run`, and there an unbuildable
    # package makes the environment unsolvable, which is the whole reason for this table.
    #
    # Triton is unobtainable for the reason in ISSUES.md #21 -- isaac_ros_triton defaults
    # x86_64 to a tarball on an internal NVIDIA host -- and unlike the TensorRT cases
    # above there is no prospect of packaging it. Each of these four ships a TensorRT
    # launch path as well, and recipes/tensorrt supplies that, so what is lost is the
    # Triton variant of the pipeline rather than the node.
    "ros-jazzy-isaac-ros-unet": {
        "isaac_ros_triton": "needs Triton (ISSUES.md #21); one of two backends, TensorRT is the other",
    },
    "ros-jazzy-isaac-ros-segformer": {
        "isaac_ros_triton": "needs Triton (ISSUES.md #21); one of two backends, TensorRT is the other",
    },
    "ros-jazzy-isaac-ros-segment-anything": {
        "isaac_ros_triton": "needs Triton (ISSUES.md #21); one of two backends, TensorRT is the other",
    },
    "ros-jazzy-isaac-ros-segment-anything2": {
        "isaac_ros_triton": "needs Triton (ISSUES.md #21); one of two backends, TensorRT is the other",
    },
    # isaac_ros_deploy. Both declare Triton as <exec_depend>, so it never reaches
    # configure -- only `run`, where it would make the environment unsolvable.
    "ros-jazzy-isaac-ros-deploy-converters": {
        "isaac_ros_triton": "needs Triton (ISSUES.md #21); an inference node in the launch graph",
    },
    "ros-jazzy-isaac-ros-deploy-bringup": {
        "isaac_ros_triton": "needs Triton (ISSUES.md #21); an inference node in the launch graph",
    },
    # Already <exec_depend> upstream, so these cost nothing at build time -- they only
    # have to stay out of `run`, where an unbuildable package makes the environment
    # unsolvable. isaac_ros_dnn_image_encoder is deliberately NOT dropped: it is built
    # here now, so the declared dependency can be honoured.
    "ros-jazzy-isaac-ros-rtdetr": {
        "isaac_ros_tensor_rt": "needs TensorRT; the inference node in the launch graph",
    },
    "ros-jazzy-isaac-ros-yolov8": {
        "isaac_ros_tensor_rt": "needs TensorRT; the inference node in the launch graph",
    },
    "ros-jazzy-isaac-ros-grounding-dino": {
        "isaac_ros_tensor_rt": "needs TensorRT; the inference node in the launch graph",
    },
    # Optional segmentation launch backend. The package also ships a fully packaged
    # TensorRT path, and does not link or import this separate ROS node.
    "ros-jazzy-nvblox-examples-bringup": {
        "isaac_ros_triton": "needs Triton (ISSUES.md #21); optional launch backend",
    },
}

# Additional source entries a package needs beyond its repo tarball, keyed by conda package
# name. Each value is (url, sha256, target_directory-relative-to-src).
#
# These exist because a GitHub release tarball is not a git clone: it contains no submodule
# content. isaac_ros_nvblox declares
#
#     [submodule "nvblox_ros/nvblox_core"]
#         url = https://github.com/nvidia-isaac/nvblox.git
#
# so in the v4.5-0 tarball nvblox_ros/nvblox_core is an *empty directory*, and nvblox_ros
# fails at configure the moment it does
#
#     include(nvblox_core/cmake/cuda/setup_compute_capability.cmake)
#     add_subdirectory(nvblox_core)
#
# The core library is Apache-2.0 and public, and the submodule commit recorded at the v4.5-0
# tag resolves in nvidia-isaac/nvblox, so fetching that exact commit reproduces what a
# recursive clone would have given. Pinned by commit rather than branch on purpose: the
# submodule tracks `public`, which moves.
_NITROS_LFS_ROOT = (
    "https://media.githubusercontent.com/media/NVIDIA-ISAAC-ROS/isaac_ros_nitros/"
    "260cee67e8344db363f7584256ae161d03abfd01/"
)


def nitros_lfs(path: str, sha256: str) -> tuple[str, str, str]:
    """A checksum-pinned Git LFS object omitted from GitHub's source archive."""
    return _NITROS_LFS_ROOT + path, sha256, "src/" + os.path.dirname(path)


EXTRA_SOURCES = {
    # GitHub archives contain pointers rather than Git LFS objects. Include only the
    # binaries selected by each vendor package for the two supported architectures.
    "ros-jazzy-cuapriltags-vendor": [
        nitros_lfs("cuapriltags_vendor/lib_aarch64_jetpack61/libcuapriltags.a",
                   "e67298e8ee52d6253cd702f4c55b3727bea177f57236aa23797bde50d74dfc24"),
        nitros_lfs("cuapriltags_vendor/lib_x86_64_cuda_12_6/libcuapriltags.a",
                   "a7f32f58782de61dd23e507fe6ce5a907379498deec505669fe339ecd4facba7"),
    ],
    "ros-jazzy-cumotion-vendor": [
        nitros_lfs("cumotion_vendor/aarch64_jetpack70/lib/libcumotion.so.1.1.0",
                   "6977efcb757839a3d992c368d8bb9ef12c4ee728469b567ae3baa26d89717c76"),
        nitros_lfs("cumotion_vendor/aarch64_jetpack70/python_wheels/cumotion-1.1.0-cp312-cp312-linux_aarch64.whl",
                   "60f6aa4703e201ab9c1b5dd4f78d85c1aa5b1c1dfc83b785f85f66309f766359"),
        nitros_lfs("cumotion_vendor/aarch64_jetpack70/python_wheels/cumotion_vis-1.1.0-py3-none-any.whl",
                   "0dce7c072d865d71fbb2ed44381d812d2601e836d82276341af7d2c39eaf24f2"),
        nitros_lfs("cumotion_vendor/x86_64_cuda_13_0/lib/libcumotion.so.1.1.0",
                   "fe13f8b2c1b6d908a72f087041a2385a1b4c2157323623bdf3e905f2852c9a2c"),
        nitros_lfs("cumotion_vendor/x86_64_cuda_13_0/python_wheels/cumotion-1.1.0-cp312-cp312-linux_x86_64.whl",
                   "b3f3eb0699686f4c3b1ba218513040fe6cdcdf0e474f78d5a8fe06371819fec5"),
        nitros_lfs("cumotion_vendor/x86_64_cuda_13_0/python_wheels/cumotion_vis-1.1.0-py3-none-any.whl",
                   "ffebfff502ff599aa917503e2648255def6b815bf1092405bf732bb9bd056f3a"),
    ],
    "ros-jazzy-cuvslam-vendor": [
        nitros_lfs("cuvslam_vendor/lib_aarch64_jetpack70/cuvslam_api_launcher",
                   "c8b7bcb74c3da5adc69fdadf511b1096ccb1828e5fc5c78e308f977be837a630"),
        nitros_lfs("cuvslam_vendor/lib_aarch64_jetpack70/libcuvslam.so",
                   "d451faa3b0ebb606c02bb82586876d865fa03fbd34d1b7e11e06eff32f3f7424"),
        nitros_lfs("cuvslam_vendor/lib_x86_64_cuda_13_0/cuvslam_api_launcher",
                   "809717836ad7281cf5682f17c813c6418cc944a638072d43baad0f50d8bd7ecb"),
        nitros_lfs("cuvslam_vendor/lib_x86_64_cuda_13_0/libcuvslam.so",
                   "d870759dc6d78b9fe55dbb842cac3b6cd6d804bde04dd8b546b5f2c466834f5e"),
    ],
    # IsaacTeleop, which isaac_teleop_core needs and which the release tarball omits --
    # third instance of this shape here, after the nvblox core below and the git-lfs
    # pointers in isaac_ros_nitros. The directory is a git submodule, so the tarball
    # carries an empty isaac_teleop_core/IsaacTeleop/ and CMakeLists.txt stops at
    #
    #   FATAL_ERROR "Missing Teleop ROS 2 Python source: ...teleop_ros2_node.py
    #                Ensure the IsaacTeleop submodule is initialized."
    #
    # which is at least a clear diagnosis, unlike nvblox's. The submodule is public --
    # .gitmodules points at github.com/NVIDIA/IsaacTeleop, branch release/1.3.x -- and the
    # recorded commit resolves there, so this reproduces what a recursive clone would give.
    # Pinned by commit rather than by the branch, which moves.
    "ros-jazzy-isaac-teleop-core": [(
        "https://github.com/NVIDIA/IsaacTeleop/archive/"
        "465ce637120ac35404f5f741a9f25f3f1a1a25ea.tar.gz",
        "730723484d920379ba095f3e3e3fe380669573723cb119cc1b28df4131702da6",
        "src/isaac_teleop_core/IsaacTeleop",
    )],
    "ros-jazzy-unitree-g1-ros2-control": [(
        "https://github.com/unitreerobotics/unitree_sdk2/archive/refs/tags/2.0.2.tar.gz",
        "8128514cccd840623fd47d655bdde29353ae5365d6940ec737f6fd61e8de366c",
        "src/unitree_g1/unitree_g1_ros2_control/unitree_sdk2",
    )],
    "ros-jazzy-nvblox-ros": [(
        "https://github.com/nvidia-isaac/nvblox/archive/"
        "24eee4948768682fa1ffb969b881efee4fca29c2.tar.gz",
        "b5243e56760fe1aaa4d029d71ed8dde34ee9f4ac84aa7de1c4fafcb32d27fc30",
        "src/nvblox_ros/nvblox_core",
    )],
    "ros-jazzy-nvblox-image-padding": [(
        "https://github.com/nvidia-isaac/nvblox/archive/"
        "24eee4948768682fa1ffb969b881efee4fca29c2.tar.gz",
        "b5243e56760fe1aaa4d029d71ed8dde34ee9f4ac84aa7de1c4fafcb32d27fc30",
        "src/nvblox_ros/nvblox_core",
    )],
}

# stdgpu, which nvblox core needs and which cannot come from a channel.
#
# nvblox offers USE_SYSTEM_STDGPU, and it is a trap for a packager: it does not want
# vanilla stdgpu. thirdparty/stdgpu/stdgpu.cmake FetchContents commit 71a5aef2 and applies
# six patches, two of which change behaviour rather than fixing a build:
#
#   stdgpu_expose_occupied.patch     adds a public method, unordered_map::occupied(index_t),
#                                    which nvblox calls when copying the hash
#   stdgpu_handle_collisions.patch   replaces stdgpu's estimate of hash collisions with the
#                                    worst case
#
# So a stock stdgpu -- in conda-forge or anywhere else -- would fail to compile nvblox,
# because the method it calls would not exist. Pointing USE_SYSTEM_STDGPU at one looks like
# the clean answer and does not work.
#
# Instead fetch the same commit nvblox pins, apply nvblox's own patches to it (they ship in
# the core tree, so nothing is invented here), and hand it to FetchContent as a local source
# directory -- which is also what makes the build hermetic, since FetchContent would
# otherwise clone from GitHub mid-build.
_STDGPU = (
    "https://github.com/stotko/stdgpu/archive/"
    "71a5aef26626eda47d15e5f577ca3b1538ff996a.tar.gz",
    "0110a321d41b4841d5daa6e0dd3ffec2f38d6591ded5ee13997ddd019328e174",
    "src/stdgpu",
)
# sqlite, vendored for a different reason than stdgpu: the system branch does
# `find_package(sqlite3 REQUIRED)` -- lowercase -- and nothing provides a lowercase
# sqlite3-config.cmake. CMake ships FindSQLite3 with a capital S, and conda-forge's sqlite
# has no config module at all, so USE_SYSTEM_SQLITE3=ON cannot be satisfied however the
# prefix is populated. nvblox's own fallback compiles the amalgamation, which is one .c
# file, so hand it that instead. Same version and hash nvblox pins.
_SQLITE = (
    "https://sqlite.org/2025/sqlite-amalgamation-3500400.zip",
    "1d3049dd0f830a025a53105fc79fd2ab9431aea99e137809d064d8ee8356b032",
    "src/sqlite3",
)
_NVBLOX_CORE_USERS = ("ros-jazzy-nvblox-ros", "ros-jazzy-nvblox-image-padding")
for _p in _NVBLOX_CORE_USERS:
    EXTRA_SOURCES[_p].append(_STDGPU)
    EXTRA_SOURCES[_p].append(_SQLITE)

# Shell lines run in the package directory, after the generic rewrites and before cmake.
EXTRA_PREP = {
    # Apply nvblox's stdgpu patches to the stdgpu source fetched above. They are git diffs
    # from the stdgpu root, so `patch -p1` in that tree does what `git apply` would have.
    # The count is asserted: if the patch set changes shape upstream the build should stop,
    # not quietly compile a stdgpu missing the method nvblox calls.
    _p: [
        'test -d "${SRC_DIR}/src/stdgpu" || { echo "stdgpu source missing"; exit 1; }',
        'n=$(ls "${SRC_DIR}"/src/nvblox_ros/nvblox_core/nvblox/thirdparty/stdgpu/*.patch | wc -l);'
        ' [ "$n" -eq 6 ] || { echo "expected 6 stdgpu patches, found $n"; exit 1; }',
        'for q in "${SRC_DIR}"/src/nvblox_ros/nvblox_core/nvblox/thirdparty/stdgpu/*.patch;'
        ' do patch -p1 -d "${SRC_DIR}/src/stdgpu" < "$q" || exit 1; done',
        # nvblox/geometry/internal/impl/plane_impl.h uses assert() without including
        # <cassert>, so it compiles only where something else happened to include it first.
        # Same shape as ISSUES.md #1 (cuvslam2.h missing <cstdint>) and the same workaround
        # the visual-slam recipe carries: force the include rather than patch a submodule we
        # fetch separately. Apache-2.0, so it is PR-able upstream -- ISSUES.md #25.
        'export CXXFLAGS="${CXXFLAGS:-} -include cassert"',
        'export CUDAFLAGS="${CUDAFLAGS:-} -include cassert"',
    ]
    for _p in _NVBLOX_CORE_USERS
}
# The 5.0 ROS wrapper still lists teleop_profiles.py, removed from its pinned
# IsaacTeleop release/1.3.x source. Nothing imports it; omit the stale install entry.
# Its version logic also mistakes the enclosing isaac-forge checkout for IsaacTeleop's
# repository. Give the stripped archive a minimal nested checkout so versioning and the
# source's later pinned Git fetches can both use Git.
EXTRA_PREP["ros-jazzy-isaac-teleop-core"] = [
    "grep -q 'teleop_profiles.py' CMakeLists.txt",
    "sed -i 's|.*teleop_profiles.py.*|)|' CMakeLists.txt",
    "git -C IsaacTeleop init -q -b release/1.3.x",
    "git -C IsaacTeleop add VERSION",
    "git -C IsaacTeleop -c user.name=builder -c user.email=builder@localhost commit -qm source",
]
# cuMotion's config incorrectly makes Eigen 3.3 a same-major requirement. Its API uses
# ABI-compatible fixed-size Eigen types and all consumers compile successfully with Eigen 5.
EXTRA_PREP["ros-jazzy-cumotion-vendor"] = [
    "test \"$(grep -rl 'find_dependency(Eigen3 3.3)' -- */lib/cmake/cumotion/cumotionConfig.cmake | wc -l)\" -eq 2",
    "sed -i 's/find_dependency(Eigen3 3.3)/find_dependency(Eigen3)/' */lib/cmake/cumotion/cumotionConfig.cmake",
]

# Extra -D flags for cmake, keyed by conda package name.
EXTRA_CMAKE_ARGS = {
    _p: [
        # From the prefix rather than FetchContent, which would need network mid-build.
        # Note USE_SYSTEM_SQLITE3, with the 3. An earlier pass read these names with a
        # regex that stopped at digits and produced USE_SYSTEM_SQLITE, which silently left
        # the flag unset -- so nvblox took its FetchContent branch, found no network, and
        # failed in add_library() with an empty source dir. A wrong flag name is not an
        # error to CMake; it is just an unset variable.
        "-DUSE_SYSTEM_EIGEN=ON", "-DUSE_SYSTEM_GFLAGS=ON", "-DUSE_SYSTEM_GLOG=ON",
        # nvblox's system-eigen branch does
        #     target_include_directories(nvblox_eigen SYSTEM INTERFACE ${EIGEN3_INCLUDE_DIR})
        # which is the pre-target-era variable. Current Eigen3Config.cmake exports the
        # Eigen3::Eigen target and does not set it, so the include directory came out empty
        # and every translation unit failed on `#include <Eigen/Core>`. Name it explicitly;
        # conda-forge puts the headers one level down, in include/eigen3.
        '-DEIGEN3_INCLUDE_DIR="${PREFIX}/include/eigen3"',
        "-DUSE_SYSTEM_BENCHMARK=ON", "-DUSE_SYSTEM_GTEST=ON",
        # These two stay FetchContent's, pointed at vendored trees -- see _STDGPU/_SQLITE.
        '-DFETCHCONTENT_SOURCE_DIR_EXT_STDGPU="${SRC_DIR}/src/stdgpu"',
        '-DFETCHCONTENT_SOURCE_DIR_EXT_SQLITE3="${SRC_DIR}/src/sqlite3"',
        # Nothing may reach the network mid-build; if a FetchContent is not satisfied by a
        # source dir above, fail rather than clone.
        "-DFETCHCONTENT_FULLY_DISCONNECTED=ON",
    ]
    for _p in _NVBLOX_CORE_USERS
}

# cuMotion's packaged CMake config calls find_dependency(CCCL), while conda-forge's CUDA
# toolkit installs that config below targets/<arch> rather than the prefix searched by
# default. Point CMake at the package explicitly for consumers that load cuMotion.
for _p in [
    "ros-jazzy-isaac-ros-cumotion-controllers",
    "ros-jazzy-isaac-ros-ur5-cumotion-benchmark",
]:
    EXTRA_CMAKE_ARGS[_p] = [
        '-DCMAKE_PREFIX_PATH="${PREFIX};${PREFIX}/targets/x86_64-linux"']

# nvblox_ros_common exports the CUDA include directory as part of its public interface --
# ament_target_dependencies(nvblox_ros_common_lib rclcpp CUDAToolkit) makes
# ${CUDAToolkit_INCLUDE_DIRS} INTERFACE. -DCUDAToolkit_INCLUDE_DIR was tried and does not
# redirect it, so the fix is the prefix rewrite in the build script above, which is general
# rather than specific to this package. Upstream would do better to keep the toolkit out of
# the public interface entirely -- the target already links CUDA::cudart, which carries its
# own includes. ISSUES.md #24.
# Host requirements beyond what the manifest and traits give, keyed by conda package name.
EXTRA_HOST = {
    # nvblox core's own dependencies, none of which appears in any package.xml -- the
    # manifest describes the ROS wrapper, not the vendored library underneath it. Taken from
    # what the core actually includes and links: CUDA::npp{c,ial,idei,im,tc} plus npp.h,
    # curand_kernel.h, cuda_fp16.h and the thrust headers (thrust ships with cccl, which
    # cuda-cudart-dev already brings).
    _p: ["libnpp-dev", "libcurand-dev", "gflags", "glog", "benchmark", "gtest", "eigen"]
    for _p in _NVBLOX_CORE_USERS
}
# LibTorch's exported Caffe2 config enables CUDA and looks for the complete development
# toolkit (nvcc plus headers for cudart, cuBLAS, NVRTC, and friends). The pytorch package's
# run dependencies intentionally provide only the runtime libraries, so the package's
# declared cuda-toolkit build dependency needs a real toolkit in host, not merely the
# cuda-version compatibility metapackage used for runtime pinning.
EXTRA_HOST["ros-jazzy-isaac-deploy-core"] = [
    "cuda-toolkit", "triton-server ==2.60.0"]
EXTRA_HOST["ros-jazzy-isaac-ros-triton"] = ["triton-server ==2.60.0"]
# xorg-libx11 contains Xlib.h but X.h and the other protocol headers are separate.
EXTRA_HOST["ros-jazzy-isaac-teleop-core"] = ["vulkan-headers", "xorg-xorgproto"]
# Unitree's CMakeLists invokes this generator but package.xml omits it.
EXTRA_HOST["ros-jazzy-unitree-api"] = ["ros-jazzy-rosidl-generator-dds-idl"]

# These packages do not compile CUDA themselves, but dependencies in their public CMake
# closure load isaac_ros_common-extras.cmake, which requires CUDAToolkit. Without a complete
# host toolkit, FindCUDAToolkit falls through to the machine's /usr/local/cuda and then fails
# to find a prefix-provided cudart.
for _p in [
    "ros-jazzy-isaac-ros-cumotion-controllers",
    "ros-jazzy-isaac-ros-ur5-cumotion-benchmark",
]:
    EXTRA_HOST[_p] = ["cuda-toolkit"]

# The manifest cannot name this non-ROS package, although the encoder links all six
# multimedia libraries it provides.
EXTRA_HOST["ros-jazzy-isaac-ros-h264-encoder"] = ["nvv4l2"]
EXTRA_HOST["ros-jazzy-isaac-ros-h264-decoder"] = ["nvv4l2", "libv4l"]

# Runtime requirements for dependencies hidden from package.xml (for example, a library
# previously downloaded by CMake). Keep these separate from EXTRA_HOST: most entries in
# EXTRA_HOST are development-only and must not leak into runtime environments.
EXTRA_RUN = {
    # isaac_deploy_core's installed extras file calls find_package(Torch), whose
    # CUDA-enabled Caffe2 config calls find_package(CUDAToolkit). Runtime CUDA libraries
    # are therefore insufficient for downstream CMake consumers: the exported package
    # requires the development toolkit as part of its public interface.
    "ros-jazzy-isaac-deploy-core": ["cuda-toolkit", "triton-server ==2.60.0"],
    "ros-jazzy-isaac-ros-triton": ["triton-server ==2.60.0"],
    "ros-jazzy-isaac-ros-h264-encoder": ["nvv4l2"],
    "ros-jazzy-isaac-ros-h264-decoder": ["nvv4l2", "libv4l"],
}

# Patches applied to a package's source, keyed by conda package name; paths are relative
# to the recipe directory. All but one are prepared for upstream; the exception says so in
# its own commit message, and the reason it cannot go upstream is that the code that needs
# fixing is under NVIDIA's proprietary header.
PATCHES = {
    # v5.0-0 installs a VERSION file that is not present in the release archive.
    "ros-jazzy-cuapriltags-vendor": ["patches/0001-do-not-install-missing-version-file.patch"],
    "ros-jazzy-rosidl-buffer": ["patches/0001-use-cxx-20-directly.patch"],
    "ros-jazzy-rosidl-buffer-backend-registry": [
        "patches/0001-use-cxx-20-directly.patch"],
    # Explicit specializations of a variable template are not implicitly inline, so
    # epsilon.hpp produces multiple definitions of MachineEpsilon<float|double> in any
    # target with two TUs including it. Breaks
    # isaac_ros_nitros_detection3_d_array_type at link time under GCC 15.
    # Apache-2.0, so ours to fix; see ISSUES.md and upstream/README.md.
    "ros-jazzy-gxf-isaac-gems": ["patches/0001-epsilon-odr-inline.patch"],
    # Replace NVIDIA's private-artifactory FetchContent fallback with the packaged
    # Triton C API. This makes the dependency reproducible and visible to the solver.
    "ros-jazzy-isaac-deploy-core": ["use-packaged-triton.patch"],
    "ros-jazzy-isaac-ros-triton": ["patches/0001-use-packaged-triton-core.patch"],
    "ros-jazzy-unitree-g1-bridge": ["patches/0001-match-package-version.patch"],
    # Isaac ROS targets CV-CUDA 0.14; adapt its changed C++ wrappers to conda-forge 0.16.
    "ros-jazzy-isaac-ros-common": [
        "patches/0001-isaac_ros_common-use-FindCUDAToolkit-instead-of-the-.patch",
        "patches/0002-do-not-export-global-CCCL-target.patch"],
    "ros-jazzy-isaac-ros-h264-decoder": [
        "patches/0001-h264_decoder-link-the-nvbuf-libraries-by-name-so-DT_.patch"],
    "ros-jazzy-isaac-ros-cumotion-robot-segmenter": [
        "patches/0001-support-vector-backed-image-messages.patch"],
    "ros-jazzy-isaac-ros-pointcloud-utils": [
        "patches/0001-support-vector-backed-point-clouds.patch"],
    "ros-jazzy-isaac-ros-teleop": [
        "patches/0001-use-conda-forge-msgpack-c-target.patch"],
    # The encoder hard-codes Ubuntu multiarch paths for nvv4l2 libraries even though
    # CMake can resolve the declared package from any installation prefix.
    "ros-jazzy-isaac-ros-h264-encoder": [
        "patches/0001-find-nvv4l2-libraries-in-prefix.patch"],
    # unitree_sdk2 ships only a static SDK archive, which find_library misses when the
    # distribution toolchain restricts its search suffixes to shared libraries.
    "ros-jazzy-unitree-g1-ros2-control": [
        "patches/0001-use-vendored-static-sdk-library.patch"],
    # test_utils.py raises at module scope when ISAAC_ROS_WS is unset, and __init__.py
    # re-exports it, so importing the package fails in any environment that does not
    # export that variable -- which is every conda environment. Apache-2.0, ours to fix;
    # see ISSUES.md.
    "ros-jazzy-isaac-ros-manipulation-ros-python-utils": [
        "patches/0001-defer-isaac-ros-ws-check.patch"],
}

# Build-number bumps that must survive recipe regeneration.
BUILD_NUMBERS = {
    "ros-jazzy-isaac-ros-cvcuda-utils": 2,
    "ros-jazzy-nvblox-ros": 1,
    "ros-jazzy-isaac-ros-yolov8": 1,
}

# Build-only libraries whose run exports must not leak into package metadata.
IGNORE_RUN_EXPORTS = {
    "ros-jazzy-nvblox-ros": ["gtest"],
}

# Files a package must ship beyond share/<pkg>/package.xml, checked declaratively at the
# end of the build. Worth listing wherever a specific file is the reason the package
# exists, or wherever a patch is what puts it there -- a passing build says the compiler
# was happy, not that the payload arrived.
EXTRA_TEST_FILES = {
    "ros-jazzy-isaac-ros-triton": [
        "lib/libtriton_node.so",
    ],
    "ros-jazzy-unitree-api": [
        "share/unitree_api/msg/Request.msg",
    ],
    "ros-jazzy-unitree-g1-bridge": [
        "bin/unitree_bridge_node",
        "share/unitree_g1_bridge/launch/unitree_g1_bridge.launch.py",
    ],
    "ros-jazzy-thor-devkit-realsense-rig-description": [
        "share/thor_devkit_realsense_rig_description/urdf/thor_devkit_realsense_rig_d455.urdf.xacro",
        "share/thor_devkit_realsense_rig_description/meshes/thor_devkit_realsense_rig_frame.stl",
        "share/thor_devkit_realsense_rig_description/launch/thor_devkit_realsense_rig_description.launch.py",
    ],
    "ros-jazzy-isaac-ros-manipulation-asset-bringup": [
        "lib/isaac_ros_manipulation_asset_bringup/setup_perception_models.py",
    ],
    "ros-jazzy-isaac-ros-manipulation-bringup": [
        "share/isaac_ros_manipulation_bringup/launch/workflows.launch.py",
    ],
}


def homepage_of(repo: str) -> str:
    return REPOS[repo].get("homepage", f"https://github.com/NVIDIA-ISAAC-ROS/{repo}")


def license_id(declared: str) -> str:
    """SPDX id for a package.xml <license> string.

    Everything NVIDIA ships is either Apache-2.0 or the NVIDIA Isaac ROS Software
    License, which has no SPDX id -- hence the LicenseRef. The non-NVIDIA packages built
    here are not covered by that dichotomy: topic_based_ros2_control declares a bare
    "BSD" whose LICENSE text carries the no-endorsement clause, so BSD-3-Clause.
    """
    if declared.startswith("Apache"):
        return "Apache-2.0"
    if declared.strip() in ("BSD", "BSD-3-Clause", "BSD 3-Clause License"):
        return "BSD-3-Clause"
    if declared.strip() == "MIT":
        return "MIT"
    return "LicenseRef-NVIDIA-Isaac-ROS"


def src_dir(repo: str) -> str:
    return os.path.join(CACHE, repo)


def detect(cml: str, pkgxml: str, path: str) -> set[str]:
    """Work out build traits from the package's own CMakeLists and manifest."""
    traits = set()
    if re.search(r"LANGUAGES[^)]*\bCUDA\b|enable_language\(\s*CUDA", cml):
        traits.add("cuda")
    if "find_package(CUDAToolkit" in cml:
        traits.add("cuda")
    # Some packages activate CUDA indirectly. isaac_deploy_core is the first: finding
    # Torch loads Caffe2's CUDA config, which enables the CUDA language and therefore needs
    # compiler activation even though its own CMakeLists has no CUDA command.
    if "cuda-toolkit" in pkgxml:
        traits.add("cuda")
    # This wrapper configures the separately fetched IsaacTeleop CMake project, which
    # calls find_package(CUDAToolkit); that nested CMakeLists is not in `cml` above.
    if path == "isaac_teleop_core":
        traits.add("cuda")
    if re.search(r"find_package\(\s*Eigen3", cml):
        traits.add("eigen")
    if re.search(r"find_package\(\s*vpi", cml):
        traits.add("vpi")
    if re.search(r"find_package\(\s*yaml-cpp", cml):
        traits.add("yamlcpp")
    if "rosidl_generate_interfaces" in cml:
        traits.add("rosidl")
    # isaac_ros_common's version-info helper shells out to python and imports yaml.
    if "isaac_ros_common-version-info" in cml or "generate_version_info" in cml:
        traits.add("python")
    # Trust CMakeLists over package.xml for build tooling. Several packages declare
    # only ament_cmake in the manifest but call find_package(ament_cmake_auto), so
    # deriving this from the manifest alone fails to configure.
    if "find_package(ament_cmake_auto" in cml:
        traits.add("ament_auto")
    if re.search(r"find_package\(\s*OpenCV", cml):
        traits.add("opencv")
    if re.search(r"find_package\(\s*cvcuda|nvcv", cml):
        traits.add("cvcuda")
    # Depending on isaac_ros_common means needing a CUDA toolkit at configure time even
    # if this package never touches CUDA itself. isaac_ros_commonConfig.cmake includes
    # isaac_ros_common-extras.cmake, which calls find_package(CUDAToolkit REQUIRED)
    # unconditionally, so it runs for every consumer. gxf_isaac_gems is the clearest
    # case: header-only, no CUDA anywhere in its own CMakeLists, and it still cannot
    # configure without cudart.
    #
    # This was invisible for a long time because the unpatched extras used the removed
    # FindCUDA module, which silently resolved against the build machine's
    # /usr/local/cuda. Once that is fixed to look inside the prefix, the missing
    # declaration turns into a hard `missing: CUDA_CUDART` error.
    if re.search(r"isaac_ros_common", cml) or "isaac_ros_common" in pkgxml:
        traits.add("cuda")
    # install_isaac_ros_asset() cannot run in a package build. It does two things: it
    # execute_process()es the asset script with --print-install-paths at *configure* time,
    # and every path in those scripts derives from $ISAAC_ROS_WS, so with that unset --
    # which it is outside NVIDIA's container -- configure aborts with "ERROR:
    # ISAAC_ROS_WS is not set." Then it hangs the script off add_custom_target(... ALL),
    # making the default build target download model weights from NGC behind a EULA and
    # run trtexec over them.
    #
    # The second half should not happen in a binary package regardless of the first: a
    # TensorRT engine plan is specialised to the GPU, driver and TensorRT version that
    # produced it, so a .plan baked into a package is wrong for every machine but the
    # builder's. Models belong on the target system, which is how NVIDIA documents
    # installing them anyway:
    #
    #     ros2 run <pkg> <asset_name>.sh
    #
    # So keep the two things that make that command work -- the script under lib/<pkg>/,
    # which the untouched install(PROGRAMS ...) already does, and the ament resource
    # pointing at it -- and drop the build-time download. See ISSUES.md #20; the fix
    # cannot be made upstream because the function lives in isaac_ros_common/cmake, under
    # the proprietary header.
    #
    # Four packages need this (foundationpose, rtdetr, grounding_dino and peoplenet model
    # installs) and every Isaac repo tends to ship one, so it is a generator rule rather
    # than four near-identical patch files. All four have the identical shape
    # `install_isaac_ros_asset(<name>)` with <name> matching the asset script's basename,
    # which is what asset_name() relies on and what the build script asserts before
    # rewriting.
    if "install_isaac_ros_asset(" in cml:
        traits.add("asset")
    # `find_package(Eigen3 3.3 REQUIRED NO_MODULE)`, which 18 packages in this corpus
    # write verbatim. The number reads as a floor and, in config mode, acts as a ceiling
    # too: Eigen ships a SameMajorVersion Eigen3ConfigVersion.cmake, so eigen 5 *rejects*
    # a 3.3 request rather than satisfying it --
    #
    #   Could not find a configuration file for package "Eigen3" that is compatible with
    #   requested version "3.3".  ... Eigen3Config.cmake, version: 5.0.1
    #
    # NO_MODULE forces config mode, so ros-jazzy-eigen3-cmake-module's module-mode
    # FindEigen3.cmake -- which does treat the version as a floor -- cannot rescue these.
    # robostack-jazzy has moved to eigen 5, so every one of them fails to configure.
    #
    # Nothing in this corpus needs Eigen 3 specifically; the types crossing these
    # boundaries (Matrix, Quaternion, Map) are unchanged. Same over-constraint as
    # ISSUES.md #13 and the same treatment, applied as a rule rather than as 18 identical
    # patch files.
    if re.search(r"find_package\(\s*Eigen3\s+[0-9]", cml):
        traits.add("eigenfloor")
    return traits


def asset_names(cml: str) -> list[str]:
    """Every asset registered by install_isaac_ros_asset(); each is also its script name.

    A list, not one name, because a package may register several:
    isaac_ros_peoplesemseg_models_install calls it twice, for
    install_peoplesemsegnet_vanilla and install_peoplesemsegnet_shuffleseg.

    This used to be a `re.search` returning the first match, which was wrong in a way that
    would not have failed the build. The sed that performs the rewrite is generic and runs
    per line, so both calls were converted correctly; what took only the first name was the
    *assertion* in front of it and the `package_contents` test after it. So the second
    asset's script and ament resource shipped untested -- exactly the payload those tests
    exist to cover, since it comes from our rewrite rather than from upstream.
    """
    return re.findall(r"install_isaac_ros_asset\(\s*([A-Za-z0-9_]+)\s*\)", cml)


# package.xml uses bare rosdep keys, not deb names, so a second mapping layer is
# needed on top of gen_repack's MAP. Anything not listed here and not obviously a
# system package is assumed to be a ROS package and gets the ros-jazzy- prefix.
SYSTEM = {
    "cuda-toolkit": "cuda-version 13.*",
    "nvidia-cuda": "cuda-version 13.*",
    # Compatibility package: conda-forge on x86, native NVIDIA payload on Jetson.
    "tensorrt": '${{ "tensorrt >=11,<12" if target_platform == "linux-64" else "tensorrt >=10,<11" }}',
    "eigen": "eigen",
    "eigen3": "eigen",
    "yaml-cpp": "yaml-cpp",
    "boost": "libboost-devel",
    "libopencv-dev": "libopencv 4.13.*",
    "cvcuda0-dev": "libcvcuda-dev >=0.16,<0.17",
    "magic_enum": "magic_enum",
    "nlohmann_json": "nlohmann_json",
    "python3-numpy": "numpy",
    "python3-pytest": None,
    "python3-opencv": "py-opencv",
    "python3-matplotlib": "matplotlib-base",
    "python3-scipy": "scipy",
    "python3-gdown": "gdown",
    "python3-yaml": "pyyaml",
    "python3-psutil": "psutil",
    "python3-pynvml-pip-shim": "pynvml",
    "python3-tqdm": "tqdm",
    # NVIDIA's ROS shim means "install the Python torch distribution". This package
    # also supplies LibTorch headers, libraries, and TorchConfig.cmake, all of which
    # isaac_deploy_core uses directly during its C++ build.
    "python3-torch-pip-shim": "pytorch-gpu ==2.13.0 cuda130_generic_*_202",
    "libgflags-dev": "gflags",
    "libgoogle-glog-dev": "glog",
    "assimp": "assimp",
    # tl_expected used to be mapped to a conda-forge "tl-expected", which does not exist
    # under that name or any near variant. It is a *ROS* package -- robostack-jazzy has
    # ros-jazzy-tl-expected 1.3.1 -- so the right handling is no entry at all: the default
    # ros_name() below already produces it. isaac_deploy_core is the first package here to
    # need it, which is why the wrong mapping went unnoticed.
    "benchmark": "benchmark",
    "posix_ipc": "posix_ipc",
    "git": None,
    "iputils-ping": None,
    # isaac_ros_cloud_control. Both would otherwise be dropped by the
    # "system-looking key" rule below, and both are real: the MQTT bridge cannot import
    # paho without the first, and vda5050_action_handler_plugins links libcurl.
    "python3-paho-mqtt-pip-shim": "paho-mqtt",
    "libcurl-dev": "libcurl",
    # isaac_teleop_core. These rosdep/Debian names differ from their conda-forge names.
    "libjsoncpp-dev": "jsoncpp",
    "libwayland-dev": "wayland",
    "libx11-dev": "xorg-libx11",
    "patchelf": "patchelf",
    "python3-pip": "pip",
    "python3-uv-pip-shim": "uv",
    "libatomic1": "libgcc",
    "libegl1": "libglvnd",
    "libgl1": "libglvnd",
    "libglx0": "libglvnd",
    "libvulkan1": "libvulkan-loader",
    "libx11-6": "xorg-libx11",
    "libxext6": "xorg-libxext",
    "python3-dex-retargeting-pip-shim": "dex-retargeting",
    "python3-nlopt": "nlopt",
    "python3-scipy-pip-shim": "scipy",
    "python3-websockets-pip-shim": "websockets",
    # adb, coturn and libbsd have no matching cross-architecture conda package. They are
    # optional external tools/libraries, not referenced by the package's source build.
    "adb": None,
    "coturn": None,
    "libbsd0": None,
    # python3-isaacteleop-pip-shim is deliberately not mapped: this recipe builds that
    # NVIDIA wheel itself from the pinned IsaacTeleop source.
    "python3-msgpack": "msgpack-python",
    "python3-msgpack-numpy": "msgpack-numpy",
    "msgpack": "msgpack-c",
}


def ros_name(dep: str) -> str:
    return "ros-jazzy-" + dep.replace("_", "-")


def deps_of(pkgxml: str, name: str, kinds: set[str] | None = None) -> list[str]:
    out: list[str] = []
    for kind, attrs, dep in DEP_TAG.findall(pkgxml):
        dep = dep.strip()
        if kind == "test_depend" or dep in TEST_ONLY or "condition" in attrs:
            continue
        if kinds is not None and kind not in kinds:
            continue
        if dep in DROP:
            continue
        if dep in DROP_DEPS.get(name, {}):
            print(f"     note {name}: dropping declared '{dep}' "
                  f"({DROP_DEPS[name][dep]})")
            continue
        if dep in SYSTEM:
            mapped = SYSTEM[dep]
            if mapped is None:
                continue
        elif dep in MAP:
            mapped = MAP[dep]
        elif dep.startswith("python3-") or "-" in dep:
            # An unrecognised system-looking key: skip rather than invent a ROS
            # package that does not exist, and let the build tell us if it mattered.
            #
            # The test used to include `dep.startswith("lib")`, which was wrong and cost
            # nvblox_ros a real dependency: `libstatistics_collector` is a core ROS 2
            # package -- ros-jazzy-libstatistics-collector, ten builds in robostack-jazzy --
            # and it was being silently dropped for beginning with "lib". rosdep's
            # convention separates the two cleanly: ROS package keys are the package name,
            # so they use underscores, while Debian system keys use dashes
            # (libgflags-dev, libopencv-dev, libcurl-dev). Every lib* key in SYSTEM above
            # has a dash, so requiring one loses nothing and stops swallowing ROS packages
            # whose names happen to start with those three letters.
            print(f"     note {name}: skipping unmapped system dep '{dep}'")
            continue
        else:
            mapped = ros_name(dep)
        if mapped == name or mapped in out:
            continue
        out.append(mapped)
    # Only on the unfiltered call, which is the one that feeds host and run. The
    # kinds-filtered calls exist to pick build tooling out of the manifest, and an
    # undeclared dependency is by definition not in the manifest.
    if kinds is None:
        for extra in EXTRA_DEPS.get(name, []):
            if extra not in out:
                print(f"     note {name}: adding undeclared dep '{extra}'")
                out.append(extra)
    return sorted(out)


# Third-party python distributions whose import name differs from the conda package,
# or which no package.xml in this corpus bothers to declare.
PY_IMPORTS = {
    "yaml": "pyyaml",
    # isaac_ros_pynitros does `import cuda.bindings.driver`; the `cuda` module is
    # conda-forge's cuda-python. Without this the import heuristic invents ros-jazzy-cuda.
    "cuda": "cuda-python",
    "numpy": "numpy",
    "scipy": "scipy",
    "matplotlib": "matplotlib-base",
    "cv2": "py-opencv",
    "PIL": "pillow",
    "torch": "pytorch-gpu ==2.13.0 cuda130_generic_*_202",
    "psutil": "psutil",
    # isaac_ros_cloud_control's python packages. Each of these would otherwise be guessed
    # as a ROS package -- ros-jazzy-boto3, ros-jazzy-paho, ros-jazzy-opentelemetry -- none
    # of which exists, so the recipe would generate cleanly and then fail to solve.
    "boto3": "boto3",
    "paho": "paho-mqtt",
    "opentelemetry": "opentelemetry-api",
    # isaac_ros_mcap_lerobot_converter. `av` is PyAV and `rosbags` is the standalone
    # rosbag reader; both are in conda-forge under those names, and both would otherwise
    # be guessed as ROS packages that do not exist.
    "av": "av",
    "rosbags": "rosbags",
}

# ROS python modules whose conda package is not just ros-jazzy-<module>. The tf2_ros
# python module lives in tf2_ros_py; ros-jazzy-tf2-ros is the C++ package and installs
# no python at all, so guessing from the module name gives an env that cannot import it.
ROS_PY_IMPORTS = {
    "tf2_ros": "ros-jazzy-tf2-ros-py",
}

# Subdirectories of a module that ship with it but are never imported by it.
NOT_IMPORTED = {"test", "tests", "examples"}


def py_run_deps(base: str, module: str, name: str) -> list[str]:
    """Runtime deps read out of the module's own import statements.

    The manipulation and isaac_ros_common python packages under-declare badly:
    isaac_ros_launch_utils lists exactly one dependency (isaac_ros_common, build-only)
    while importing launch, launch_ros, launch_xml, ament_index_python and yaml. A
    package.xml-only reading of the deps produces something that imports nothing.
    Anything that is not stdlib and not a known PyPI distribution is taken to be a ROS
    package, which in this corpus it always is; a wrong guess fails at solve time, which
    is where we want it to fail.

    Only *module-level* imports count. Imports inside a function body are how these
    packages express optional dependencies -- isaac_ros_manipulation_ros_python_utils
    reaches for the UR and Flexiv driver utilities that way, and both of those depend on
    it in turn, so treating a lazy import as a hard dependency would invent a cycle that
    does not exist.
    """
    found: set[str] = set()
    for root, dirs, files in os.walk(os.path.join(base, module)):
        dirs[:] = [d for d in dirs if d not in NOT_IMPORTED]
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            try:
                tree = ast.parse(open(p, encoding="utf-8", errors="replace").read())
            except SyntaxError as e:
                print(f"     note {name}: cannot parse {f} for imports ({e})")
                continue
            for node in tree.body:
                if isinstance(node, ast.Import):
                    found |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])

    out: list[str] = []
    for mod in sorted(found):
        # "" comes from relative imports (`from . import x`), which need nothing.
        if not mod or mod in sys.stdlib_module_names or mod in (module, "setuptools"):
            continue
        if mod in PY_IMPORTS:
            mapped = PY_IMPORTS[mod]
        elif mod in ROS_PY_IMPORTS:
            mapped = ROS_PY_IMPORTS[mod]
        elif mod in SYSTEM and SYSTEM[mod]:
            # The manifest path (deps_of) and the import path both map names, and without
            # this they disagree: isaac_ros_pynitros declares <exec_depend>posix_ipc, which
            # SYSTEM maps to conda-forge's posix_ipc, *and* imports posix_ipc from
            # utils/cpu_shared_mem.py, which fell through to ros_name() and invented
            # ros-jazzy-posix-ipc. Both landed in `run`, and the invented one does not exist,
            # so the test environment could not solve. One mapping table, consulted by both.
            mapped = SYSTEM[mod]
        else:
            mapped = ros_name(mod)
            if mapped == name:
                continue
            print(f"     note {name}: import '{mod}' assumed to be {mapped}")
        if mapped not in out:
            out.append(mapped)
    return out


def emit_python(name: str, repo: str, path: str, base: str, pkgxml: str,
                version: str, lic: str, summary: str) -> str:
    """Recipe for an <build_type>ament_python</build_type> package.

    These are setuptools projects whose data_files carry the ROS payload: the ament
    index marker, package.xml, and the launch/config/urdf trees. `pip install` places
    all of that correctly under $PREFIX, so no cmake or ament tooling is involved.

    Console scripts land in $PREFIX/bin rather than $PREFIX/lib/<pkg>/, which is where
    a rosdistro puts them. That is deliberate: it is what RoboStack's own ament_python
    packages do (checked against ros-jazzy-py-trees-ros), and matching the ecosystem we
    resolve against matters more than matching the upstream layout. The setup.cfg
    [install] install_scripts entry that would redirect them is a `setup.py install`
    setting and has no effect on a wheel build.
    """
    deps = deps_of(pkgxml, name)
    ros_dir = name.replace("ros-jazzy-", "").replace("-", "_")
    repo_info = REPOS[repo]
    has_module = os.path.isdir(os.path.join(base, ros_dir))

    # Several of these setup.py files import ament_index_python at *metadata* time to
    # locate isaac_ros_common's scripts directory, then run its version-info generator
    # as a build_py subcommand. That makes the ament index a build-time requirement, not
    # just a runtime one -- hence the host block below and the AMENT_PREFIX_PATH export.
    host = ["python", "pip", "setuptools"]
    setup_py = os.path.join(base, "setup.py")
    setup_src = (open(setup_py, encoding="utf-8", errors="replace").read()
                 if os.path.isfile(setup_py) else "")
    if "ament_index_python" in setup_src:
        # pyyaml is for isaac_ros_version_embed.py, which the generator shells out to.
        host += ["pyyaml", "ros-jazzy-ament-index-python"]
        for d in deps_of(pkgxml, name, kinds={"build_depend", "buildtool_depend"}):
            if d not in host:
                host.append(d)

    run = list(deps)
    if has_module:
        for d in py_run_deps(base, ros_dir, name):
            if d not in run:
                run.append(d)

    def block(items, indent=4):
        return "\n".join(f"{' ' * indent}- {i}" for i in items) or f"{' ' * indent}# none"

    # A pure-data package (urdf/srdf/config only) has no module to import.
    import_test = f"""
  - python:
      imports:
        - {ros_dir}
      pip_check: false""" if has_module else ""

    pats = PATCHES.get(name, [])
    patch_block = ("\n    patches:\n" + "\n".join(f"      - {x}" for x in pats)
                   if pats else "")

    return f"""schema_version: 1

# {name}, built FROM SOURCE against RoboStack.
#
# Generated by scripts/gen_source.py -- edit the generator, not this file.
# Source: {repo}/{path}
# Build type: ament_python (setuptools, installed with pip).

context:
  version: "{version}"

package:
  name: {name}
  version: ${{{{ version }}}}

source:
  - url: {repo_info['url']}
    sha256: {repo_info['sha256']}
    target_directory: src{patch_block}

build:
  number: {BUILD_NUMBERS.get(name, 0)}
  script:
    - export AMENT_PREFIX_PATH="${{PREFIX}}${{AMENT_PREFIX_PATH:+:${{AMENT_PREFIX_PATH}}}}"
    - cd src/{path}
    - ${{{{ PYTHON }}}} -m pip install . --no-deps --no-build-isolation -vv

requirements:
  host:
{block(host)}
  run:
    - python
{block(run)}

tests:
  - package_contents:
      files:
        - share/{ros_dir}/package.xml
        - share/ament_index/resource_index/packages/{ros_dir}{import_test}

about:
  homepage: {homepage_of(repo)}
  summary: {summary}
  license: {lic}
"""


def emit(name: str, repo: str, path: str) -> str | None:
    base = os.path.join(src_dir(repo), path)
    cml_p, pkg_p = os.path.join(base, "CMakeLists.txt"), os.path.join(base, "package.xml")
    if not os.path.isfile(pkg_p):
        print(f"  !! {name}: no package.xml at {path}")
        return None
    cml = open(cml_p, encoding="utf-8", errors="replace").read() if os.path.isfile(cml_p) else ""
    pkgxml = open(pkg_p, encoding="utf-8", errors="replace").read()

    version = (re.search(r"<version>([^<]+)</version>", pkgxml) or [None, "0"])[1].strip()
    lic_raw = (re.search(r"<license>([^<]+)</license>", pkgxml) or [None, "?"])[1].strip()
    lic = license_id(lic_raw)
    summary = re.sub(r"\s+", " ",
                     (re.search(r"<description>([\s\S]*?)</description>", pkgxml)
                      or [None, name])[1]).strip().strip('"')[:110] or name
    # A description with ": " in it is not a valid unquoted YAML scalar.
    summary = json.dumps(summary)

    if "<build_type>ament_python</build_type>" in pkgxml.replace(" ", ""):
        return emit_python(name, repo, path, base, pkgxml, version, lic, summary)

    traits = detect(cml, pkgxml, path)
    deps = deps_of(pkgxml, name)

    host = list(deps)
    for extra in EXTRA_HOST.get(name, []):
        if extra not in host:
            host.append(extra)
    for t in sorted(traits):
        for extra in TRAIT_DEPS[t]:
            if extra.endswith("# [build]"):
                continue
            if extra not in host:
                host.append(extra)

    build_tools = ["${{ compiler('c') }}", "${{ compiler('cxx') }}", "cmake", "ninja",
                   "pkg-config"]
    if path == "isaac_teleop_core":
        build_tools.append("git")
    if "cuda" in traits:
        # Most of these packages have no .cu sources, so nothing is compiled by nvcc.
        # The compiler is here for its activation script: it puts
        # $PREFIX/targets/<arch>/include on CXXFLAGS and exports the CMAKE_ARGS the
        # build script passes to cmake. Without it, find_package(CUDAToolkit) falls back
        # to /usr/local/cuda and silently compiles against the build machine's CUDA --
        # see README.md. Never a host dep. Requires cuda_compiler_version from
        # ../variants.yaml, or the build fails to resolve.
        build_tools.insert(2, "${{ compiler('cuda') }}")

    # Runtime deps: drop build-only tooling.
    #
    # eigen is deliberately not among them. It is header-only: the templates are compiled
    # into our .so and nothing loads eigen at runtime, so a run dependency only serves to
    # export our build-time Eigen choice into every consumer's solve. With the Eigen 3 pin
    # cuMotion needs (see TRAIT_DEPS) that made whole environments unsolvable --
    # isaac_ros_manipulation_gear_assembly wants cuMotion's object attachment *and*
    # ur_robot_driver, whose joint_trajectory_controller -> rsl chain requires eigen 5.
    run = [d for d in deps if not d.startswith(("ros-jazzy-ament-cmake", "ament_cmake"))
           and d not in ("ros-jazzy-rosidl-default-generators",)
           and not d.startswith("eigen")]
    if "rosidl" in traits and "ros-jazzy-rosidl-default-runtime" not in run:
        run.append("ros-jazzy-rosidl-default-runtime")
    if "vpi" in traits and "vpi" not in run:
        run.append("vpi")
    for extra in EXTRA_RUN.get(name, []):
        if extra not in run:
            run.append(extra)

    ros_dir = name.replace("ros-jazzy-", "").replace("-", "_")
    repo_info = REPOS[repo]

    def block(items, indent=4):
        return "\n".join(f"{' ' * indent}- {i}" for i in items) or f"{' ' * indent}# none"

    trait_note = (f"\n# Detected build traits: {', '.join(sorted(traits))}."
                  if traits else "\n# No special build traits detected.")

    pats = PATCHES.get(name, [])
    patch_block = ("    patches:\n" + "\n".join(f"      - {x}" for x in pats) + "\n"
                   if pats else "")
    ignored = IGNORE_RUN_EXPORTS.get(name, [])
    ignore_block = ("  ignore_run_exports:\n    by_name:\n" +
                    "\n".join(f"      - {x}" for x in ignored) + "\n"
                    if ignored else "")

    # See the asset note in detect(). The rewrite is a sed rather than a patch file
    # because five packages need the identical change; the grep in front of it is the
    # load-bearing part.
    #
    # The rewrite emits the install(PROGRAMS ...) as well as the resource registration, and
    # that is not redundant. Four of the five packages install the script themselves right
    # after the install_isaac_ros_asset() call, so for them it is a harmless duplicate
    # install of one file. nvblox_test_data does not -- its CMakeLists has only
    # install_isaac_ros_asset(quickstart) -- so registering the resource alone would leave
    # the ament index pointing at lib/nvblox_test_data/quickstart.sh, a file nothing ever
    # installs. A dangling resource is worse than a missing one: `ros2 run` fails with a
    # path that looks like it should work. Emitting both makes the resource true for all
    # five -- if upstream ever changes the call's shape, the sed would
    # silently not match and the build would go back to trying to download models at
    # build time, so assert the text is there first and fail loudly if it is not.
    # Source rewrites applied in the package directory before cmake runs. Each is
    # preceded by a grep asserting the text is present, which is the load-bearing part: a
    # sed that silently stops matching would quietly restore the broken behaviour, so the
    # build fails loudly instead if upstream changes shape.
    prep = ""
    if "eigenfloor" in traits:
        prep += (
            "\n    # See the eigenfloor note in scripts/gen_source.py: a versioned"
            "\n    # find_package(Eigen3 ...) in config mode rejects eigen 5 rather than"
            "\n    # accepting it, and NO_MODULE rules out the module-mode workaround."
            "\n    - grep -qE 'find_package\\(Eigen3 [0-9]' CMakeLists.txt"
            " || { echo 'versioned find_package(Eigen3) not found -- upstream changed"
            " shape, revisit gen_source.py'; exit 1; }"
            "\n    - sed -i -E 's|find_package\\(Eigen3 [0-9.]+|find_package(Eigen3|'"
            " CMakeLists.txt")

    for _line in EXTRA_PREP.get(name, []):
        prep += f"\n    - {_line}"

    assets = asset_names(cml) if "asset" in traits else []
    if assets:
        prep += (
            "\n    # See scripts/gen_source.py: install_isaac_ros_asset() would download"
            "\n    # model weights and run trtexec during the build. Keep the ament"
            "\n    # resource, drop the download -- assets belong on the target machine."
        )
        # One assertion per call, so a package that registers several -- as
        # isaac_ros_peoplesemseg_models_install does -- cannot lose one silently.
        for asset in assets:
            prep += (
                f"\n    - grep -q 'install_isaac_ros_asset({asset})' CMakeLists.txt"
                f" || {{ echo 'install_isaac_ros_asset({asset}) not found -- upstream changed"
                " shape, revisit gen_source.py'; exit 1; }")
        # One sed for all of them: the pattern is generic and sed substitutes once per
        # line, and upstream puts each call on its own line.
        prep += (
            "\n    - >"
            "\n      sed -i"
            " 's|install_isaac_ros_asset(\\([A-Za-z0-9_]*\\))"
            "|ament_index_register_resource(\"\\1\" CONTENT"
            " \"${CMAKE_INSTALL_PREFIX}/lib/${PROJECT_NAME}/\\1.sh\")\\n"
            "install(PROGRAMS asset_scripts/\\1.sh DESTINATION lib/${PROJECT_NAME})|'"
            "\n      CMakeLists.txt")

    # A passing build says the compiler was happy, not that the payload arrived. For the
    # asset packages the payload *is* the script plus its resource, and both come from the
    # rewrite above rather than from upstream, so assert them explicitly.
    test_files = list(EXTRA_TEST_FILES.get(name, []))
    for asset in assets:
        test_files += [
            f"lib/{ros_dir}/{asset}.sh",
            f"share/ament_index/resource_index/{asset}/{ros_dir}",
        ]
    extra_files = "".join(f"\n        - {f}" for f in test_files)

    # See EXTRA_SOURCES: submodule content the release tarball omits.
    extra_cmake = "".join(
        f"\n      {a}" for a in EXTRA_CMAKE_ARGS.get(name, []))

    extra_sources = "".join(
        f"  - url: {u}\n    sha256: {h}\n    target_directory: {d}\n"
        for u, h, d in EXTRA_SOURCES.get(name, []))

    return f"""schema_version: 1

# {name}, built FROM SOURCE against RoboStack.
#
# Generated by scripts/gen_source.py -- edit the generator, not this file.
# Source: {repo}/{path}{trait_note}

context:
  version: "{version}"

package:
  name: {name}
  version: ${{{{ version }}}}

source:
  - url: {repo_info['url']}
    sha256: {repo_info['sha256']}
    target_directory: src
{patch_block}{extra_sources}
build:
  number: {BUILD_NUMBERS.get(name, 0)}
  script:
    - export AMENT_PREFIX_PATH="${{PREFIX}}${{AMENT_PREFIX_PATH:+:${{AMENT_PREFIX_PATH}}}}"
    - export CMAKE_PREFIX_PATH="${{PREFIX}}${{CMAKE_PREFIX_PATH:+:${{CMAKE_PREFIX_PATH}}}}"
    - cd src/{path}{prep}
    # ${{CMAKE_ARGS}} carries the compiler activation's CMAKE_FIND_ROOT_PATH, which is
    # what points find_package(CUDAToolkit) at the prefix rather than /usr/local/cuda.
    - >
      cmake -S . -B build -G Ninja ${{CMAKE_ARGS:-}}
      -DCMAKE_BUILD_TYPE=Release
      -DCMAKE_INSTALL_PREFIX="${{PREFIX}}"
      -DCMAKE_PREFIX_PATH="${{PREFIX}}"
      -DCMAKE_CUDA_ARCHITECTURES="${{CUDA_ARCHITECTURES:-$(case "${{target_platform:-$(uname -m)}}" in linux-aarch64|aarch64) echo "87;110;120";; *) echo "80;86;89;90";; esac)}}"
      -DPYTHON_EXECUTABLE="${{PREFIX}}/bin/python"
      -DBUILD_TESTING=OFF{extra_cmake}
    - cmake --build build --parallel "${{CPU_COUNT:-2}}"
    - cmake --install build
    # No installed *text* file may name the build environment. $BUILD_PREFIX is unique to
    # this build and is deleted afterwards, and conda's relocation does not rewrite it --
    # only $PREFIX is a placeholder -- so such a reference breaks every consumer.
    #
    # Not hypothetical: nvblox_ros_common passes CUDAToolkit to
    # ament_target_dependencies(), which makes the toolkit's include directory INTERFACE, and
    # FindCUDAToolkit resolves it next to nvcc -- in BUILD_PREFIX. It went into the installed
    # export file, the package built and tested clean, and the failure surfaced only when
    # nvblox_ros used it: "includes non-existent path".
    #
    # Rewrite first: the CUDA headers exist at the same relative paths under both prefixes
    # (the compile line carries -I for both), so substituting the host prefix is correct
    # rather than merely quieting the check. Then fail on anything left.
    #
    # Text files only. Binaries legitimately still carry BUILD_PREFIX in their RPATH at this
    # point -- rattler-build's post-processing relocates them after this script runs -- so
    # including them would fail every package for a non-problem.
    - >
      find "${{PREFIX}}" -type f \\( -name '*.cmake' -o -name '*.pc' -o -name '*.sh'
      -o -name '*.dsv' -o -name '*.txt' -o -name '*.bash' -o -name '*.zsh' \\)
      -exec grep -lF "${{BUILD_PREFIX}}" {{}} + 2>/dev/null
      | xargs -r sed -i "s|${{BUILD_PREFIX}}|${{PREFIX}}|g"
    - >
      left=$(find "${{PREFIX}}" -type f \\( -name '*.cmake' -o -name '*.pc' -o -name '*.sh'
      -o -name '*.dsv' -o -name '*.txt' -o -name '*.bash' -o -name '*.zsh' \\)
      -exec grep -lF "${{BUILD_PREFIX}}" {{}} + 2>/dev/null | head -5);
      if [ -n "$left" ]; then echo "FAIL: installed text files still name BUILD_PREFIX:";
      echo "$left"; exit 1; fi
  dynamic_linking:
    missing_dso_allowlist:
      # GXF extensions live in sibling packages' share/ trees; cuVSLAM and the VPI
      # backends are dlopen'd or resolved through the ament index.
      - libgxf_*.so
      - libcuvslam.so
      - libcumotion.so*
      - libnvvpi.so.*

requirements:
  build:
{block(build_tools)}
  host:
{block(host)}
  run:
    - __glibc >=2.38
{block(run)}
{ignore_block}
tests:
  - package_contents:
      files:
        - share/{ros_dir}/package.xml{extra_files}

about:
  homepage: {homepage_of(repo)}
  summary: {summary}
  license: {lic}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    args = ap.parse_args()

    wanted = set(args.names) if args.names else None
    written = 0
    for name, repo, path in PACKAGES:
        if wanted and name not in wanted:
            continue
        if name in EXTERNAL:
            continue
        text = emit(name, repo, path)
        if text is None:
            continue
        d = os.path.join(RECIPES, name)
        os.makedirs(d, exist_ok=True)
        # Replace any repack recipe wholesale.
        for stale in ("build.sh", "relink.py"):
            p = os.path.join(d, stale)
            if os.path.exists(p):
                os.remove(p)
        with open(os.path.join(d, "recipe.yaml"), "w") as fh:
            fh.write(text)
        print(f"  + recipes/{name}")
        written += 1
    print(f"\ngenerated {written} source recipes")


if __name__ == "__main__":
    main()
