from types import SimpleNamespace

from app.ai import AvalAiProvider, _transcription_text
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
