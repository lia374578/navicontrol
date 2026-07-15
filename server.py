import asyncio
import json
import websockets
import ff_sdk

async def handler(websocket):
    print("\n[Server] Client connected to interface.")
    robot = None
    active_keys = {"w": False, "a": False, "s": False, "d": False, "shift": False}
    is_moving = False
    loop_task = None
    is_standing = False

    async def robot_control_loop():
        nonlocal is_moving
        print("[Server] Starting active 10Hz control loop.")
        while True:
            try:
                if robot:
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
                            print("[Server] Sending Sit command...")
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
                active_keys["w"] = data.get("w", False)
                active_keys["a"] = data.get("a", False)
                active_keys["s"] = data.get("s", False)
                active_keys["d"] = data.get("d", False)
                active_keys["shift"] = data.get("shift", False)

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
                    print("[Server] Restoring sitting state...")
                    await robot.motion.stand()
                    await asyncio.sleep(2.0)
                await robot.close()
                print("[Server] Cleaned up successfully.")
            except Exception as e:
                print(f"[Server] Cleanup failed: {e}")
            robot = None

async def main():
    print("[Server] Starting NaviControl WebSocket Server on ws://localhost:8765")
    async with websockets.serve(handler, "0.0.0.0", 8765):
        await asyncio.Future()  # Keep running indefinitely

if __name__ == "__main__":
    asyncio.run(main())
