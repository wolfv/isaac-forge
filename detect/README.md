# `detect/` — the Isaac ROS object-detection stack

All **eight** packages in
[`NVIDIA-ISAAC-ROS/isaac_ros_object_detection`](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_object_detection)
at `v4.5-0`, built from source against RoboStack. Six composable nodes, all loading.

```bash
cd detect && pixi run check
```

```
C++ components (dlopen into a live container) -- 6 to load
  ok    load DetectNetDecoderNode
  ok    load YoloV8DecoderNode
  ok    load RtDetrPreprocessorNode (memory_pool_num_blocks:=1, ...)
  ok    load RtDetrDecoderNode
  ok    load GroundingDinoPreprocessorNode
  ok    load GroundingDinoDecoderNode
all checks passed
```

| package | contributes | components |
|---|---|---|
| `isaac_ros_rtdetr` | RT-DETR preprocessor + decoder | 2 |
| `isaac_ros_grounding_dino` | open-vocabulary detection, `SetPrompt`/`GetTextTokens` services | 2 |
| `isaac_ros_yolov8` | YOLOv8 decoder | 1 |
| `isaac_ros_detectnet` | DetectNet decoder | 1 |
| `isaac_ros_grounding_dino_interfaces` | 3 services | — |
| `isaac_ros_rtdetr_models_install` | NGC asset script | — |
| `isaac_ros_grounding_dino_models_install` | NGC asset script | — |
| `isaac_ros_peoplenet_models_install` | NGC asset script | — |

## The manifests were already right here

`packages.json` marks four of the eight blocked on `tensorrt`. Unlike
`isaac_ros_pose_estimation`, that needed **no patches to disprove** — every package in this
repo already declares its inference backend correctly:

```xml
<!-- isaac_ros_rtdetr, isaac_ros_yolov8, isaac_ros_grounding_dino -->
<exec_depend>isaac_ros_tensor_rt</exec_depend>

<!-- isaac_ros_detectnet -->
<test_depend>isaac_ros_triton</test_depend>
```

`<exec_depend>` and `<test_depend>` are invisible to
`ament_auto_find_build_dependencies()`, so nothing about TensorRT or Triton runs at
configure time, and `grep -rn 'NvInfer\|nvinfer\|triton'` over every `src/` and `include/`
tree in the repo returns nothing. The blocker label is an artefact of reading manifests
without distinguishing dependency kind — the same measurement error that made four of the
five pose-estimation packages look unreachable, where two of them genuinely *were* blocked
by a `<depend>` that should have been an `<exec_depend>` (`ISSUES.md` #18).

What TensorRT still gates is the **pipelines**. These are decoders: they consume the tensor
output of an inference node and turn it into `Detection2DArray`. They load and construct
without one — that is what `pixi run check` establishes — but a detection graph needs
`isaac_ros_tensor_rt` in the middle. As with `pose/`, this directory proves packaging, not
a working demo.

## Two generator rules came out of this

Both replace what would have been piles of near-identical patch files, and both are used
by `pose/` too.

**The asset rule.** Three packages here (and `isaac_ros_foundationpose_models_install`)
call `install_isaac_ros_asset()`, which dry-runs its asset script at configure time —
needing `$ISAAC_ROS_WS`, so it aborts — and then makes the default build target download
model weights from NGC and run `trtexec` over them. That last part should not happen in a
binary package regardless: an engine plan is specialised to the GPU, driver and TensorRT
version that produced it. `scripts/gen_source.py` now detects the call and rewrites it to
register the ament resource without the download, leaving the models to the target system:

```bash
ros2 run isaac_ros_rtdetr_models_install install_rtdetr_models.sh
```

`ISSUES.md` #20. `check.py` asserts the script and its resource for all three, because
they *are* the package — nothing else would notice if the rewrite stopped matching.

**The Eigen floor rule.** `find_package(Eigen3 3.3 REQUIRED NO_MODULE)` appears verbatim
in **18** packages in this corpus. The number reads as a floor and, in config mode, acts
as a ceiling: Eigen ships a `SameMajorVersion` config, so Eigen 5 *rejects* a 3.3 request
rather than satisfying it, and `NO_MODULE` rules out the module-mode workaround. Since
robostack-jazzy moved to Eigen 5, all 18 fail to configure. The generator now strips the
version, with a `grep` in front asserting the text is there so the rewrite fails loudly
rather than silently stopping to match. Same over-constraint as `ISSUES.md` #13.

Eight recipes carry that rewrite today, including the NITROS type adapters — which is why
`isaac_ros_nitros_point_cloud_type` is the package that surfaced it, not anything in this
directory.

## Notes on the check

`ROS_DOMAIN_ID=91` and a container named `detect_check_container`, for the reason spelled
out in `pose/README.md`: every `component_container` answers to `/ComponentManager`, and
the other check environments here leave them running, so the default name silently routes
load requests to a prefix without these packages installed.

`RtDetrPreprocessorNode` gets a 1 MB CUDA memory pool instead of its default ~369 MB. It
is the one node here that allocates device memory in its constructor, and all six land in
one container.
