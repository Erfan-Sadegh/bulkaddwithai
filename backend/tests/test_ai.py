from app.ai import _transcription_text


class DumpableTranscription:
    def model_dump(self):
        return {"text": "سلام، قیمتش سی هزار تومنه"}


def test_transcription_text_extracts_plain_text_from_provider_shapes():
    assert _transcription_text("متن خام") == "متن خام"
    assert _transcription_text({"text": "متن دیکشنری"}) == "متن دیکشنری"
    assert _transcription_text('{"text": "متن جیسون"}') == "متن جیسون"
    assert _transcription_text(DumpableTranscription()) == "سلام، قیمتش سی هزار تومنه"
