"""Video utility functions: first-frame extraction, dimension reading, MIME validation."""

import logging
from pathlib import Path

import cv2
from PIL import Image

logger = logging.getLogger(__name__)


def extract_first_frame(video_path: Path) -> Image.Image:
    """Extract the first frame from a video as a PIL Image (RGB).

    Raises ValueError if the video cannot be opened or the frame cannot be read.
    """
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")
        ret, frame = cap.read()
        if not ret or frame is None:
            raise ValueError(f"Cannot read first frame from: {video_path}")
        # OpenCV returns BGR; convert to RGB for PIL
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame_rgb)
    finally:
        cap.release()


def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    """Return (width, height) of a video file."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return w, h
    finally:
        cap.release()


def verify_video_mime(data: bytes) -> bool:
    """Return True if data appears to be a valid MP4 or WebM file.

    Checks magic bytes only — does not fully decode.
      MP4/MOV: bytes 4–7 are 'ftyp' (0x66 0x74 0x79 0x70)
      WebM:    bytes 0–3 are EBML header (0x1A 0x45 0xDF 0xA3)
    """
    if len(data) < 8:
        return False
    # MP4: 'ftyp' at offset 4
    if data[4:8] == b"ftyp":
        return True
    # WebM (Matroska EBML header)
    return data[0:4] == b"\x1a\x45\xdf\xa3"
