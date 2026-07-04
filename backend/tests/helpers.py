def image_file(name: str, payload: bytes = b"fake-image"):
    return ("files", (name, payload, "image/jpeg"))


def audio_file(name: str = "voice.webm", payload: bytes = b"fake-audio"):
    return ("files", (name, payload, "audio/webm"))
