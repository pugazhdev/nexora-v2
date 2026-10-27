"""Test factories. Everything here is synthetic test data."""

import io

from PIL import Image


def png_bytes(size=(64, 48), color=(200, 30, 30), fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()
