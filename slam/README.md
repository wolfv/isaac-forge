# cuVSLAM on NVIDIA's r2b Galileo dataset — on Fedora, from conda packages

```bash
cd slam
./fetch_data.sh      # 493 MB from NGC, public, no credentials
pixi run slam
```

Everything here resolves from `../output` (the packages this repo builds) plus
`robostack-jazzy` and conda-forge. No Docker, no apt, no Ubuntu.

## Result

```
    cuVSLAM version: 15.0.0+74f0e317-modified
    Time taken by cuvslam::WarmUpGPU(): 0.006158

  /visual_slam/tracking/odometry     343 msgs
  /visual_slam/tracking/slam_path    343 poses
  /chassis/odom (wheel, ground ref)  842 msgs

  cuVSLAM path length       6.04 m
  cuVSLAM net displacement   5.91 m
  wheel odom path length    6.36 m
  agreement with wheel odom: 94.9% (5.1% difference in path length)

PASS: cuVSLAM tracked 6.04 m over 343 poses on the GPU
```

Measured on an RTX 4060, driver 610.43.03, CUDA 13.3, with NVDEC hardware decode.

The wheel-odometry comparison is the point. A node that loads proves packaging; a
trajectory that tracks to within 5% of the ground reference recorded in the same bag
proves the GPU maths is actually running correctly. `measure_trajectory.py` also
fails if the path is under 10 cm, because a wedged tracker still publishes poses —
it just never moves.

## Pipeline

```
r2b_galileo_0.mcap  (4 stereo pairs, H.264, 1920x1200, 22 s, 12919 msgs)
    -> DecoderNode x2              NVDEC hardware decode -> rgb8
    -> ImageFormatConverterNode x2 CV-CUDA rgb8 -> mono8
    -> VisualSlamNode              cuVSLAM stereo tracking on the GPU
    -> /visual_slam/tracking/odometry, /visual_slam/tracking/slam_path
```

All five nodes run in one `component_container_mt`, so NITROS hands buffers between
stages without leaving the device.

Only the front stereo pair is used (`num_cameras: 2`). The bag carries four pairs,
so this could go to 8.

Images are **not** rectified — `camera_info` reports a `rational_polynomial` model
with non-zero distortion — so `rectified_images: false` and cuVSLAM undistorts
internally. Extrinsics come from the bag's own `/tf_static`
(`base_link -> front_stereo_camera -> ..._left_optical`).

## NVDEC — running end to end

`USE_NVDEC=1` (the default) runs NVIDIA's own `isaac_ros_h264_decoder` on NVDEC, and the
decoders are the *only* image source in this graph, so the trajectory above is proof the
hardware decode works:

```
[h264_decoder]: [DecoderNode] Initializing H264 Decoder Node
[V4L2Decoder]:  V4L2 Decoder initialized, cuvid=1
[h264_decoder]: [DecoderNode] H264 Decoder Node initialized
```

Measured decode output over a 30 s window:

| topic | msgs | format |
|---|---|---|
| `/front/left/image_raw` | 186 | 1920x1200 rgb8 |
| `/front/right/image_raw` | 178 | 1920x1200 rgb8 |
| `/front/left/image_mono` | 189 | 1920x1200 mono8 |
| `/front/right/image_mono` | 181 | 1920x1200 mono8 |

Two fixes had to land first, and neither is a patch to a vendor binary any more:

- the absolute `DT_NEEDED` entries are gone, because the package is source-built with
  the upstream fix (`ISSUES.md` #2). The byte-patching phase in `gen_repack.py` that
  used to rewrite sonames inside `libdecoder_node.so` has been deleted.
- the decoder no longer references `cudaGetDeviceProperties_v2`. It was being compiled
  against the build machine's `/usr/local/cuda` 12.9 headers — see the root cause in
  the top-level [`README.md`](../README.md).

Expect ~12 `Still waiting for resolution_change_event` warnings from `V4L2Decoder` in
the first few seconds. That is the decoder waiting for the stream's first resolution
event; it clears once frames flow, and no decoder errors follow.

## The CPU fallback (USE_NVDEC=0)

`h264_bridge.py` decodes the front pair with PyAV instead. Still useful as a cross-check
on cuVSLAM independent of NVDEC: it gives **6.06 m over 280 poses, 95.3%** agreement.

Fewer frames reach the tracker, which is the whole difference between the two numbers.
The cost is visible in the log: CPU decode delivers frames every ~66 ms against
cuVSLAM's 40 ms jitter threshold, so it warns repeatedly. NVDEC removes most of that
slack — 343 poses against 280.

## Files

```
fetch_data.sh                     pull the dataset from NGC
launch/r2b_galileo_vslam.launch.py  cuVSLAM node + params + frame wiring
h264_bridge.py                    CPU H.264 -> mono8 (see above)
measure_trajectory.py             integrate the path, compare to wheel odom
run_slam.sh                       orchestrate the three and report
```
