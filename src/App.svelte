<script>
import { onMount } from "svelte";

let activeKeys = $state({ w: false, a: false, s: false, d: false, shift: false });
let connectionState = $state("disconnected"); // "disconnected" | "connecting" | "connected" | "failed"
let isMobile = $state(false);

const keyMap = {
    w: "w",
    a: "a",
    s: "s",
    d: "d",
    ArrowUp: "w",
    ArrowLeft: "a",
    ArrowDown: "s",
    ArrowRight: "d",
    W: "w",
    A: "a",
    S: "s",
    D: "d",
    Shift: "shift"
};

let socket = null;

function sendCommand(key, state) {
    if (activeKeys[key] !== state) {
        activeKeys[key] = state;
        console.log(
            `Action: ${key.toUpperCase()} is ${state ? "Pressed" : "Released"}`,
        );

        // If connected, transmit key state to the Python WebSocket server
        if (connectionState === "connected" && socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
                action: "move",
                w: activeKeys.w,
                a: activeKeys.a,
                s: activeKeys.s,
                d: activeKeys.d,
                shift: activeKeys.shift
            }));
        }
    }
}

function toggleShift() {
    sendCommand('shift', !activeKeys.shift);
}

function handleConnect() {
    if (connectionState === "disconnected" || connectionState === "failed") {
        connectionState = "connecting";

        // Determine host dynamically (allows mobile devices on local network to connect)
        const host = window.location.hostname || "localhost";
        console.log(`Connecting to WebSocket server at ws://${host}:8765...`);

        try {
            socket = new WebSocket(`ws://${host}:8765`);

            socket.onopen = () => {
                console.log("WebSocket channel opened. Requesting robot session...");
                socket.send(JSON.stringify({ action: "connect" }));
            };

            socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === "connect_status") {
                        connectionState = data.status;
                        if (data.status === "failed") {
                            console.error("Robot connection failed:", data.error);
                        }
                    }
                } catch (e) {
                    console.error("Failed to parse WebSocket message:", e);
                }
            };

            socket.onclose = () => {
                console.log("WebSocket connection closed.");
                connectionState = "disconnected";
                // Reset active keys
                activeKeys = { w: false, a: false, s: false, d: false, shift: false };
                socket = null;
            };

            socket.onerror = (error) => {
                console.error("WebSocket error:", error);
                connectionState = "failed";
            };

        } catch (e) {
            console.error("Failed to establish WebSocket:", e);
            connectionState = "failed";
        }
    } else if (connectionState === "connected") {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ action: "disconnect" }));
        }
    }
}

onMount(() => {
    const handleKey = (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        
        const key = keyMap[e.key];
        if (key) {
            e.preventDefault();
            sendCommand(key, e.type === "keydown");
        }
    };

    window.addEventListener("keydown", handleKey);
    window.addEventListener("keyup", handleKey);

    const checkMobile = () => {
        const hasTouch = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
        const isSmall = window.innerWidth <= 768;
        isMobile = hasTouch || isSmall;
    };
    
    checkMobile();
    window.addEventListener("resize", checkMobile);

    return () => {
        window.removeEventListener("keydown", handleKey);
        window.removeEventListener("keyup", handleKey);
        window.removeEventListener("resize", checkMobile);
        if (socket) {
            socket.close();
        }
    };
});

// Derived states for terminal console display
const consoleText = $derived(
    connectionState === "disconnected" ? "CONSOLE STANDBY: LINK OFFLINE" :
    connectionState === "connecting" ? "ESTABLISHING SECURE UPLINK TO ROBOT DOG..." :
    connectionState === "failed" ? "CONNECTION FAILURE: LINK TIMEOUT / OFFLINE" :
    activeKeys.w ? `● TRANSMITTING: SENDING FORWARD COMMAND${activeKeys.shift ? " (FAST)" : ""}` :
    activeKeys.a ? `● TRANSMITTING: SENDING LEFT TURN MESSAGE${activeKeys.shift ? " (FAST)" : ""}` :
    activeKeys.s ? `● TRANSMITTING: SENDING REVERSE COMMAND${activeKeys.shift ? " (FAST)" : ""}` :
    activeKeys.d ? `● TRANSMITTING: SENDING RIGHT TURN MESSAGE${activeKeys.shift ? " (FAST)" : ""}` :
    activeKeys.shift ? "● LINK STABLE: STANDING BY (FAST SPEED ACTIVE)" :
    "● LINK STABLE: STANDING BY FOR COMMAND"
);

const consoleClass = $derived(
    connectionState === "connecting" || connectionState === "failed" ? "offline" :
    connectionState === "connected" ? (activeKeys.w || activeKeys.a || activeKeys.s || activeKeys.d ? "active-transmitting" : "idle") :
    "idle"
);
</script>

<main>
  <div class="control-panel">
    <!-- Header -->
    <header class="panel-header">
      <h1>NaviControl v2.0</h1>
      <p>Robotics Tactical Interface</p>
    </header>

    <!-- Connection Box -->
    <section class="connection-box">
      <button 
        class="connect-btn {connectionState}" 
        onclick={handleConnect}
        disabled={connectionState === "connecting"}
      >
        {#if connectionState === "disconnected"}
          Connect Link
        {:else if connectionState === "connecting"}
          <span class="spinner"></span> Establishing...
        {:else if connectionState === "connected"}
          Disconnect Link
        {:else if connectionState === "failed"}
          Failed - Retry Link
        {/if}
      </button>

      <div class="status-indicator">
        <span class="status-dot {connectionState}"></span>
        {#if connectionState === "disconnected"}
          Link Status: Offline
        {:else if connectionState === "connecting"}
          Link Status: Synchronizing
        {:else if connectionState === "connected"}
          Link Status: Connected
        {:else if connectionState === "failed"}
          Link Status: Error
        {/if}
      </div>
    </section>

    <!-- Dpad Container (Centered) -->
    <section class="dpad-container">
      <div class="dpad">
        <div></div>
        <button 
          class:active={activeKeys.w} 
          onpointerdown={() => sendCommand('w', true)} 
          onpointerup={() => sendCommand('w', false)}
          onpointerleave={() => sendCommand('w', false)}
        >
          {isMobile ? '▲' : 'W'}
        </button>
        <div></div>

        <button 
          class:active={activeKeys.a} 
          onpointerdown={() => sendCommand('a', true)} 
          onpointerup={() => sendCommand('a', false)}
          onpointerleave={() => sendCommand('a', false)}
        >
          {isMobile ? '◀' : 'A'}
        </button>
        <button 
          class:active={activeKeys.s} 
          onpointerdown={() => sendCommand('s', true)} 
          onpointerup={() => sendCommand('s', false)}
          onpointerleave={() => sendCommand('s', false)}
        >
          {isMobile ? '▼' : 'S'}
        </button>
        <button 
          class:active={activeKeys.d} 
          onpointerdown={() => sendCommand('d', true)} 
          onpointerup={() => sendCommand('d', false)}
          onpointerleave={() => sendCommand('d', false)}
        >
          {isMobile ? '▶' : 'D'}
        </button>

        <button 
          class="shift-btn"
          class:active={activeKeys.shift}
          onpointerdown={isMobile ? null : () => sendCommand('shift', true)}
          onpointerup={isMobile ? null : () => sendCommand('shift', false)}
          onpointerleave={isMobile ? null : () => sendCommand('shift', false)}
          onclick={isMobile ? toggleShift : null}
        >
          RUN
        </button>
      </div>
    </section>

    <!-- HUD / Live Console Display -->
    <footer class="hud-console">
      <div class="console-text {consoleClass}">
        {consoleText}
      </div>
    </footer>
  </div>
</main>
