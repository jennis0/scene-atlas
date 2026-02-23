"""Unit tests for backend.app.services.video_utils."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.app.services.video_utils import (
    extract_first_frame,
    get_video_dimensions,
    verify_video_mime,
)

# ---------------------------------------------------------------------------
# verify_video_mime — pure byte‑check, no I/O
# ---------------------------------------------------------------------------


class TestVerifyVideoMime:
    """Already tested in test_validation.py; these cover additional edge cases."""

    def test_mp4_ftyp_isom(self):
        data = b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00"
        assert verify_video_mime(data) is True

    def test_webm_ebml_header(self):
        data = b"\x1a\x45\xdf\xa3\x01\x00\x00\x00"
        assert verify_video_mime(data) is True

    def test_jpeg_rejected(self):
        data = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        assert verify_video_mime(data) is False

    def test_too_short(self):
        assert verify_video_mime(b"\x00\x00\x00") is False

    def test_empty(self):
        assert verify_video_mime(b"") is False

    def test_exactly_8_bytes_ftyp(self):
        data = b"\x00\x00\x00\x08ftyp"
        assert verify_video_mime(data) is True


# ---------------------------------------------------------------------------
# extract_first_frame — mock cv2.VideoCapture
# ---------------------------------------------------------------------------


class TestExtractFirstFrame:
    def test_returns_pil_image(self, tmp_path):
        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)  # BGR
        fake_frame[:, :, 2] = 255  # Red in BGR

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, fake_frame)

        with patch("backend.app.services.video_utils.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.COLOR_BGR2RGB = 4  # actual OpenCV constant
            mock_cv2.cvtColor.return_value = fake_frame[:, :, ::-1]  # simulate BGR→RGB

            result = extract_first_frame(tmp_path / "video.mp4")

        from PIL import Image

        assert isinstance(result, Image.Image)
        mock_cap.release.assert_called_once()

    def test_raises_on_unopened(self, tmp_path):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False

        with patch("backend.app.services.video_utils.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            with pytest.raises(ValueError, match="Cannot open video"):
                extract_first_frame(tmp_path / "bad.mp4")

        mock_cap.release.assert_called_once()

    def test_raises_on_no_frame(self, tmp_path):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)

        with patch("backend.app.services.video_utils.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            with pytest.raises(ValueError, match="Cannot read first frame"):
                extract_first_frame(tmp_path / "empty.mp4")


# ---------------------------------------------------------------------------
# get_video_dimensions — mock cv2.VideoCapture
# ---------------------------------------------------------------------------


class TestGetVideoDimensions:
    def test_returns_width_height(self, tmp_path):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {3: 1920.0, 4: 1080.0}[prop]

        with patch("backend.app.services.video_utils.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

            w, h = get_video_dimensions(tmp_path / "video.mp4")

        assert w == 1920
        assert h == 1080
        mock_cap.release.assert_called_once()

    def test_raises_on_unopened(self, tmp_path):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False

        with patch("backend.app.services.video_utils.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            with pytest.raises(ValueError, match="Cannot open video"):
                get_video_dimensions(tmp_path / "bad.mp4")
