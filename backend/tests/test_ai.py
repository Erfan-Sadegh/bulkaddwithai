import base64
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from app.ai import AvalAiProvider, InvalidProductImageError, _image_data_url, _transcription_text
from app.config import Settings
from app.models import Asset


class DumpableTranscription:
    def model_dump(self):
        return {"text": "سلام، قیمتش سی هزار تومنه"}


def test_transcription_text_extracts_plain_text_from_provider_shapes():
    assert _transcription_text("متن خام") == "متن خام"
    assert _transcription_text({"text": "متن دیکشنری"}) == "متن دیکشنری"
    assert _transcription_text('{"text": "متن جیسون"}') == "متن جیسون"
    assert _transcription_text(DumpableTranscription()) == "سلام، قیمتش سی هزار تومنه"


def test_avalai_transcription_uses_json_and_keeps_audio_filename(tmp_path):
    audio_path = tmp_path / "voice.m4a"
    audio_path.write_bytes(b"recorded audio")
    captured = {}

    class FakeTranscriptions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return {"text": "متن صدا"}

    provider = AvalAiProvider(Settings(AVALAI_API_KEY="test-key"))
    provider.client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=FakeTranscriptions()),
    )
    audio = Asset(
        batch_id=1,
        type="audio",
        upload_order=1,
        original_filename="voice.m4a",
        file_path=str(audio_path),
        mime_type="audio/mp4",
        size_bytes=audio_path.stat().st_size,
        checksum="test",
    )

    assert provider.transcribe(audio) == "متن صدا"
    assert captured["response_format"] == "json"
    assert captured["file"].name.endswith("voice.m4a")


def test_image_data_url_normalizes_mislabeled_image_to_supported_jpeg(tmp_path):
    path = tmp_path / "camera.heic"
    Image.new("RGBA", (80, 60), (230, 40, 50, 120)).save(path, format="PNG")

    data_url = _image_data_url(path, "image/heic")

    prefix, payload = data_url.split(",", 1)
    assert prefix == "data:image/jpeg;base64"
    with Image.open(BytesIO(base64.b64decode(payload))) as normalized:
        assert normalized.format == "JPEG"
        assert normalized.mode == "RGB"
        assert normalized.size == (80, 60)


def test_image_data_url_bounds_large_images_before_ai_request(tmp_path):
    path = tmp_path / "large.png"
    Image.new("RGB", (4200, 2800), "white").save(path, format="PNG")

    data_url = _image_data_url(path, "image/png")

    with Image.open(BytesIO(base64.b64decode(data_url.split(",", 1)[1]))) as normalized:
        assert max(normalized.size) == 1600


def test_image_data_url_rejects_unreadable_images_before_provider_call(tmp_path):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not-an-image")

    with pytest.raises(InvalidProductImageError):
        _image_data_url(path, "image/jpeg")


def test_avalai_image_failure_identifies_the_photo_number_without_calling_provider(tmp_path):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not-an-image")
    provider = AvalAiProvider(Settings(AVALAI_API_KEY="test-key"))
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: pytest.fail("provider must not be called"))
        )
    )
    image = Asset(
        batch_id=1,
        type="image",
        upload_order=3,
        original_filename="broken.jpg",
        file_path=str(path),
        mime_type="image/jpeg",
        size_bytes=path.stat().st_size,
        checksum="test",
    )

    with pytest.raises(InvalidProductImageError) as captured:
        provider.extract_products([image], None)

    assert captured.value.upload_order == 3
