import asyncio
import math
import ff_sdk

# Motion parameters
LINEAR_SPEED = 0.2  # m/s (safe slow speed)
ANGULAR_SPEED = 0.5  # rad/s (~28.6 deg/s)

# Durations
BASE_MOVE_DURATION = 2.0  # seconds
TURN_90_DURATION = (math.pi / 2) / ANGULAR_SPEED   # ~3.14 seconds
TURN_180_DURATION = math.pi / ANGULAR_SPEED        # ~6.28 seconds


async def send_cmd_vel(robot, linear: float, angular: float, duration: float, rate_hz: float = 10.0):
    """Sends velocity commands at rate_hz frequency for duration seconds."""
    interval = 1.0 / rate_hz
    steps = max(1, int(duration * rate_hz))
    
    for _ in range(steps):
        await robot.motion.cmd_vel(linear=linear, angular=angular)
        await asyncio.sleep(interval)
        
    # Send a stop command at the end of each motion phase
    await robot.motion.stop()


async def main():
    print("Connecting to robot...")
    robot = await ff_sdk.connect("NV-dev001")
    print("Connected.")
    print(robot.diagnose().summary())

    try:
        print("Starting sequence: Standing up (stand command)...")
        await robot.motion.stand()
        await asyncio.sleep(2.0)  # Wait for stand transition to complete

        # 1. Move forward
        print(f"1. Moving forward for {BASE_MOVE_DURATION}s...")
        await send_cmd_vel(robot, linear=LINEAR_SPEED, angular=0.0, duration=BASE_MOVE_DURATION)
        await asyncio.sleep(1.0)

        # 2. Turn 90 degrees
        print(f"2. Turning 90 degrees (~{TURN_90_DURATION:.2f}s)...")
        await send_cmd_vel(robot, linear=0.0, angular=ANGULAR_SPEED, duration=TURN_90_DURATION)
        await asyncio.sleep(1.0)

        # 3. Move forward twice the distance
        double_duration = BASE_MOVE_DURATION * 2
        print(f"3. Moving forward twice the distance ({double_duration}s)...")
        await send_cmd_vel(robot, linear=LINEAR_SPEED, angular=0.0, duration=double_duration)
        await asyncio.sleep(1.0)

        # 4. Turn 180 degrees
        print(f"4. Turning 180 degrees (~{TURN_180_DURATION:.2f}s)...")
        await send_cmd_vel(robot, linear=0.0, angular=ANGULAR_SPEED, duration=TURN_180_DURATION)
        await asyncio.sleep(1.0)

        # 5. Move backwards
        print(f"5. Moving backwards for {BASE_MOVE_DURATION}s...")
        await send_cmd_vel(robot, linear=-LINEAR_SPEED, angular=0.0, duration=BASE_MOVE_DURATION)
        await asyncio.sleep(1.0)

        # Stop sequence: toggling stand back to sitting/lying down
        print("Stopping sequence: Sitting/Lying down (stand command)...")
        await robot.motion.stand()
        await asyncio.sleep(2.0)  # Wait for sit transition to complete

        print("Motion sequence complete.")

    except KeyboardInterrupt:
        print("Interrupted by user.")
    finally:
        print("Stopping robot velocity and closing session...")
        try:
            await robot.motion.stop()
        except Exception as e:
            print(f"Failed to stop robot: {e}")
        await robot.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
