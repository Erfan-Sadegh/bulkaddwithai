from io import BytesIO

from PIL import Image


def image_bytes(color: tuple[int, int, int] = (24, 112, 101), *, size: tuple[int, int] = (32, 24)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="JPEG")
    return output.getvalue()


def image_file(name: str, payload: bytes | None = None, content_type: str = "image/jpeg"):
    return ("files", (name, payload if payload is not None else image_bytes(), content_type))


def audio_file(name: str = "voice.webm", payload: bytes = b"fake-audio"):
    return ("files", (name, payload, "audio/webm"))
