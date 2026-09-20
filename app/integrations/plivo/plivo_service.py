
import json
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

PLIVO_AUTH_ID = os.environ["PLIVO_AUTH_ID"]
PLIVO_AUTH_TOKEN = os.environ["PLIVO_AUTH_TOKEN"]

# Module-level, reused client: avoids a fresh TCP+TLS handshake on every
# call, and lets us await instead of blocking the event loop.
_http_client = httpx.AsyncClient(
    auth=(PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN),
    timeout=10.0,
)


def create_greeting_response(host: str):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>
        Hello, welcome to the hospital appointment assistant.
        How can I help you today?
    </Speak>

    <Stream
        streamTimeout="86400"
        keepCallAlive="true"
        bidirectional="true"
        contentType="audio/x-mulaw;rate=8000"
        audioTrack="inbound">
        wss://{host}/call/media-stream
    </Stream>
</Response>
'''


def build_clear_audio_message(stream_id: str) -> str:
    return json.dumps({
        "event": "clearAudio",
        "streamId": stream_id,
    })


def create_tts_response(text: str):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>{text}</Speak>
</Response>
'''


async def speak_on_call(call_uuid: str, text: str):
    """Must be `async def` -- this is called with `await` in call_router.py.
    If this is still plain `def` using `requests`, calling it returns None
    (not a coroutine), and `await None` is exactly the crash you saw."""
    url = (
        f"https://api.plivo.com/v1/Account/"
        f"{PLIVO_AUTH_ID}/Call/{call_uuid}/Speak/"
    )

    data = {
        "text": text,
        "voice": "WOMAN",
        "language": "en-US",
    }

    response = await _http_client.post(url, json=data)

    print("[Plivo TTS]", response.status_code)
    print(response.text)


async def stop_speaking(call_uuid: str):
    """Barge-in: stops whatever TTS is currently playing on the call.
    Call this the instant the caller starts talking over the AI, so the
    two audio streams never overlap. Safe to call even if nothing is
    currently speaking -- Plivo just returns that there's no active speak."""
    url = (
        f"https://api.plivo.com/v1/Account/"
        f"{PLIVO_AUTH_ID}/Call/{call_uuid}/Speak/"
    )

    response = await _http_client.delete(url)

    print("[Plivo TTS] stop ->", response.status_code)