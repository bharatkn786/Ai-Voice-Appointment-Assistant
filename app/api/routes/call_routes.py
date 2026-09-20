import asyncio
import base64
import json
import os
import time

from dotenv import load_dotenv
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.integrations.plivo.plivo_service import (
    create_greeting_response,
    build_clear_audio_message,
    speak_on_call,
    stop_speaking,
)
from app.integrations.plivo.deepgram_service import connect_to_deepgram


load_dotenv()

router = APIRouter(prefix="/call")

GRACE_PERIOD = 0.7

print("[call_router] loaded -- debounce + barge-in version, GRACE_PERIOD =", GRACE_PERIOD)


def _ts():
    return time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"


@router.post("/incoming")
async def answer_call(request: Request):
    """Set this as your Plivo number's Answer URL."""
    xml_data = create_greeting_response(host=request.headers["host"])
    return Response(content=xml_data, media_type="application/xml")


async def handle_appointment_request(transcript: str):
    """Handoff point to your appointment assistant logic."""
    print(f"\n>>> SENDING TO APPOINTMENT ASSISTANT: {transcript!r}\n")
    return transcript


@router.websocket("/media-stream")
async def media_stream(plivo_ws: WebSocket):
    await plivo_ws.accept()

    stream_id = None
    call_uuid = None
    utterance_pieces = []
    pending_finalize_task = None
    ai_speaking = False  # True while our TTS is actively playing on the call

    async with connect_to_deepgram() as dg_ws:

        async def from_plivo():
            nonlocal stream_id, call_uuid

            try:
                async for raw in plivo_ws.iter_text():
                    event = json.loads(raw)
                    etype = event.get("event")

                    if etype == "start":
                        stream_id = event["start"]["streamId"]
                        call_uuid = event["start"]["callId"]
                        print(f"[plivo] stream started: {stream_id}")
                        print(f"[plivo] call uuid: {call_uuid}")

                    elif etype == "media":
                        audio_bytes = base64.b64decode(
                            event["media"]["payload"]
                        )
                        await dg_ws.send(audio_bytes)

                    elif etype == "stop":
                        print("[plivo] stream stopped")
                        break

            except WebSocketDisconnect:
                print("[plivo] disconnected")

            finally:
                await dg_ws.send(json.dumps({"type": "CloseStream"}))

        async def finalize_utterance():
            nonlocal ai_speaking

            complete = " ".join(utterance_pieces).strip()
            utterance_pieces.clear()

            if not complete:
                return

            print(f"\n[{_ts()}] [FINAL]", complete)

            response_text = await handle_appointment_request(complete)

            if call_uuid:
                ai_speaking = True
                await speak_on_call(call_uuid, "You said " + response_text)

        async def schedule_finalize():
            nonlocal pending_finalize_task
            try:
                await asyncio.sleep(GRACE_PERIOD)
            except asyncio.CancelledError:
                print(f"[{_ts()}] [grace] cancelled -- user kept talking")
                return
            pending_finalize_task = None
            print(f"[{_ts()}] [grace] elapsed -- finalizing now")
            await finalize_utterance()

        def reset_finalize_timer():
            nonlocal pending_finalize_task
            if pending_finalize_task is not None and not pending_finalize_task.done():
                pending_finalize_task.cancel()
            print(f"[{_ts()}] [grace] pause detected, starting {GRACE_PERIOD}s timer "
                  f"(buffer so far: {' '.join(utterance_pieces)!r})")
            pending_finalize_task = asyncio.create_task(schedule_finalize())

        def cancel_finalize_timer():
            nonlocal pending_finalize_task
            if pending_finalize_task is not None and not pending_finalize_task.done():
                pending_finalize_task.cancel()
            pending_finalize_task = None

        async def from_deepgram():
            nonlocal ai_speaking

            async for raw in dg_ws:
                msg = json.loads(raw)
                mtype = msg.get("type")

                if mtype == "SpeechStarted":
                    print(f"[{_ts()}] [deepgram] SpeechStarted")
                    cancel_finalize_timer()

                elif mtype == "Results":
                    alt = msg["channel"]["alternatives"][0]
                    transcript = alt["transcript"].strip()

                    if not transcript:
                        continue

                    print(f"[interim] {transcript}")

                    # Confirm actual speech before stopping AI TTS
                    if ai_speaking and len(transcript) >= 2 and call_uuid:
                        print(f"[{_ts()}] [barge-in] confirmed speech: {transcript!r}")

                        ai_speaking = False

                        await stop_speaking(call_uuid)

                        if stream_id:
                            try:
                                await plivo_ws.send_text(
                                    build_clear_audio_message(stream_id)
                                )
                            except WebSocketDisconnect:
                                print("[plivo] WebSocket already disconnected")

                    if msg["is_final"]:
                        utterance_pieces.append(transcript)

                        if msg.get("speech_final"):
                            reset_finalize_timer()
                    else:
                        print(f"[interim] {transcript}")

                elif mtype == "UtteranceEnd":
                    if utterance_pieces:
                        print(f"[{_ts()}] [deepgram] UtteranceEnd fallback fired")
                        reset_finalize_timer()

        await asyncio.gather(
            from_plivo(),
            from_deepgram(),
        )
        