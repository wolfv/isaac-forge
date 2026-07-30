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

# Upstream tarballs. Everything NVIDIA is pinned to the v4.5-0 release tag; osrf's
# negotiated has no tags at all, so it is pinned to a commit.
REPOS = {
    "isaac_ros_nitros": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_nitros/archive/refs/tags/v4.5-0.tar.gz",
        sha256="a8814fd02843a1098d00173671f03115b3b3575aabb078be371a7f977ad1e5c2"),
    "isaac_ros_common": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_common/archive/refs/tags/v4.5-0.tar.gz",
        sha256="b7a2bb09bad33c3654750a412c2c902064e8256088e1b1391ecd1dbcd803d0f7"),
    "isaac_ros_image_pipeline": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_image_pipeline/archive/refs/tags/v4.5-0.tar.gz",
        sha256="66a0ea87a075c4eb428faa4b987768928ae0250e6ab801db4bcbeef8fa8924b1"),
    "isaac_ros_visual_slam": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/archive/refs/tags/v4.5-0.tar.gz",
        sha256="8708fb6b016138483d24e785fa8549243839fe312d63786df2bba8840b5703f9"),
    "isaac_ros_benchmark": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_benchmark/archive/refs/tags/v4.5-0.tar.gz",
        sha256="3f37f7d22571a43f58b9a701940e8ee12c001f753fd5637be1e6d78a4bee1721"),
    "ros2_benchmark": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/ros2_benchmark/archive/refs/tags/v4.5-0.tar.gz",
        sha256="9077a56c57337a7d34a5da1068d06e9b2ed550180e8566012e93f6f6dd1d4d63"),
    "isaac_ros_manipulation": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_manipulation/archive/refs/tags/v4.5-0.tar.gz",
        sha256="00d45ee0c52efe40688d90958538092c713ad1eec0fe62befcdfe74a1c33225f"),
    "isaac_ros_cumotion": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_cumotion/archive/refs/tags/v4.5-0.tar.gz",
        sha256="3ef770f800665ad25569291f935ef8c47f752a301575aaca1c26df5199c2b520"),
    "isaac_ros_image_segmentation": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_image_segmentation/archive/refs/tags/v4.5-0.tar.gz",
        sha256="4ef02550da5192b6d31566e992e2cbf06b2c35b43d7605a53d1eba4a0f28bd1b"),
    "isaac_ros_pose_estimation": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_pose_estimation/archive/refs/tags/v4.5-0.tar.gz",
        sha256="7e6855053fbc1e9af5683c36e6e5642e2d5db9de8783753371ddeb4c565aee13"),
    "isaac_ros_dnn_inference": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_dnn_inference/archive/refs/tags/v4.5-0.tar.gz",
        sha256="e19397a4f685fffc66cd68d1a8489fc2939878ea6299c376d04ab5d19c09ce06"),
    "isaac_ros_object_detection": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_object_detection/archive/refs/tags/v4.5-0.tar.gz",
        sha256="349b78dcdbd22c019f982d343c65bd690d4affcdf8aca85183b1505943962098"),
    "negotiated": dict(
        url="https://github.com/osrf/negotiated/archive/"
            "eac198b55dcd052af5988f0f174902913c5f20e7.tar.gz",
        sha256="01aed43adef3e6ef3d9e1879d3a2910d6acdcf802e6ea2905ab4626e21d7af05",
        homepage="https://github.com/osrf/negotiated"),
    "isaac_ros_nvblox": dict(
        url="https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_nvblox/archive/refs/tags/v4.5-0.tar.gz",
        sha256="4a668d140bec4df889f1b1a0a1059d841c19546ec8ac7e26de830a694fc855b8"),
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
    # small libraries
    ("ros-jazzy-isaac-common", "isaac_ros_common", "isaac_common"),
    ("ros-jazzy-gxf-isaac-gems", "isaac_ros_nitros", "isaac_ros_gxf_extensions/gxf_isaac_gems"),
    # NITROS type adapters -- thin wrappers over the core
    ("ros-jazzy-isaac-ros-nitros-std-msg-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_std_msg_type"),
    ("ros-jazzy-isaac-ros-nitros-image-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_image_type"),
    ("ros-jazzy-isaac-ros-nitros-camera-info-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_camera_info_type"),
    ("ros-jazzy-isaac-ros-nitros-tensor-list-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_tensor_list_type"),
    ("ros-jazzy-isaac-ros-nitros-compressed-image-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_compressed_image_type"),
    ("ros-jazzy-isaac-ros-nitros-disparity-image-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_disparity_image_type"),
    ("ros-jazzy-isaac-ros-nitros-point-cloud-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_point_cloud_type"),
    ("ros-jazzy-isaac-ros-nitros-detection2-d-array-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_detection2_d_array_type"),
    ("ros-jazzy-isaac-ros-nitros-detection3-d-array-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_detection3_d_array_type"),
    ("ros-jazzy-isaac-ros-nitros-flat-scan-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_flat_scan_type"),
    ("ros-jazzy-isaac-ros-nitros-imu-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_imu_type"),
    ("ros-jazzy-isaac-ros-nitros-occupancy-grid-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_occupancy_grid_type"),
    ("ros-jazzy-isaac-ros-nitros-pose-cov-stamped-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_pose_cov_stamped_type"),
    ("ros-jazzy-isaac-ros-managed-nitros", "isaac_ros_nitros", "isaac_ros_managed_nitros"),
    # utility libraries over NITROS
    ("ros-jazzy-isaac-ros-vpi-utils", "isaac_ros_image_pipeline", "isaac_ros_vpi_utils"),
    ("ros-jazzy-isaac-ros-cvcuda-utils", "isaac_ros_image_pipeline", "isaac_ros_cvcuda_utils"),
    # benchmark harness
    ("ros-jazzy-ros2-benchmark", "ros2_benchmark", "ros2_benchmark"),
    ("ros-jazzy-isaac-ros-benchmark", "isaac_ros_benchmark", "isaac_ros_benchmark"),
    ("ros-jazzy-isaac-ros-image-proc-benchmark", "isaac_ros_benchmark", "benchmarks/isaac_ros_image_proc_benchmark"),
    # --- the manipulation stack ------------------------------------------------
    # Interfaces it needs from sibling repos, then the manipulation packages
    # themselves. isaac_ros_manipulation_bringup and _asset_bringup are absent on
    # purpose: their closure is the entire DNN + nvblox stack, which needs TensorRT
    # and Triton. See README.md.
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
    ("ros-jazzy-isaac-ros-manipulation-interfaces", "isaac_ros_manipulation", "isaac_ros_manipulation_interfaces"),
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
    ("ros-jazzy-isaac-ros-manipulation-test-utils", "isaac_ros_manipulation", "isaac_ros_manipulation_test_utils"),
    ("ros-jazzy-isaac-ros-manipulation-ur-isaac-sim-utils", "isaac_ros_manipulation", "isaac_ros_manipulation_robots/isaac_ros_manipulation_ur_isaac_sim_utils"),
    ("ros-jazzy-isaac-ros-manipulation-ros-python-utils", "isaac_ros_manipulation", "isaac_ros_manipulation_ros_python_utils"),
    ("ros-jazzy-isaac-ros-manipulation-object-following", "isaac_ros_manipulation", "isaac_ros_manipulation_object_following"),
    ("ros-jazzy-isaac-ros-manipulation-pose-to-pose", "isaac_ros_manipulation", "isaac_ros_manipulation_pose_to_pose"),
    ("ros-jazzy-isaac-ros-manipulation-robot-utils", "isaac_ros_manipulation", "isaac_ros_manipulation_robots/isaac_ros_manipulation_robot_utils"),
    ("ros-jazzy-isaac-ros-manipulation-ur-robot-description", "isaac_ros_manipulation", "isaac_ros_manipulation_robots/isaac_ros_manipulation_ur_robot_description"),
    ("ros-jazzy-isaac-ros-manipulation-flexiv-robot-description", "isaac_ros_manipulation", "isaac_ros_manipulation_robots/isaac_ros_manipulation_flexiv_robot_description"),
    ("ros-jazzy-isaac-ros-manipulation-ur-driver-utils", "isaac_ros_manipulation", "isaac_ros_manipulation_robots/isaac_ros_manipulation_ur_driver_utils"),
    ("ros-jazzy-isaac-ros-manipulation-orchestration", "isaac_ros_manipulation", "isaac_ros_manipulation_orchestration"),
    ("ros-jazzy-isaac-ros-manipulation-pick-and-place", "isaac_ros_manipulation", "isaac_ros_manipulation_pick_and_place"),
    # C++ / rosidl on top of the python utilities
    ("ros-jazzy-isaac-ros-manipulation-servers", "isaac_ros_manipulation", "isaac_ros_manipulation_servers"),
    ("ros-jazzy-isaac-ros-manipulation-dnn-policy", "isaac_ros_manipulation", "isaac_ros_manipulation_dnn_policy"),
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
    ("ros-jazzy-isaac-ros-cumotion-robot-description", "isaac_ros_cumotion", "isaac_ros_cumotion_robot_description"),
    ("ros-jazzy-isaac-ros-cumotion", "isaac_ros_cumotion", "isaac_ros_cumotion"),
    ("ros-jazzy-isaac-ros-cumotion-object-attachment", "isaac_ros_cumotion", "isaac_ros_cumotion_object_attachment"),
    # Needs cuMotion's object attachment and the Robotiq gripper controller, so it comes
    # after both.
    ("ros-jazzy-isaac-ros-manipulation-gear-assembly", "isaac_ros_manipulation", "isaac_ros_manipulation_gear_assembly"),
    # Last of the manipulation packages: it needs isaac_ros_cumotion_moveit, so it only
    # became reachable once cuMotion built against eigen 5.
    ("ros-jazzy-isaac-ros-manipulation-flexiv-driver-utils", "isaac_ros_manipulation", "isaac_ros_manipulation_robots/isaac_ros_manipulation_flexiv_driver_utils"),
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
    # already built here. isaac_ros_tensor_rt and isaac_ros_triton are the two that are
    # genuinely blocked and are absent on purpose.
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
    # The backend every DNN pipeline above actually defaults to, unblocked by
    # recipes/tensorrt (10.13.3.9, repacked from NVIDIA's CUDA apt repo with their
    # permission -- see that recipe for why 10.13/cuda13 rather than the 10.9/cuda12.8
    # Isaac ships against).
    #
    # isaac_ros_triton, its sibling in the same repo, is still absent and not for want of
    # trying: its CMakeLists defaults x86_64 to a tarball on artifactory.pdx.nvidia.com,
    # which is internal and does not resolve, and no public x86_64 Triton server tarball
    # exists to override it with. See ISSUES.md #21.
    ("ros-jazzy-isaac-ros-tensor-rt", "isaac_ros_dnn_inference", "isaac_ros_tensor_rt"),
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
    # same LFS trap README.md documents for isaac_ros_nitros, which is solved there by
    # filling the pointers from the deb; for these it is cheaper to repack outright.
    ("ros-jazzy-isaac-ros-apriltag-interfaces", "isaac_ros_common", "isaac_ros_apriltag_interfaces"),
    ("ros-jazzy-isaac-ros-nova-interfaces", "isaac_ros_common", "isaac_ros_nova_interfaces"),
    ("ros-jazzy-isaac-ros-test-cmake", "isaac_ros_common", "isaac_ros_test_cmake"),
    ("ros-jazzy-isaac-ros-nitros-odometry-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_odometry_type"),
    ("ros-jazzy-isaac-ros-nitros-pose-array-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_pose_array_type"),
    ("ros-jazzy-isaac-ros-nitros-twist-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_twist_type"),
    ("ros-jazzy-isaac-ros-nitros-compressed-video-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_compressed_video_type"),
    ("ros-jazzy-isaac-ros-nitros-battery-state-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_battery_state_type"),
    ("ros-jazzy-isaac-ros-nitros-correlated-timestamp-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_correlated_timestamp_type"),
    ("ros-jazzy-isaac-ros-nitros-encoder-ticks-type", "isaac_ros_nitros", "isaac_ros_nitros_type/isaac_ros_nitros_encoder_ticks_type"),
    ("ros-jazzy-isaac-ros-nitros-topic-tools", "isaac_ros_nitros", "isaac_ros_nitros_topic_tools"),
    ("ros-jazzy-isaac-ros-pynitros", "isaac_ros_nitros", "isaac_ros_pynitros"),
    ("ros-jazzy-isaac-ros-nitros-bridge-ros2", "isaac_ros_nitros", "isaac_ros_nitros_bridge/isaac_ros_nitros_bridge_ros2"),
    ("ros-jazzy-isaac-ros-stereo-image-proc", "isaac_ros_image_pipeline", "isaac_ros_stereo_image_proc"),
    ("ros-jazzy-isaac-ros-depth-image-proc", "isaac_ros_image_pipeline", "isaac_ros_depth_image_proc"),
    ("ros-jazzy-isaac-ros-image-pipeline", "isaac_ros_image_pipeline", "isaac_ros_image_pipeline"),
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
    # Pinned, and the floor is load-bearing rather than cosmetic. conda-forge's
    # libcvcuda-dev 0.16 ships lib/cmake/{cvcuda,nvcv_types}/*-config.cmake; the 0.14
    # deb repack this repo used before it (still sitting in some output/ trees) ships
    # only headers and two .so symlinks. isaac_ros_foundationpose is the first package
    # here to call find_package(nvcv_types REQUIRED) rather than naming the libraries
    # directly, so with the older one in a local channel -- which outranks conda-forge --
    # it fails at configure with "Could not find a package configuration file provided
    # by nvcv_types". Say the version, so an unindexed leftover cannot win.
    "cvcuda": ["libcvcuda >=0.16", "libcvcuda-dev >=0.16"],
    # Compiled against directly, through isaac_ros_gxf's expected_macro.hpp. It also
    # arrives transitively as a run dep of ros-jazzy-isaac-ros-gxf, but relying on that is
    # what kept the include-path problem invisible -- declare it, and see the magicenum
    # note in detect() for why the include directory has to be stated too.
    "magicenum": ["magic_enum"],
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
}

# Patches applied to a package's source, keyed by conda package name; paths are relative
# to the recipe directory. All but one are prepared for upstream; the exception says so in
# its own commit message, and the reason it cannot go upstream is that the code that needs
# fixing is under NVIDIA's proprietary header.
PATCHES = {
    # Explicit specializations of a variable template are not implicitly inline, so
    # epsilon.hpp produces multiple definitions of MachineEpsilon<float|double> in any
    # target with two TUs including it. Breaks
    # isaac_ros_nitros_detection3_d_array_type at link time under GCC 15.
    # Apache-2.0, so ours to fix; see ISSUES.md and upstream/README.md.
    "ros-jazzy-gxf-isaac-gems": ["patches/0001-epsilon-odr-inline.patch"],
    # test_utils.py raises at module scope when ISAAC_ROS_WS is unset, and __init__.py
    # re-exports it, so importing the package fails in any environment that does not
    # export that variable -- which is every conda environment. Apache-2.0, ours to fix;
    # see ISSUES.md.
    "ros-jazzy-isaac-ros-manipulation-ros-python-utils": [
        "patches/0001-defer-isaac-ros-ws-check.patch"],
    # Demote the inference backends from <depend> to <exec_depend>. Neither decoder
    # includes a header from them; declaring them as build dependencies is what makes
    # ament_auto_find_build_dependencies require TensorRT (and, for centerpose, Triton) to
    # configure a package that only does PnP. See ISSUES.md.
    "ros-jazzy-isaac-ros-dope": [
        "patches/0001-tensor-rt-is-a-runtime-dependency.patch"],
    "ros-jazzy-isaac-ros-centerpose": [
        "patches/0001-tensor-rt-and-triton-are-runtime-dependencies.patch"],
}

# Files a package must ship beyond share/<pkg>/package.xml, checked declaratively at the
# end of the build. Worth listing wherever a specific file is the reason the package
# exists, or wherever a patch is what puts it there -- a passing build says the compiler
# was happy, not that the payload arrived.
EXTRA_TEST_FILES = {
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
    if declared.strip() in ("BSD", "BSD-3-Clause"):
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
    # Anything that includes a NITROS type header ends up compiling
    # isaac_ros_gxf's gxf/core/expected_macro.hpp, which does
    #
    #     #include "magic_enum.hpp"
    #
    # NVIDIA's ros-jazzy-magic-enum deb puts that header at the top of an include dir;
    # conda-forge's magic_enum puts it in include/magic_enum/, and its CMake package
    # exports only a target, no *_INCLUDE_DIRS variable. So the directory reaches a
    # consumer only if the consumer links magic_enum::magic_enum through isaac_ros_gxf's
    # imported target -- and a package that picks the gxf headers up through ament
    # include dirs instead does not. isaac_ros_tensor_proc is that case, and it fails with
    # `expected_macro.hpp:24: fatal error: magic_enum.hpp: No such file or directory`.
    # ros-jazzy-isaac-ros-h264-decoder hit this first and fixes it by hand in its
    # build.sh; this is the same two lines, decided from the manifest instead.
    if re.search(r"isaac_ros_(gxf|nitros)", pkgxml):
        traits.add("magicenum")
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


def asset_name(cml: str) -> str | None:
    """The asset registered by install_isaac_ros_asset(), which is also its script name."""
    m = re.search(r"install_isaac_ros_asset\(\s*([A-Za-z0-9_]+)\s*\)", cml)
    return m.group(1) if m else None


# package.xml uses bare rosdep keys, not deb names, so a second mapping layer is
# needed on top of gen_repack's MAP. Anything not listed here and not obviously a
# system package is assumed to be a ROS package and gets the ros-jazzy- prefix.
SYSTEM = {
    "cuda-toolkit": "cuda-version 13.*",
    # recipes/tensorrt -- the conda package name matches gen_repack's MAP for libnvinfer10.
    "tensorrt": "tensorrt",
    "eigen": "eigen",
    "eigen3": "eigen",
    "yaml-cpp": "yaml-cpp",
    "boost": "libboost-devel",
    "libopencv-dev": "libopencv 4.13.*",
    "magic_enum": "magic_enum",
    "nlohmann_json": "nlohmann_json",
    "python3-numpy": "numpy",
    "python3-pytest": None,
    "python3-opencv": "py-opencv",
    "python3-matplotlib": "matplotlib-base",
    "python3-scipy": "scipy",
    "libgflags-dev": "gflags",
    "libgoogle-glog-dev": "glog",
    "assimp": "assimp",
    "tl_expected": "tl-expected",
    "benchmark": "benchmark",
    "posix_ipc": "posix_ipc",
    "git": None,
    "iputils-ping": None,
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
        elif dep.startswith(("python3-", "lib")) or "-" in dep:
            # An unrecognised system-looking key: skip rather than invent a ROS
            # package that does not exist, and let the build tell us if it mattered.
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
    "torch": "pytorch",
    "psutil": "psutil",
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
  number: 0
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
    for t in sorted(traits):
        for extra in TRAIT_DEPS[t]:
            if extra.endswith("# [build]"):
                continue
            if extra not in host:
                host.append(extra)

    build_tools = ["${{ compiler('c') }}", "${{ compiler('cxx') }}", "cmake", "ninja",
                   "pkg-config"]
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

    ros_dir = name.replace("ros-jazzy-", "").replace("-", "_")
    repo_info = REPOS[repo]

    def block(items, indent=4):
        return "\n".join(f"{' ' * indent}- {i}" for i in items) or f"{' ' * indent}# none"

    trait_note = (f"\n# Detected build traits: {', '.join(sorted(traits))}."
                  if traits else "\n# No special build traits detected.")

    pats = PATCHES.get(name, [])
    patch_block = ("    patches:\n" + "\n".join(f"      - {x}" for x in pats)
                   if pats else "")

    # See the asset note in detect(). The rewrite is a sed rather than a patch file
    # because four packages need the identical change; the grep in front of it is the
    # load-bearing part -- if upstream ever changes the call's shape, the sed would
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

    asset = asset_name(cml) if "asset" in traits else None
    if asset:
        prep += (
            "\n    # See scripts/gen_source.py: install_isaac_ros_asset() would download"
            "\n    # model weights and run trtexec during the build. Keep the ament"
            "\n    # resource, drop the download -- assets belong on the target machine."
            f"\n    - grep -q 'install_isaac_ros_asset({asset})' CMakeLists.txt"
            f" || {{ echo 'install_isaac_ros_asset({asset}) not found -- upstream changed"
            # Not an f-string fragment, so a literal single brace -- doubling it here
            # emitted `}}` and made the build script a shell syntax error.
            " shape, revisit gen_source.py'; exit 1; }"
            "\n    - >"
            "\n      sed -i"
            " 's|install_isaac_ros_asset(\\([A-Za-z0-9_]*\\))"
            "|ament_index_register_resource(\"\\1\" CONTENT"
            " \"${CMAKE_INSTALL_PREFIX}/lib/${PROJECT_NAME}/\\1.sh\")|'"
            "\n      CMakeLists.txt")

    # A passing build says the compiler was happy, not that the payload arrived. For the
    # asset packages the payload *is* the script plus its resource, and both come from the
    # rewrite above rather than from upstream, so assert them explicitly.
    test_files = list(EXTRA_TEST_FILES.get(name, []))
    if asset:
        test_files += [
            f"lib/{ros_dir}/{asset}.sh",
            f"share/ament_index/resource_index/{asset}/{ros_dir}",
        ]
    extra_files = "".join(f"\n        - {f}" for f in test_files)

    # See the magicenum note in detect(): the host dep alone is not enough, because
    # conda-forge's magic_enum nests the header one directory deeper than the
    # `#include "magic_enum.hpp"` in isaac_ros_gxf expects to find it. That bare-name
    # include is ISSUES.md #17; this is the consumer-side half of it.
    magic_enum_include = (
        '\n    - export CXXFLAGS="${CXXFLAGS:-} -I${PREFIX}/include/magic_enum"'
        # CMake seeds CMAKE_CUDA_FLAGS from CUDAFLAGS the way it seeds CMAKE_CXX_FLAGS from
        # CXXFLAGS, and nvcc does not otherwise see the C++ one. Needed wherever a .cu source
        # includes a GXF header -- isaac_ros_depth_image_proc is the first such package here,
        # and CXXFLAGS alone left it failing on magic_enum.hpp in depth_to_point_cloud_cuda.cu.
        '\n    - export CUDAFLAGS="${CUDAFLAGS:-} -I${PREFIX}/include/magic_enum"'
        if "magicenum" in traits else "")

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
{patch_block}
build:
  number: 0
  script:
    - export AMENT_PREFIX_PATH="${{PREFIX}}${{AMENT_PREFIX_PATH:+:${{AMENT_PREFIX_PATH}}}}"
    - export CMAKE_PREFIX_PATH="${{PREFIX}}${{CMAKE_PREFIX_PATH:+:${{CMAKE_PREFIX_PATH}}}}"{magic_enum_include}
    - cd src/{path}{prep}
    # ${{CMAKE_ARGS}} carries the compiler activation's CMAKE_FIND_ROOT_PATH, which is
    # what points find_package(CUDAToolkit) at the prefix rather than /usr/local/cuda.
    - >
      cmake -S . -B build -G Ninja ${{CMAKE_ARGS:-}}
      -DCMAKE_BUILD_TYPE=Release
      -DCMAKE_INSTALL_PREFIX="${{PREFIX}}"
      -DCMAKE_PREFIX_PATH="${{PREFIX}}"
      -DCMAKE_CUDA_ARCHITECTURES="80;86;89;90"
      -DPYTHON_EXECUTABLE="${{PREFIX}}/bin/python"
      -DBUILD_TESTING=OFF
    - cmake --build build --parallel "${{CPU_COUNT:-2}}"
    - cmake --install build
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
