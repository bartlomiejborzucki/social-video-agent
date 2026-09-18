"""Face detection for reframing.

YuNet is used rather than Haar cascades or MTCNN. It is Apache-2.0, ships with
OpenCV, the model is 233 KB and ungated, and it is both faster and considerably
more accurate than the Haar cascade that most open-source reframers still use.

Detection runs on sampled frames, not every frame. Crop position is a
piecewise-constant decision that changes at cuts and speaker turns, so
per-frame detection would buy precision the output cannot express.
"""

from __future__ import annotations

import contextlib
import logging
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from social_video.errors import SocialVideoError
from social_video.paths import ensure_dir, models_dir

log = logging.getLogger(__name__)

_MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
_MODEL_NAME = "face_detection_yunet_2023mar.onnx"


@dataclass(frozen=True)
class Face:
    """A detected face in source pixel coordinates."""

    x: float
    y: float
    width: float
    height: float
    confidence: float
    #: YuNet's five landmarks: right eye, left eye, nose, right and left mouth
    #: corner. They come back from the same detection call, so speaker detection
    #: gets a mouth position without a second model.
    landmarks: tuple[tuple[float, float], ...] = ()

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2.0, self.y + self.height / 2.0

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def mouth_center(self) -> tuple[float, float] | None:
        """Midpoint of the two mouth corners, when landmarks are present."""
        if len(self.landmarks) < 5:
            return None
        right, left = self.landmarks[3], self.landmarks[4]
        return (right[0] + left[0]) / 2.0, (right[1] + left[1]) / 2.0


@dataclass(frozen=True)
class FrameFaces:
    """Faces found at one sampled instant."""

    t: float
    faces: tuple[Face, ...]

    @property
    def primary(self) -> Face | None:
        """The most prominent face: closest to camera wins, ties on confidence."""
        if not self.faces:
            return None
        return max(self.faces, key=lambda f: (f.area, f.confidence))


def ensure_model() -> Path:
    """Download the YuNet model on first use."""
    path = ensure_dir(models_dir() / "yunet") / _MODEL_NAME
    if path.is_file() and path.stat().st_size > 1000:
        return path
    log.info("downloading YuNet face detection model (233 KB)")
    try:
        with urllib.request.urlopen(_MODEL_URL, timeout=120) as response:
            data = response.read()
    except OSError as exc:
        raise SocialVideoError(
            f"could not download the face detection model from {_MODEL_URL}: {exc}\n"
            f"Reframing can still run with --reframe center, which needs no model."
        ) from exc
    path.write_bytes(data)
    return path


def detect_faces(
    video: Path,
    *,
    start: float = 0.0,
    end: float | None = None,
    samples_per_second: float = 2.0,
    min_confidence: float = 0.7,
    on_frame: Callable[[float, object, tuple[Face, ...]], None] | None = None,
) -> list[FrameFaces]:
    """Sample a time range and detect faces in each sampled frame.

    Two samples per second is enough: a speaker does not teleport, and the crop
    only moves at segment boundaries anyway.
    """
    import cv2

    # OpenCV's DNN backend logs a benign "Targets are not supported by the new
    # graph engine" warning straight to stderr on every detector construction,
    # which would otherwise leak into an agent's output on every reframe.
    with contextlib.suppress(AttributeError):
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)

    model = ensure_model()
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise SocialVideoError(f"could not open {video} for face detection")

    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        source_duration = frame_count / fps if fps > 0 else 0.0
        stop = min(end if end is not None else source_duration, source_duration) or (
            end if end is not None else 0.0
        )
        if stop <= start:
            return []

        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        detector = cv2.FaceDetectorYN.create(
            str(model), "", (width, height), min_confidence, 0.3, 5000
        )

        results: list[FrameFaces] = []
        step = 1.0 / max(samples_per_second, 0.1)
        t = start
        while t < stop:
            capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            found = faces_in_frame(detector, frame)
            if on_frame is not None:
                on_frame(t, frame, found)
            results.append(FrameFaces(t=t, faces=found))
            t += step
        return results
    finally:
        capture.release()


def faces_in_frame(detector, frame) -> tuple[Face, ...]:
    """Run one detection and keep the landmarks the caller may need."""
    _, raw = detector.detect(frame)
    faces: list[Face] = []
    for row in raw if raw is not None else []:
        x, y, w, h = (float(v) for v in row[:4])
        points = tuple((float(row[4 + index * 2]), float(row[5 + index * 2])) for index in range(5))
        faces.append(
            Face(
                x=x,
                y=y,
                width=w,
                height=h,
                confidence=float(row[-1]),
                landmarks=points,
            )
        )
    return tuple(faces)
