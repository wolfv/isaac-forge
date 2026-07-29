# Benchmark parity — working

Goal: run NVIDIA's own `ros2_benchmark` / `isaac_ros_benchmark` harness against our
conda-built packages, so throughput can be compared to their deb-built numbers using
their own tool and their own metric.

**Status: the harness completes on our packages.**

```bash
cd bench
./fetch_data.sh          # 2.9 GB r2b_storage from NGC (public)
pixi run bench
```

## Numbers

`ResizeNode` RGB8 1920x1200 → 960x576 on an RTX 4060 (driver 610.43.03, CUDA 13.3),
`launch_test` reporting `Ran 1 test ... OK`. Reproduced twice:

| | |
|---|---|
| Peak throughput | **2495.5 fps** |
| Harness prediction | 2495.3 fps |
| Frames sent / missed | 12476 / **0** |
| Mean frame-to-frame jitter | 0.073 ms |
| Max frame-to-frame jitter | 2.17 ms |
| Mean / max GPU utilization | 3.5% / 8.0% |
| Mean CPU utilization | 0.96% |

The binary search converged upward through 1255 → 1877 → 2189 → 2344 → 2422 → 2461 →
2481 → 2490 Hz with zero missed frames at every probe, so the ceiling is the harness
saturating rather than the node dropping work.

Measured with `Device OS : Linux 7.1.5-200.fc44.x86_64` in NVIDIA's own metadata table,
which remains the point of the exercise.

## What works

All 45 packages build and install, including the complete benchmark harness
(`ros2_benchmark`, `ros2_benchmark_interfaces`, `isaac_ros_benchmark`,
`isaac_ros_image_proc_benchmark` and 11 NITROS type adapters).

The harness gets a long way:

- profiles idle CPU/GPU via `nvidia-smi` (0.625% CPU, 0.000% GPU)
- resolves and hashes the dataset (`5e8f11201fe10dbac7307a8628553e94`, 3087908864 bytes)
- predicts peak throughput (2495 Hz)
- loads `NitrosDataLoaderNode`, `NitrosPlaybackNode` and `NitrosMonitorNode`, each
  completing NITROS format negotiation (`nitros_image_rgb8`, `nitros_camera_info`)
- emits NVIDIA's own metadata table — note the device line:

```
| [metadata] Test Name : Isaac ROS ResizeNode RGB8 1920x1200 to 960x576 Benchmark |
| [metadata] Device Hostname : fedora-3.fritz.box                                 |
| [metadata] Device Architecture : x86_64                                         |
| [metadata] Device OS : Linux 7.1.5-200.fc44.x86_64                              |
| [metadata] Idle System CPU Util. (%) : 0.872                                    |
| [metadata] Peak Throughput Prediction (Hz) : 2495.273                           |
| [metadata] Input Data Size (bytes) : 3087908864                                 |
```

NVIDIA's benchmark harness reporting `Linux 7.1.5-200.fc44.x86_64` is itself a
result worth keeping.

## The crash this used to hit — undiagnosed, not fixed

For the record, because it may come back. The measurement phase used to abort
immediately after `NitrosMonitorNode` finished initialising:

```
[r2b.MonitorNode]: [NitrosMonitorNode] Created an NITROS type monitor subscriber
[component_container_mt-1] terminate called after throwing an instance of 'std::runtime_error
[component_container_mt-1] terminate called recursively        (x40)
[ERROR] process has died [pid ..., exit code -6, cmd '... component_container_mt ...']
```

The `what()` string was destroyed by the recursive `terminate`, so the message was never
recovered. Ruled out at the time: not GPU OOM (8188 MiB total, 1185 MiB in use,
`playback_message_buffer_size` 100 frames ≈ 690 MB at 1920x1200 RGB8); not a missing
library (all three NITROS nodes loaded and negotiated formats first); not the dataset (it
resolved, sized and hashed).

**It stopped reproducing without being diagnosed.** Three things changed between the
failing and passing runs, and no attempt was made to isolate which mattered:

| | was | now |
|---|---|---|
| OS | Fedora 43 (`7.1.5-100.fc43`) | Fedora 44 (`7.1.5-200.fc44`) |
| Driver | 580.173.02 | 610.43.03 |
| Packages | earlier build | rebuilt |

So this is not a fix, it is a disappearance. If it returns, catch it under a debugger
rather than guessing:

```bash
pixi run env ISAAC_ROS_WS="$PWD/ws" gdb -ex run -ex bt --args \
  .pixi/envs/default/lib/rclcpp_components/component_container_mt \
  --ros-args -r __node:=resize_container -r __ns:=/r2b
```

The earlier hypothesis, still unverified: a CUDA/NITROS interaction during buffer
allocation that throws where the deb build would not. The buffering path is the one part
of this stack that allocates large NITROS GPU buffers up front, and it is the first thing
to run after the monitor subscriber exists.

## Two harness notes

`launch_testing`'s pytest plugin is incompatible with the pytest RoboStack ships —
`pytest_pycollect_makemodule(path, parent)` uses the pre-pytest-8 signature and
fails plugin validation. Use `launch_test` directly instead of `pytest`. Unrelated to
Isaac ROS, but it will bite anyone running these benchmarks from conda.

Assets resolve through `${ISAAC_ROS_WS}/src/ros2_benchmark/assets`, and
`assets_root:=` on the command line does not override it, so `ws/` here is a symlink
farm that satisfies the expected layout.
