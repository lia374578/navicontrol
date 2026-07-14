import asyncio
from collections import deque

import ff_sdk
from ff_sdk.platforms.navi import NaviAdapter

# ── Tuning ────────────────────────────────────────────────────────────────────
# Calibrated from observed data: flat mean ~0.7–1.8 Nm, range ~0–0.8 Nm.
TERRAIN_POLL_HZ = 4.0
WINDOW_SIZE     = 4     # 1-second rolling window at 4 Hz

# Roughness — two independent signals; either one triggers "rough / uneven"
BUMP_RANGE      = 1.0   # Nm peak-to-valley in window
ASYM_ROUGH      = 0.40  # Nm left-right or front-rear imbalance (raised from 0.25)

# Slope — tune after seeing actual values in [live] output on a real slope
SLOPE_PITCH     = 0.08  # rad (~4.6°) forward / back
SLOPE_ROLL      = 0.06  # rad (~3.4°) side-to-side

# Yaw gate — suppress asym signal while the robot is turning.
# Turning causes an intentional rear-inner / front-outer loading pattern that
# looks identical to rough-terrain asymmetry. Check actual yaw values in [live]
# to tune; 0.20 rad/s ≈ gentle pivot on the spot.
YAW_GATE        = 0.25  # rad/s — above this, asym is suppressed

DEBOUNCE        = 2     # consecutive samples needed before announcing a label change
HEARTBEAT_SECS  = 5


# ── Helpers ───────────────────────────────────────────────────────────────────

def _leg_asymmetry(efforts: tuple) -> float:
    """Left-right and front-rear effort imbalance (max of the two).

    Compares same-side and same-row pairs rather than all four legs.
    A trot gait loads diagonal pairs (e.g. FR+RL), so same-side and
    same-row averages stay balanced — this returns ~0 on flat walking
    but spikes when one side of the body carries disproportionate load.

    Assumes leg ordering: L0=FR, L1=FL, L2=RR, L3=RL (groups of 3 joints).
    """
    if len(efforts) < 12:
        return 0.0
    leg_means = [
        sum(abs(efforts[i * 3 + j]) for j in range(3)) / 3
        for i in range(4)
    ]
    lr = abs((leg_means[0] + leg_means[2]) / 2 - (leg_means[1] + leg_means[3]) / 2)
    fb = abs((leg_means[0] + leg_means[1]) / 2 - (leg_means[2] + leg_means[3]) / 2)
    return max(lr, fb)


def _classify(
    effort_range: float, leg_asym: float,
    pitch: float, roll: float, yaw_rate: float,
) -> str:
    if abs(pitch) >= SLOPE_PITCH or abs(roll) >= SLOPE_ROLL:
        direction = "fwd/back" if abs(pitch) >= abs(roll) else "side"
        return f"slope ({direction})"
    if effort_range >= BUMP_RANGE:
        return "rough / uneven"
    # Only use asym when the robot is not turning — a yaw rate above the gate
    # means the controller is intentionally creating the leg imbalance.
    if leg_asym >= ASYM_ROUGH and abs(yaw_rate) < YAW_GATE:
        return "rough / uneven"
    return "flat / smooth"


# ── Monitor loop ──────────────────────────────────────────────────────────────

async def monitor_terrain(robot, navi) -> None:
    period = 1.0 / TERRAIN_POLL_HZ
    window: deque[float] = deque(maxlen=WINDOW_SIZE)
    loop = asyncio.get_event_loop()

    current_label  = ""
    pending_label  = ""
    pending_count  = 0
    heartbeat_ticks = int(HEARTBEAT_SECS * TERRAIN_POLL_HZ)
    tick = 0
    names_printed = False
    imu_available = True

    print("Terrain monitor — drive with the remote. Ctrl+C to stop.\n")

    while True:
        t0 = loop.time()
        try:
            # Fetch joint states; fetch IMU in parallel if available
            if imu_available:
                results = await asyncio.gather(
                    robot.state.joint_states(),
                    navi.read_imu(),
                    return_exceptions=True,
                )
                js = results[0]
                imu_result = results[1]

                if isinstance(imu_result, Exception):
                    imu_available = False
                    print(f"  [terrain] IMU unavailable ({imu_result}); slope detection off")
                    pitch, roll, yaw_rate = 0.0, 0.0, 0.0
                else:
                    pitch, roll, yaw_rate = imu_result

                if isinstance(js, Exception):
                    raise js
            else:
                js = await robot.state.joint_states()
                pitch, roll, yaw_rate = 0.0, 0.0, 0.0

            if not names_printed and js.names:
                print(f"  Joints ({len(js.names)}): {', '.join(js.names)}\n")
                names_printed = True

            if js.efforts:
                mean_e = sum(abs(e) for e in js.efforts) / len(js.efforts)
                window.append(mean_e)

            if len(window) == WINDOW_SIZE:
                smooth = sum(window) / len(window)
                rng    = max(window) - min(window)
                asym   = _leg_asymmetry(js.efforts)
                label  = _classify(rng, asym, pitch, roll, yaw_rate)

                if label == pending_label:
                    pending_count += 1
                else:
                    pending_label = label
                    pending_count = 1

                if pending_count >= DEBOUNCE and label != current_label:
                    current_label = label
                    print(
                        f"Terrain: {label:<28}"
                        f"  mean={smooth:.2f}  range={rng:.2f}"
                        f"  asym={asym:.2f}  yaw={yaw_rate:+.2f}"
                        f"  pitch={pitch:+.3f}  roll={roll:+.3f}"
                    )

                tick += 1
                if tick % heartbeat_ticks == 0:
                    mean_v = (
                        sum(abs(v) for v in js.velocities) / len(js.velocities)
                        if js.velocities else 0.0
                    )
                    max_v = max(abs(v) for v in js.velocities) if js.velocities else 0.0

                    leg_str = ""
                    if len(js.efforts) >= 12:
                        leg_means = [
                            sum(abs(js.efforts[i * 3 + j]) for j in range(3)) / 3
                            for i in range(4)
                        ]
                        leg_str = "  ".join(f"L{i}={m:.2f}" for i, m in enumerate(leg_means))

                    print(
                        f"  [live] {current_label}\n"
                        f"    effort : mean={smooth:.2f} Nm  range={rng:.2f} Nm  asym={asym:.2f} Nm\n"
                        f"    imu    : pitch={pitch:+.4f} rad  roll={roll:+.4f} rad"
                        f"  yaw_rate={yaw_rate:+.3f} rad/s\n"
                        f"    vel    : mean={mean_v:.2f} rad/s  max={max_v:.2f} rad/s"
                        + (f"\n    legs   : {leg_str}" if leg_str else "")
                    )

        except Exception as exc:
            print(f"[terrain] {exc}")

        remaining = period - (loop.time() - t0)
        if remaining > 0:
            await asyncio.sleep(remaining)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    robot = await ff_sdk.connect("NV-dev001")
    assert isinstance(robot.adapter, NaviAdapter)
    navi = robot.adapter.navi
    print(robot.diagnose().summary())

    await robot.motion.stand()
    await asyncio.sleep(2)

    try:
        await monitor_terrain(robot, navi)
    except KeyboardInterrupt:
        pass
    finally:
        await robot.close()
        print("Done.")


asyncio.run(main())
