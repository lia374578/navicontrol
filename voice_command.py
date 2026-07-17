"""Voice command processing module for robot dog control.

Captures audio from the browser, sends it to Gemini for speech-to-text
and intent parsing, and returns structured robot commands.
"""

import base64
import json
import os
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ── Gemini client ──────────────────────────────────────────────────────────

_client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY"),
)

_MODEL = "models/gemini-3-flash-preview"

# ── System prompt ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a robot dog voice command interpreter. The user speaks a
command, and you map it to one of the following structured actions.

Respond ONLY with a JSON object (no explanations, no markdown).

## Available commands

### Movement (continuous velocity)
- {"action": "move", "linear": <float>, "angular": <float>}
  - Forward: linear=0.5, angular=0.0
  - Backward: linear=-0.5, angular=0.0
  - Turn left: linear=0.0, angular=1.0
  - Turn right: linear=0.0, angular=-1.0
  - Forward-left diagonal: linear=0.5, angular=0.5
  - Forward-right diagonal: linear=0.5, angular=-0.5
  - "go fast" → set linear=1.0 instead of 0.5
  - "slow down" → set linear=0.3

### Stop
- {"action": "stop"} — bring the robot to rest

### Preset actions (tricks / poses)
- {"action": "preset", "name": "<name>"}
  Available names: stand, bow, wave_hand, clap_hand, shake_hand,
  dance_with_beats, shoulder_dance, lion_dance, jump_forward,
  draw_heart, affection, confused, bark, nod_head, shake_head,
  wag_tail, half_sit, lie_on_elbows

### State / stance
- {"action": "stand"} — stand up from sitting/laying
- {"action": "damping"} — relax / zero-torque safe-halt

## Examples
User says "go forward" → {"action": "move", "linear": 0.5, "angular": 0.0}
User says "turn left" → {"action": "move", "linear": 0.0, "angular": 1.0}
User says "stop" → {"action": "stop"}
User says "bow" → {"action": "preset", "name": "bow"}
User says "dance" → {"action": "preset", "name": "dance_with_beats"}
User says "stand up" → {"action": "stand"}
User says "lie down" → {"action": "preset", "name": "lie_on_elbows"}
User says "run forward" → {"action": "move", "linear": 1.0, "angular": 0.0}
User says "say hello" → {"action": "preset", "name": "wave_hand"}
User says "go slow" → {"action": "move", "linear": 0.3, "angular": 0.0}
"""


def process_voice_command(audio_base64: str, mime_type: str = "audio/webm") -> dict:
    """Send audio to Gemini, parse the spoken command, return a robot action dict.

    Args:
        audio_base64: Base64-encoded audio bytes (captured from browser MediaRecorder).
        mime_type: MIME type of the audio (default "audio/webm" for opus-in-webm).

    Returns:
        A dict with keys "action", and optionally "linear", "angular", or "name".
        On error, returns {"action": "error", "error": "<description>"}.
    """
    try:
        audio_bytes = base64.b64decode(audio_base64)
    except Exception as e:
        return {"action": "error", "error": f"Failed to decode audio: {e}"}

    try:
        response = _client.models.generate_content(
            model=_MODEL,
            contents=[
                types.Part(
                    inline_data=types.Blob(
                        data=audio_bytes,
                        mime_type=mime_type,
                    )
                ),
                types.Part(text=_SYSTEM_PROMPT),
            ],
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=200,
            ),
        )
    except Exception as e:
        return {"action": "error", "error": f"Gemini API call failed: {e}"}

    raw_text = response.text.strip()
    # Strip markdown code fences if present (e.g. ```json ... ```)
    raw_text = re.sub(r"^```(?:json)?\s*|```$", "", raw_text, flags=re.DOTALL).strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        return {"action": "error", "error": f"Gemini returned unparseable JSON: {raw_text}"}

    # Validate required fields
    if "action" not in result:
        return {"action": "error", "error": f"Response missing 'action' field: {result}"}

    return result
