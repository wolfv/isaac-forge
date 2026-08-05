# Real YOLOv8 + Rerun demo

This example runs an actual COCO-trained **Ultralytics YOLOv8n** network through
the packaged Isaac ROS GPU pipeline:

```text
sample image -> NITROS/CUDA preprocessing -> TensorRT -> YOLOv8 decoder
             -> vision_msgs/Detection2DArray -> Rerun
```

It downloads a checksum-pinned 12 MB, 320×320 ONNX model and the Ultralytics `bus.jpg`
sample on first use. YOLOv8n is already the smallest YOLOv8 model; using its 320×320 export
instead of 640×640 reduces TensorRT activation and tactic memory substantially for an Orin
Nano. TensorRT then builds a GPU-specific engine in `.cache/`, which can take a few minutes
the first time.

```bash
cd yolo
pixi run check
pixi run demo
```

The environment supports both x86_64 Linux and Jetson/ARM64. Its ARM platform declares
JetPack 7, CUDA 13, and SM87, so Pixi selects the Orin TensorRT payload as well as
`ros-jazzy-isaac-ros-image-proc` from isaac-forge.

The demo opens the Rerun viewer with the image and 2D detection boxes, and also
writes an annotated image to `.cache/yolov8_result.png`.

For a machine without a desktop session, record the visualization instead:

```bash
pixi run demo --no-viewer
# Later, on a desktop:
pixi run rerun .cache/yolov8_result.rrd
```

## Video and webcam streaming

Run the bundled-on-demand sample traffic video until it ends:

```bash
pixi run video
```

A webcam, video file, RTSP stream, or other OpenCV-compatible URL can be used as
the source. The Rerun timeline updates with every inference result:

```bash
pixi run video --source 0                    # default webcam
pixi run video --source /path/to/video.mp4
pixi run video --source /path/to/video.mp4 --loop
pixi run video --source rtsp://camera.example/stream
```

For headless processing, add `--no-viewer`; this writes
`.cache/yolov8_video.rrd`. Use `--max-frames 300` to bound a recording.

An NVIDIA GPU and working driver are required. Close other GPU-heavy applications while
TensorRT builds the engine on a low-memory Jetson. The downloaded model carries the
Ultralytics AGPL-3.0 license; its URL and SHA-256 are pinned in
[`yolo_demo.py`](./yolo_demo.py).
