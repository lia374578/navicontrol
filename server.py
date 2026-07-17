import asyncio
import json
import os
import websockets
import ff_sdk
from ff_sdk import Session
from voice_command import process_voice_command

async def handler(websocket):
    print("\n[Server] Client connected to interface.")
    robot: Session | None = None
    active_keys = {"w": False, "a": False, "s": False, "d": False, "shift": False}
    is_moving = False
    loop_task = None
    is_standing = False
    voice_active = False  # when True, control loop won't override voice commands
    voice_linear = 0.0    # continuous voice velocity (non-zero keeps moving)
    voice_angular = 0.0
    realtime_openai = None
    realtime_relay_task = None

    async def robot_control_loop():
        nonlocal is_moving, voice_active, voice_linear, voice_angular
        print("[Server] Starting active 10Hz control loop.")
        assert robot is not None  # only created after robot is connected
        while True:
            try:
                if voice_linear != 0.0 or voice_angular != 0.0:
                    # Continuous voice move — keep sending velocity at 10Hz
                    await robot.motion.cmd_vel(linear=voice_linear, angular=voice_angular)
                    is_moving = True
                elif robot and not voice_active:
                    w = active_keys.get("w", False)
                    a = active_keys.get("a", False)
                    s = active_keys.get("s", False)
                    d = active_keys.get("d", False)
                    shift = active_keys.get("shift", False)

                    LINEAR_SPEED = 1.0 if shift else 0.5
                    ANGULAR_SPEED = 2.0

                    linear = 0.0
                    angular = 0.0

                    if w:
                        linear = LINEAR_SPEED
                    elif s:
                        linear = -LINEAR_SPEED

                    if a:
                        angular = ANGULAR_SPEED
                    elif d:
                        angular = -ANGULAR_SPEED

                    if linear != 0.0 or angular != 0.0:
                        await robot.motion.cmd_vel(linear=linear, angular=angular)
                        is_moving = True
                    else:
                        if is_moving:
                            print("[Server] Idle state. Sending motion stop command.")
                            await robot.motion.stop()
                            is_moving = False
            except Exception as e:
                print(f"[Server] Control loop error: {e}")
            await asyncio.sleep(0.1)

    try:
        async for message in websocket:
            data = json.loads(message)
            action = data.get("action")

            if action == "connect":
                if robot is not None:
                    await websocket.send(json.dumps({"type": "connect_status", "status": "connected"}))
                    continue

                print("[Server] Connection requested. Establishing session with 'NV-dev001'...")
                try:
                    robot = await ff_sdk.connect("NV-dev001")
                    print("[Server] Successfully connected to robot dog.")
                    
                    print("[Server] Sending Stand command...")
                    await robot.motion.stand()
                    is_standing = True
                    await asyncio.sleep(2.0)
                    
                    # Start the 10Hz cmd_vel control loop task
                    loop_task = asyncio.create_task(robot_control_loop())

                    await websocket.send(json.dumps({"type": "connect_status", "status": "connected"}))
                    print("[Server] Status sent to frontend: Connected.")
                    # List available action IDs for custom animations
                    try:
                        navi_ext = robot.adapter.navi  # type: ignore[attr-defined]
                        if hasattr(navi_ext, 'list_actions'):
                            actions = await navi_ext.list_actions()
                            print(f"[Server] Available navi actions type: {type(actions).__name__}")
                            # Try to iterate and print
                            try:
                                for a in list(actions)[:30]:
                                    print(f"  {a}")
                            except:
                                print(f"  {actions}")
                    except Exception as e:
                        print(f"[Server] Could not list navi actions: {e}")
                except Exception as e:
                    print(f"[Server] Failed to connect: {e}")
                    await websocket.send(json.dumps({
                        "type": "connect_status", 
                        "status": "failed", 
                        "error": str(e)
                    }))
                    robot = None

            elif action == "disconnect":
                print("[Server] Disconnect requested by client.")
                if loop_task:
                    loop_task.cancel()
                    loop_task = None
                if robot:
                    try:
                        print("[Server] Stopping motions...")
                        await robot.motion.stop()
                        if is_standing:
                            print("[Server] Sending Stand command...")
                            await robot.motion.stand()
                            await asyncio.sleep(2.0)
                        await robot.close()
                        print("[Server] Session closed cleanly.")
                    except Exception as e:
                        print(f"[Server] Error during disconnect: {e}")
                    robot = None
                    is_standing = False
                await websocket.send(json.dumps({"type": "connect_status", "status": "disconnected"}))

            elif action == "move":
                # Keyboard/d-pad move: clear voice state, let control loop process
                voice_active = False
                voice_linear = 0.0
                voice_angular = 0.0
                active_keys["w"] = data.get("w", False)
                active_keys["a"] = data.get("a", False)
                active_keys["s"] = data.get("s", False)
                active_keys["d"] = data.get("d", False)
                active_keys["shift"] = data.get("shift", False)

            elif action == "voice_command":
                # Quick voice command from browser SpeechRecognition keyword match
                if robot is None:
                    await websocket.send(json.dumps({"type": "voice_status", "status": "error", "error": "Not connected to robot"}))
                    continue
                cmd = data.get("command", {})
                print(f"[Server] Quick voice command received: {cmd}")
                await websocket.send(json.dumps({"type": "voice_status", "status": "processing"}))

                try:
                    if loop_task:
                        loop_task.cancel()
                        loop_task = None

                    action_type = cmd.get("action")
                    if action_type == "move":
                        linear = cmd.get("linear", 0.5)
                        angular = cmd.get("angular", 0.0)
                        duration = cmd.get("duration", 0)
                        # Always let 10Hz loop keep velocity alive
                        voice_active = False
                        voice_linear = linear
                        voice_angular = angular
                        if duration > 0:
                            # Schedule auto-stop that clears velocities
                            async def auto_stop():
                                await asyncio.sleep(duration)
                                nonlocal voice_linear, voice_angular
                                voice_linear = 0.0
                                voice_angular = 0.0
                                await robot.motion.stop()
                                print(f"[Server] Auto-stop after {duration}s")
                            asyncio.create_task(auto_stop())
                        active_keys = {k: False for k in active_keys}
                        is_moving = False
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "ok",
                            "command": f"move(linear={linear}, angular={angular})"
                        }))
                        print("[Server] Voice move command executed successfully")

                    elif action_type == "stop":
                        voice_active = False
                        voice_linear = 0.0
                        voice_angular = 0.0
                        print("[Server] Executing voice stop")
                        await robot.motion.stop()
                        active_keys = {k: False for k in active_keys}
                        is_moving = False
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "ok", "command": "stop"
                        }))
                        print("[Server] Voice stop executed")

                    elif action_type == "stand":
                        voice_active = False
                        print("[Server] Executing voice stand")
                        await robot.motion.stand()
                        is_standing = True
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "ok", "command": "stand"
                        }))
                        print("[Server] Voice stand executed")

                    elif action_type == "damping":
                        voice_active = False
                        print("[Server] Executing voice damping")
                        await robot.motion.damping()
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "ok", "command": "damping"
                        }))
                        print("[Server] Voice damping executed")

                    elif action_type == "preset":
                        preset_name = cmd.get("name", "")
                        voice_active = True
                        print(f"[Server] Executing voice preset: {preset_name}")
                        try:
                            await robot.motion.do_preset(preset_name)
                        except Exception as e:
                            err = str(e)
                            if 'do_action' in err or 'presets' in err:
                                print("[Server] do_preset failed, trying adapter.navi.do_action()...")
                                action_map = {"dance_with_beats": 20600, "bow": 20510, "wave_hand": 20542, "shake_hand": 20541, "clap_hand": 20543, "lion_dance": 20587, "jump_forward": 20607, "draw_heart": 20608, "bark": 20525, "nod_head": 20521, "wag_tail": 20511}
                                # Per-animation hold times (seconds) — overestimate for safety
                                hold_times = {"dance_with_beats": 8, "bow": 4, "wave_hand": 5, "shake_hand": 4, "clap_hand": 4, "lion_dance": 14, "jump_forward": 4, "draw_heart": 10, "bark": 4, "nod_head": 4, "wag_tail": 4}
                                aid = action_map.get(preset_name, 0)
                                hold = hold_times.get(preset_name, 6)
                                print(f"[Server] navi action {aid} with hold_time={hold}s")
                                try:
                                    result = await robot.adapter.navi.do_action(action_id=aid, hold_time=hold)  # type: ignore[attr-defined]
                                    print(f"[Server] navi.do_action({aid}) result: {result}")
                                except Exception as e2:
                                    print(f"[Server] navi.do_action also failed: {e2}")
                                    raise e
                        active_keys = {k: False for k in active_keys}
                        is_moving = False
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "ok",
                            "command": f"preset({preset_name})"
                        }))
                        print("[Server] Voice preset executed")

                    else:
                        voice_active = False
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "error",
                            "error": f"Unknown quick action: {action_type}"
                        }))

                    loop_task = asyncio.create_task(robot_control_loop())

                except Exception as e:
                    print(f"[Server] Quick voice command error: {e}")
                    voice_active = False
                    await websocket.send(json.dumps({
                        "type": "voice_status", "status": "error", "error": str(e)
                    }))

            elif action == "voice":
                if robot is None:
                    await websocket.send(json.dumps({"type": "voice_status", "status": "error", "error": "Not connected to robot"}))
                    continue
                audio_b64 = data.get("audio", "")
                mime_type = data.get("mime_type", "audio/webm")
                print(f"[Server] Processing voice command ({len(audio_b64)} bytes base64)...")

                await websocket.send(json.dumps({"type": "voice_status", "status": "processing"}))

                cmd = process_voice_command(audio_b64, mime_type=mime_type)
                print(f"[Server] Voice command parsed: {cmd}")

                action_type = cmd.get("action")
                try:
                    # Stop the control loop so it doesn't fight voice commands
                    if loop_task:
                        loop_task.cancel()
                        loop_task = None

                    if action_type == "move":
                        linear = cmd.get("linear", 0.0)
                        angular = cmd.get("angular", 0.0)
                        voice_active = True
                        await robot.motion.cmd_vel(linear=linear, angular=angular)
                        active_keys = {k: False for k in active_keys}
                        is_moving = False
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "ok",
                            "command": f"move(linear={linear}, angular={angular})"
                        }))

                    elif action_type == "stop":
                        voice_active = False
                        await robot.motion.stop()
                        active_keys = {k: False for k in active_keys}
                        is_moving = False
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "ok", "command": "stop"
                        }))

                    elif action_type == "stand":
                        voice_active = False
                        await robot.motion.stand()
                        is_standing = True
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "ok", "command": "stand"
                        }))

                    elif action_type == "damping":
                        voice_active = False
                        await robot.motion.damping()
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "ok", "command": "damping"
                        }))

                    elif action_type == "preset":
                        preset_name = cmd.get("name", "")
                        voice_active = True
                        await robot.motion.do_preset(preset_name)
                        active_keys = {k: False for k in active_keys}
                        is_moving = False
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "ok",
                            "command": f"preset({preset_name})"
                        }))

                    elif action_type == "error":
                        voice_active = False
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "error",
                            "error": cmd.get("error", "Unknown error")
                        }))

                    else:
                        voice_active = False
                        await websocket.send(json.dumps({
                            "type": "voice_status", "status": "error",
                            "error": f"Unknown action: {action_type}"
                        }))

                    # Re-start the control loop so keyboard commands work again
                    loop_task = asyncio.create_task(robot_control_loop())

                except Exception as e:
                    print(f"[Server] Voice command execution error: {e}")
                    voice_active = False
                    await websocket.send(json.dumps({
                        "type": "voice_status", "status": "error", "error": str(e)
                    }))

            elif action == "create_realtime_session":
                api_key = os.environ.get("OPENAI_API_KEY", "")
                if not api_key:
                    await websocket.send(json.dumps({
                        "type": "realtime_session", "status": "error",
                        "error": "OPENAI_API_KEY not configured on server"
                    }))
                    continue

                try:
                    # Server connects directly to OpenAI Realtime with proper auth
                    openai_ws = await websockets.connect(
                        "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1",
                        additional_headers={"Authorization": f"Bearer {api_key}"},
                        ssl=True
                    )
                    print("[Server] Connected to OpenAI Realtime.")
                    realtime_openai = openai_ws

                    # Start relay IMMEDIATELY so no events are missed
                    relay_accumulator = ""  # buffer for transcript printing

                    async def relay_openai_to_browser():
                        nonlocal relay_accumulator
                        try:
                            async for msg in openai_ws:
                                event = json.loads(msg)
                                event_type = event.get("type", "?")
                                if event_type == "response.output_audio_transcript.delta":
                                    relay_accumulator += event.get("delta", "")
                                elif event_type == "response.output_audio_transcript.done":
                                    if relay_accumulator:
                                        print(f"[Server] AI: {relay_accumulator}")
                                    relay_accumulator = ""
                                elif event_type == "response.function_call_arguments.done":
                                    print(f"[Server] AI calls: {event.get('name', '?')}({event.get('arguments', '{}')})")
                                elif event_type == "response.done":
                                    print("[Server] Response done.")
                                elif event_type == "error":
                                    print(f"[Server] OpenAI error: {event.get('error', {}).get('message', str(event))}")
                                elif event_type in ("response.output_audio.delta", "response.output_audio.done", "rate_limits.updated"):
                                    pass  # skip high-frequency noise
                                else:
                                    print(f"[Server] Event: {event_type}")
                                await websocket.send(json.dumps({
                                    "type": "realtime_event",
                                    "event": event
                                }))
                        except websockets.exceptions.ConnectionClosed:
                            pass
                        except Exception as e:
                            print(f"[Server] OpenAI relay error: {e}")
                        finally:
                            nonlocal realtime_openai, realtime_relay_task
                            realtime_openai = None
                            realtime_relay_task = None
                            await websocket.send(json.dumps({
                                "type": "realtime_event",
                                "event": {"type": "relay_closed"}
                            }))

                    realtime_relay_task = asyncio.create_task(relay_openai_to_browser())

                    # Send session configuration
                    print("[Server] Sending session.update...")
                    await openai_ws.send(json.dumps({
                        "type": "session.update",
                        "session": {
                            "type": "realtime",
                            "instructions": "Your name is Navi. You control a robot dog. Use bracketed codes. IMPORTANT: angular= turn rate (positive=left, negative=right) — this rotates in place, not sideways. Parameters: speed=0.0-1.0, angular=-2.0-2.0, duration=seconds. Codes: [forward speed=0.5] move forward, [back speed=0.5] reverse, [stop], [stand], [dance], [bow], [wave/hello], [shake], [clap], [lion], [jump], [heart], [bark], [nod], [wag], [cute], [think], [sleepy]. Combine: [forward speed=0.5 angular=0.5 duration=3]. Chat naturally without brackets when no action needed."
                        }
                    }))
                    print("[Server] Session.update sent.")

                    await websocket.send(json.dumps({"type": "realtime_session", "status": "ok"}))
                    print("[Server] OpenAI Realtime proxy established.")

                except Exception as e:
                    print(f"[Server] OpenAI Realtime connection failed: {e}")
                    await websocket.send(json.dumps({
                        "type": "realtime_session", "status": "error", "error": str(e)
                    }))

            elif action == "realtime_audio":
                if realtime_openai:
                    audio_b64 = data.get("audio", "")
                    if audio_b64:
                        await realtime_openai.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": audio_b64
                        }))

            elif action == "realtime_commit":
                if realtime_openai:
                    await realtime_openai.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    await realtime_openai.send(json.dumps({"type": "response.create"}))

            elif action == "realtime_function_result":
                if realtime_openai:
                    await realtime_openai.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": data.get("call_id", ""),
                            "output": data.get("output", "{}")
                        }
                    }))
                    await realtime_openai.send(json.dumps({"type": "response.create"}))

            elif action == "realtime_disconnect":
                if realtime_openai:
                    await realtime_openai.close()
                realtime_openai = None
                if realtime_relay_task:
                    realtime_relay_task.cancel()
                    realtime_relay_task = None

    except websockets.exceptions.ConnectionClosed:
        print("[Server] Client WebSocket connection closed unexpectedly.")
    finally:
        # Guarantee cleanup if WebSocket connection drops
        if loop_task:
            loop_task.cancel()
        if robot:
            print("[Server] Performing emergency session cleanup...")
            try:
                await robot.motion.stop()
                if is_standing:
                    print("[Server] Sending Stand command...")
                    await robot.motion.stand()
                    await asyncio.sleep(2.0)
                await robot.close()
                print("[Server] Cleaned up successfully.")
            except Exception as e:
                print(f"[Server] Cleanup failed: {e}")
            robot = None
        # Clean up OpenAI Realtime connection if client dropped
        if realtime_openai:
            try:
                await realtime_openai.close()
            except:
                pass
            realtime_openai = None
            realtime_relay_task = None

async def main():
    print("[Server] Starting NaviControl WebSocket Server on ws://localhost:8765")
    async with websockets.serve(handler, "0.0.0.0", 8765):
        await asyncio.Future()  # Keep running indefinitely

if __name__ == "__main__":
    asyncio.run(main())
