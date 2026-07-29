# `manip/` — the Isaac ROS manipulation stack, resolved and run

Sixteen of the eighteen packages in
[NVIDIA-ISAAC-ROS/isaac_ros_manipulation](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_manipulation),
plus the cuMotion layer underneath them, installed into one conda environment resolved
only from `../output` + `robostack-jazzy` + `conda-forge`.

```bash
cd manip
pixi run check      # imports, ament index, dlopen every C++ component
pixi run ik         # cuMotion solves inverse kinematics on the GPU
pixi run fk J1 ... J6   # check a returned solution with independent forward kinematics
```

## What `pixi run check` proves

That the environment *solves* is itself a result: 16 manipulation packages, cuMotion
including its MoveIt planner plugin, the UR driver stack, moveit's python utilities and
py_trees are mutually consistent. On top of that:

| | |
|---|---|
| python modules importing cleanly | 12 |
| generated action types | `PickAndPlace`, `MotionPlan` |
| packages visible to `ros2 pkg list` | 21 |
| C++ composable nodes dlopened into a live container | 3 |

The dlopen step is the one that matters. The python packages are data plus imports and
fail loudly; the C++ ones link `libcumotion.so`, and a wrong ABI there stays invisible
until something calls `dlopen`.

`isaac_ros_manipulation_servers` registers six components —
`ObjectDetectionServer`, `FoundationPoseServer`, `DopeServer`, `ObjectInfoServer`,
`ObjectSelectionServer`, `SegmentAnythingServer`. Two are loaded here; the other four
construct DNN clients that need TensorRT or Triton, which are not packaged yet.

## What `pixi run ik` proves

cuMotion runs. The planner node loads NVIDIA's own UR5e + Robotiq 2F-85 description from
`isaac_ros_cumotion_robot_description`, builds the robot model, and answers an action
request:

```
Loaded component 2 into '/ComponentManager' container node as '/cumotion_action_server'
action servers:
  /cumotion/ik
  /cumotion/motion_plan
  /cumotion/move_group

[cumotion_action_server]: Initializing TrajectoryOptimizerImpl
[cumotion_action_server]: TrajectoryOptimizerImpl initialized successfully
[cumotion_action_server]: Initializing IkSolverImpl
[cumotion_action_server]: IkSolverImpl initialized successfully
[cumotion_action_server]: Received IK request
[cumotion_action_server]: IK succeeded with 26 solutions

Goal finished with status: SUCCEEDED
```

**26 IK solutions** for a 6-DOF arm with a gripper, from NVIDIA's `libcumotion.so.1.1.0` as
shipped, running on the local GPU inside a conda environment on Fedora. The reported
`planning_time` ranges from **17 ms to 155 ms** across runs of the same binary — the solve
itself is the low end, and the spread is GPU work on the first call after the node comes up,
not something this packaging controls.

And the answer is right, not just present. `fk_check.py` parses the same URDF, composes the
joint transforms with numpy — no ROS, no KDL, no MoveIt, so agreement means something — and
recomputes where the gripper ends up:

```console
$ pixi run fk -0.08417 -1.702348 2.191254 -2.059429 -1.571057 -1.654926
fk(gripper_frame)[ 0.400000  0.100000  0.300000]
goal          [ 0.400000  0.100000  0.300000]
position err  0.000 mm
tool +Z       [-0.0003 -0.0002 -1.0000]   (goal: [0 0 -1], dot =  1.000000)
```

That check is what makes the Eigen 5 decision defensible rather than hopeful: cuMotion is
compiled here against **Eigen 5.0.1** and linked against NVIDIA's **Eigen 3** library. An
Eigen 3.4 build of the same stack returns a different one of the 26 branches, 0.026 mm out.
Both are correct; see `ISSUES.md` #13.

Along the way the node parses the XRDF, applies per-link collision buffers and reports the
self-collision masks it cannot honour (`attached_object` has no spheres until something
attaches an object) — normal startup chatter, not packaging damage.

## The two packages that are not here

| package | why |
|---|---|
| `isaac_ros_manipulation_bringup` | closure is the whole DNN + nvblox stack: TensorRT, Triton, FoundationPose, ESS, RT-DETR, SegmentAnything, nvblox |
| `isaac_ros_manipulation_asset_bringup` | same, minus nvblox — it is the model-download and TensorRT-engine-build package |

Both are a matter of packaging more of Isaac ROS, and both are waiting on the same thing:
TensorRT.

`isaac_ros_manipulation_flexiv_driver_utils` was on this list until `isaac_ros_cumotion_moveit`
became buildable — see the Eigen note above.

## Notes

- `ROS_DOMAIN_ID` defaults to 73 in `ik.sh` so a container left running from another
  experiment on the default domain cannot answer the action call.
- `read_esdf_world` is turned off. With it on, the planner waits for nvblox's
  `get_esdf_and_gradient` service and times out after 30 s, because nvblox is not packaged
  yet. Collision-aware planning against a live 3D reconstruction needs that service; IK
  and free-space planning do not.
- The planner also blocks during construction on `publish_static_planning_scene`, which
  is served by a *second* component in the same package
  (`StaticPlanningSceneServer`). Loading the planner alone always fails; `ik.sh` loads
  both, in order.
