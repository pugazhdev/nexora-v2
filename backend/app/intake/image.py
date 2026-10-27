"""Validate uploads by content (magic bytes + decoding), then normalise: strip metadata, resize."""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.errors import ImageTooLargeError, InvalidImageError, UnsupportedImageError


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    mime_type: str


ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}


def sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def prepare_image(
    data: bytes,
    declared_mime: str | None,
    *,
    max_bytes: int,
    max_pixels: int,
    max_side: int,
) -> PreparedImage:
    if not data:
        raise InvalidImageError("The uploaded file is empty.")
    if len(data) > max_bytes:
        raise ImageTooLargeError(
            f"Image exceeds the {max_bytes // (1024 * 1024)} MB upload limit.",
            details={"max_bytes": max_bytes},
        )
    sniffed = sniff_mime(data)
    if sniffed is None or sniffed not in ALLOWED_MIME:
        raise UnsupportedImageError("Unsupported image format. Use JPEG, PNG or WebP.")
    if declared_mime and declared_mime.split(";")[0].strip().lower() != sniffed:
        raise UnsupportedImageError(
            "File content does not match its declared type.",
            details={"declared": declared_mime, "detected": sniffed},
        )

    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > max_pixels:
                raise ImageTooLargeError("Image dimensions are too large.")
            img.load()
            img = ImageOps.exif_transpose(img)  # also drops other metadata when re-encoded
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[3])
                img = bg
            else:
                img = img.convert("RGB")
            img.thumbnail((max_side, max_side))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=88)
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError("Image dimensions are too large.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise InvalidImageError("The file is not a readable image.") from exc
    return PreparedImage(data=out.getvalue(), mime_type="image/jpeg")
