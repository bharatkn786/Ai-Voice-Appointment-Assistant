import os
import websockets

DEEPGRAM_API_KEY = os.environ["DEEPGRAM_API_KEY"]

# encoding/sample_rate MUST match the contentType in your Plivo <Stream> XML.
DEEPGRAM_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-3"
    "&language=en-US"
    "&encoding=mulaw"
    "&sample_rate=8000"
    "&channels=1"
    "&interim_results=true"
    "&endpointing=400"
    "&utterance_end_ms=3000"
    "&smart_format=true"
    "&vad_events=true"
)

def connect_to_deepgram():
    """Returns an async context manager -- use as:
        async with connect_to_deepgram() as dg_ws:
            ...
    """
    return websockets.connect(
        DEEPGRAM_URL,
        additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
        ping_interval=5,
    )