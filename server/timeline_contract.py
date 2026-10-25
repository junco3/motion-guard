"""Verify the complete prepared timeline before provisioning a paid worker."""
import json
import hashlib
from pathlib import Path

import cv2
from motionguard_core.reference_io import validate_timeline


class InvalidGeneratedVideo(ValueError):
    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = evidence


def decoded_video(path, expected_size=(512, 768), reject_black=False):
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError("Cannot decode prepared video")
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = 0
        first_size = None
        maximum = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            size = frame.shape[:2]
            if reject_black:
                maximum = max(maximum, int(frame.max()))
            if first_size is None:
                first_size = size
            if size != first_size or (expected_size is not None and size != expected_size):
                raise ValueError("Prepared video dimensions differ from reference")
            count += 1
        if reject_black and count and maximum == 0:
            raise InvalidGeneratedVideo("Generated video is entirely black", {
                "reason": "all_black", "frames": count, "fps": fps,
                "pixel_min": 0, "pixel_max": 0,
                "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                "motion_evaluation": "not_performed"})
        return {"frames": count, "fps": fps}
    finally:
        cap.release()


def validate_cloud(folder, workflow, gt_name, control_name):
    """Cloud Stage1 has its own required output graph; never skip absent nodes."""
    folder = Path(folder)
    timeline = validate_timeline(json.loads((folder / gt_name).read_text(encoding="utf-8")))
    expected = {"frames": timeline["frames"], "fps": 24}
    for name in ("reference.mp4", control_name):
        if decoded_video(folder / name) != expected:
            raise ValueError("Cloud GT and video timeline mismatch: " + name)
    links = (
        ("5548/5000", "video", ["5001", 0]),
        ("5548/5026", "input", ["5548/5000", 0]),
        ("5548/5028", "input", ["5548/5026", 0]),
        ("5548/5029", "image", ["5548/5028", 0]),
        ("9002/3059", "length", ["5548/5029", 2]),
        ("9002/5066", "a", ["5548/5000", 2]),
        ("9002/3980", "frames_number", ["5548/5029", 2]),
        ("9002/3980", "frame_rate", ["9002/5066", 0]),
        ("5014/1241", "frame_rate", ["5548/5000", 2]),
        ("9002/9005", "frame_rate", ["5548/5000", 2]),
        ("diag_video", "fps", ["5548/5000", 2]),
        ("diag_video", "images", ["diag_decode", 0]),
        ("diag_save", "video", ["diag_video", 0]),
    )
    for node, field, required in links:
        if workflow.get(node, {}).get("inputs", {}).get(field) != required:
            raise ValueError("Cloud graph timeline disconnected: " + node + "." + field)
    return expected


def validate_cloud_output(path, expected):
    # Stage1's graph resizes spatially. Preserve its original resolution while
    # requiring a stable decoded frame size and the complete reference timeline.
    actual = decoded_video(path, expected_size=None, reject_black=True)
    if actual != expected:
        raise ValueError("Generated video timeline mismatch")
    return actual


def validate(folder, plan, workflow, gt_name):
    folder = Path(folder)
    gt = json.loads((folder / gt_name).read_text(encoding="utf-8"))
    timeline = validate_timeline(gt)
    expected = timeline["frames"]
    for key, value in (("expected_frames", expected), ("expected_fps", 24)):
        supplied = plan.get(key, value)
        if type(supplied) is not int or supplied != value:
            raise ValueError("Prepared plan timeline mismatch")
    for name in ("reference.mp4", "pose.mp4"):
        if decoded_video(folder / name) != {"frames": expected, "fps": 24}:
            raise ValueError("Prepared GT and video timeline mismatch: " + name)
    # Require the audited graph's actual frame-count/fps dependencies.
    links = (
        ("5548/5000", "video", ["5001", 0]),
        ("5548/5026", "input", ["5548/5000", 0]),
        ("5548/5028", "input", ["5548/5026", 0]),
        ("5548/5029", "image", ["5548/5028", 0]),
        ("9002/3059", "length", ["5548/5029", 2]),
        ("9002/5066", "a", ["5548/5000", 2]),
        ("9002/3980", "frames_number", ["5548/5029", 2]),
        ("9002/3980", "frame_rate", ["9002/5066", 0]),
        ("diag_video", "fps", ["5548/5000", 2]),
        ("5518/4849", "fps", ["5548/5000", 2]),
        ("5014/1241", "frame_rate", ["5548/5000", 2]),
        ("9002/9005", "frame_rate", ["5548/5000", 2]),
    )
    for node, field, required in links:
        if workflow.get(node, {}).get("inputs", {}).get(field) != required:
            raise ValueError("Prepared graph timeline disconnected: " + node + "." + field)
    return timeline
