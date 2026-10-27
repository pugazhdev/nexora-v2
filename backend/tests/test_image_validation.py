import io

import pytest
from PIL import Image

from app.errors import ImageTooLargeError, InvalidImageError, UnsupportedImageError
from app.intake.image import prepare_image
from tests.factories import png_bytes

KW = dict(max_bytes=1_000_000, max_pixels=1_000_000, max_side=100)


def test_valid_png_is_normalised_to_resized_jpeg():
    out = prepare_image(png_bytes(size=(400, 200)), "image/png", **KW)
    assert out.mime_type == "image/jpeg"
    img = Image.open(io.BytesIO(out.data))
    assert max(img.size) == 100


def test_jpeg_and_webp_accepted():
    assert prepare_image(png_bytes(fmt="JPEG"), "image/jpeg", **KW).data
    assert prepare_image(png_bytes(fmt="WEBP"), "image/webp", **KW).data


def test_empty_file_rejected():
    with pytest.raises(InvalidImageError):
        prepare_image(b"", "image/png", **KW)


def test_oversize_rejected():
    with pytest.raises(ImageTooLargeError):
        prepare_image(png_bytes(), "image/png", max_bytes=10, max_pixels=10**6, max_side=100)


def test_text_file_with_image_extension_rejected_by_content():
    with pytest.raises(UnsupportedImageError):
        prepare_image(b"this is not an image at all", "image/png", **KW)


def test_declared_type_must_match_content():
    with pytest.raises(UnsupportedImageError) as e:
        prepare_image(png_bytes(), "image/jpeg", **KW)
    assert e.value.details["detected"] == "image/png"


def test_gif_not_permitted():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="GIF")
    with pytest.raises(UnsupportedImageError):
        prepare_image(buf.getvalue(), "image/gif", **KW)


def test_truncated_image_rejected():
    with pytest.raises(InvalidImageError):
        prepare_image(png_bytes(size=(200, 200))[:60], "image/png", **KW)


def test_pixel_limit_enforced():
    with pytest.raises(ImageTooLargeError):
        prepare_image(
            png_bytes(size=(200, 200)), "image/png", max_bytes=10**6, max_pixels=1000, max_side=100
        )
