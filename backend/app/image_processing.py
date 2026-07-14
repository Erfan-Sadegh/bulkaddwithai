import base64
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener


AI_IMAGE_MAX_SIDE = 1600
IMAGE_MAX_PIXELS = 80_000_000

register_heif_opener()


class InvalidProductImageError(ValueError):
    def __init__(self, message: str, *, upload_order: int | None = None):
        super().__init__(message)
        self.upload_order = upload_order


def normalized_image_bytes(path: Path, *, max_side: int = AI_IMAGE_MAX_SIDE) -> bytes:
    try:
        with Image.open(path) as source:
            width, height = source.size
            if width < 1 or height < 1 or width * height > IMAGE_MAX_PIXELS:
                raise InvalidProductImageError("image dimensions are invalid or too large")

            source.seek(0)
            source.load()
            oriented = ImageOps.exif_transpose(source)
            oriented.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            normalized = _flatten_to_rgb(oriented)
            output = BytesIO()
            normalized.save(output, format="JPEG", quality=82, optimize=True)
            return output.getvalue()
    except InvalidProductImageError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise InvalidProductImageError("image could not be decoded") from exc


def normalized_image_data_url(path: Path) -> str:
    payload = base64.b64encode(normalized_image_bytes(path)).decode("ascii")
    return f"data:image/jpeg;base64,{payload}"


def normalize_image_file(source: Path, target: Path) -> None:
    target.write_bytes(normalized_image_bytes(source))


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")
