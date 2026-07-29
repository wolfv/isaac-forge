#!/usr/bin/env bash
# Run NVIDIA's cuMotion planner node against the UR5e + Robotiq 2F-85 description it
# ships, and ask it to solve inverse kinematics on the GPU.
#
# This is the real test of the cuMotion packaging. The planner node links
# libcumotion.so, parses NVIDIA's URDF and XRDF, builds the collision-sphere model,
# initializes the trajectory optimizer and IK solver on the device, and answers an action
# request -- none of which happens if the library, its Eigen ABI or its CUDA runtime are
# wrong.
set -euo pipefail

# Off the default domain so a stray container from another experiment cannot answer.
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-73}"
SHARE="${CONDA_PREFIX}/share/isaac_ros_cumotion_robot_description"
LOG="$(mktemp -t cumotion-XXXXXX.log)"

ros2 run rclcpp_components component_container > "${LOG}" 2>&1 &
CONTAINER=$!
cleanup() { kill "${CONTAINER}" 2>/dev/null || true; wait "${CONTAINER}" 2>/dev/null || true; }
trap cleanup EXIT

for _ in $(seq 1 40); do
  ros2 component list >/dev/null 2>&1 && break
  sleep 0.5
done

# The planner blocks on this service during construction, so it has to exist first.
ros2 component load /ComponentManager isaac_ros_cumotion \
  nvidia::isaac_ros::cumotion::StaticPlanningSceneServer | tail -1

# read_esdf_world is off: with it on the planner waits for nvblox's ESDF service, and
# nvblox is not packaged yet.
ros2 component load /ComponentManager isaac_ros_cumotion \
  nvidia::isaac_ros::cumotion::CumotionPlanner \
  -p urdf_file_path:="${SHARE}/urdf/ur5e_robotiq_2f_85.urdf" \
  -p xrdf_file_path:="${SHARE}/xrdf/ur5e_robotiq_2f_85.xrdf" \
  -p read_esdf_world:=false \
  -p update_esdf_on_request:=false | tail -1

sleep 2
echo
echo "action servers:"
ros2 action list | sed 's/^/  /'
echo
echo "IK request: gripper 40 cm out, 10 cm across, 30 cm up, tool pointing down"
ros2 action send_goal /cumotion/ik isaac_ros_cumotion_interfaces/action/IKSolution \
"{goal_pose: {position: {x: 0.4, y: 0.1, z: 0.3},
              orientation: {x: 1.0, y: 0.0, z: 0.0, w: 0.0}},
  world_frame: 'base_link',
  num_solutions_to_return: 1,
  seed_state: {name: [shoulder_pan_joint, shoulder_lift_joint, elbow_joint,
                      wrist_1_joint, wrist_2_joint, wrist_3_joint],
               position: [0.0, -1.57, 1.57, -1.57, -1.57, 0.0]}}"

echo
echo "planner log (collision-mask warnings elided):"
grep -vE "self-collision mask|^$" "${LOG}" | tail -12
