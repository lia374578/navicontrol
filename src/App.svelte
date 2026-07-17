<script>
import { onMount } from "svelte";

let activeKeys = $state({ w: false, a: false, s: false, d: false, shift: false });
let connectionState = $state("disconnected");
let isMobile = $state(false);

let isRecording = $state(false);
let voiceCommand = $state("");
let voiceStatusText = $state("");
let speechRecognition = null;
let speechRecognitionSupported = $state(false);

let voiceMode = $state("keywords");
let aiAgentReady = $state(false);
let aiAgentConnecting = $state(false);
let audioContextAI = null;
let mediaStreamAI = null;
let audioProcessorAI = null;
let aiTranscript = $state("");
let aiResponses = $state([]);
let chatPanelEl = $state(null);

function ensureSpeechRecognition() {
  if (speechRecognition) return true;
  const win = (window);
  const SR = win.SpeechRecognition || win.webkitSpeechRecognition;
  if (!SR) {
    voiceStatusText = "Speech API not supported";
    console.log("Speech API not supported in this browser");
    return false;
  }

  speechRecognition = new SR();
  speechRecognition.continuous = true;
  speechRecognition.interimResults = true;
  speechRecognition.lang = "en-US";

  speechRecognition.onstart = () => {
    if (!voiceStatusText || voiceStatusText === "Starting mic...") {
      voiceStatusText = "Listening...";
    }
    console.log("SpeechRecognition: started, listening...");
  };

  speechRecognition.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript.toLowerCase().trim();
      const isFinal = event.results[i].isFinal;
      console.log("SpeechRecognition heard:", transcript, isFinal ? "(final)" : "(interim)");
      voiceStatusText = `Heard: "${transcript}"${isFinal ? " ✓" : ""}`;

      if (isFinal) {
        const words = transcript.split(/\s+/);
        for (const word of words) {
          const cmd = keywordActions[word];
          if (cmd) {
            console.log("SpeechRecognition matched:", word);
            voiceStatusText = `Matched: ${word}`;
            sendVoiceCommand(cmd);
            return;
          }
        }
      }
    }
  };

  speechRecognition.onerror = (event) => {
    if (event.error === "aborted" || event.error === "no-speech") {
      console.log("SpeechRecognition:", event.error, "(expected)");
      return;
    }
    voiceStatusText = `Error: ${event.error}`;
    console.warn("SpeechRecognition error:", event.error);
  };

  speechRecognition.onend = () => {
    console.log("SpeechRecognition: session ended, isRecording =", isRecording);
    if (isRecording) {
      console.log("SpeechRecognition: restarting while still held...");
      try { speechRecognition.start(); } catch (e) {}
    }
  };

  return true;
}

function startSpeechRecognition() {
  if (!ensureSpeechRecognition()) return;
  voiceStatusText = "Starting mic...";
  console.log("SpeechRecognition: starting");
  try {
    speechRecognition.start();
  } catch (e) {
    voiceStatusText = `Failed to start: ${(e).message}`;
    console.warn("SpeechRecognition start failed:", e);
  }
}

function stopSpeechRecognition() {
  if (speechRecognition) {
    try { speechRecognition.stop(); } catch (e) {}
  }
}

const keywordActions = {
  "go": { action: "move", linear: 0.5, angular: 0.0 },
  "forward": { action: "move", linear: 0.5, angular: 0.0 },
  "move": { action: "move", linear: 0.5, angular: 0.0 },
  "walk": { action: "move", linear: 0.5, angular: 0.0 },
  "run": { action: "move", linear: 1.0, angular: 0.0 },
  "fast": { action: "move", linear: 1.0, angular: 0.0 },
  "back": { action: "move", linear: -0.5, angular: 0.0 },
  "backward": { action: "move", linear: -0.5, angular: 0.0 },
  "reverse": { action: "move", linear: -0.5, angular: 0.0 },
  "left": { action: "move", linear: 0.0, angular: 1.0 },
  "right": { action: "move", linear: 0.0, angular: -1.0 },
  "stop": { action: "stop" },
  "halt": { action: "stop" },
  "stand": { action: "stand" },
  "sit": { action: "stand" },
  "dance": { action: "preset", name: "dance_with_beats" },
  "bow": { action: "preset", name: "bow" },
  "hello": { action: "preset", name: "wave_hand" },
  "wave": { action: "preset", name: "wave_hand" },
  "shake": { action: "preset", name: "shake_hand" },
  "clap": { action: "preset", name: "clap_hand" },
  "lion": { action: "preset", name: "lion_dance" },
  "jump": { action: "preset", name: "jump_forward" },
  "heart": { action: "preset", name: "draw_heart" },
  "bark": { action: "preset", name: "bark" },
  "nod": { action: "preset", name: "nod_head" },
  "wag": { action: "preset", name: "wag_tail" },
  "cute": { action: "preset", name: "cute" },
  "think": { action: "preset", name: "think" },
  "sleepy": { action: "preset", name: "be_sleepy" }
};

function sendVoiceCommand(cmd) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    console.log("sendVoiceCommand: socket not open, cannot send");
    return;
  }
  console.log("sendVoiceCommand: sending via WebSocket:", JSON.stringify(cmd));
  socket.send(JSON.stringify({
    action: "voice_command",
    command: cmd
  }));
  voiceCommand = cmd.action + (cmd.linear !== undefined ? ` linear=${cmd.linear}` : "") + (cmd.angular !== undefined ? ` angular=${cmd.angular}` : "") + (cmd.name ? ` name=${cmd.name}` : "");
}

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
                    } else if (data.type === "voice_status") {
                        if (data.status === "ok" && data.command) {
                            voiceCommand = data.command;
                        }
                    } else if (data.type === "realtime_session") {
                        if (data.status === "ok") {
                            aiAgentReady = true;
                            aiAgentConnecting = false;
                            voiceStatusText = "AI Agent ready — tap to talk";
                        } else {
                            aiAgentConnecting = false;
                            voiceStatusText = `AI Agent error: ${data.error || "unknown"}`;
                        }
                    } else if (data.type === "realtime_event") {
                        handleRealtimeEvent(data.event);
                    }
                } catch (e) {
                    console.error("Failed to parse WebSocket message:", e);
                }
            };

            socket.onclose = () => {
                console.log("WebSocket connection closed.");
                connectionState = "disconnected";
                if (aiAgentReady) disconnectAIAgent();
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

function handleMicStart() {
    if (isRecording) return;
    if (connectionState !== "connected" || !socket) {
        console.log("handleMicStart: not connected, aborting");
        return;
    }
    console.log("handleMicStart:", voiceMode === "ai-agent" ? "AI agent mode" : "keyword mode");
    isRecording = true;
    voiceCommand = "";
    if (voiceMode === "ai-agent") {
        handleAIMicStart();
    } else {
        voiceStatusText = "";
        startSpeechRecognition();
    }
}

function handleMicEnd() {
    console.log("handleMicEnd:", voiceMode === "ai-agent" ? "AI agent mode" : "keyword mode");
    if (voiceMode === "ai-agent") {
        handleAIMicEnd();
        return;
    }
    stopSpeechRecognition();
    if (voiceStatusText === "Listening...") {
        voiceStatusText = "No speech detected";
    }
    setTimeout(() => { voiceStatusText = ""; }, 1500);
    isRecording = false;
}

function handleBigButtonPress() {
    if (voiceMode === "ai-agent" && !aiAgentReady && !aiAgentConnecting) {
        connectAIAgent();
    } else if (voiceMode === "ai-agent" && aiAgentReady) {
        if (isRecording) {
            handleMicEnd();
        } else {
            handleMicStart();
        }
    } else {
        handleMicStart();
    }
}

function handleBigButtonRelease() {
    if (isRecording && voiceMode !== "ai-agent") {
        handleMicEnd();
    }
}

function connectAIAgent() {
    if (aiAgentReady || aiAgentConnecting || !socket) return;
    aiAgentConnecting = true;
    voiceStatusText = "Requesting AI Agent session...";
    socket.send(JSON.stringify({ action: "create_realtime_session" }));
}

function disconnectAIAgent() {
    if (mediaStreamAI) { mediaStreamAI.getTracks().forEach(t => t.stop()); mediaStreamAI = null; }
    if (audioContextAI) { audioContextAI.close(); audioContextAI = null; }
    audioProcessorAI = null;
    aiAgentReady = false;
    aiAgentConnecting = false;
    voiceStatusText = "AI Agent disconnected";
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ action: "realtime_disconnect" }));
    }
}

function handleRealtimeEvent(msg) {
    switch (msg.type) {
        case "session.created":
            voiceStatusText = "AI Agent ready — tap to talk";
            break;
        case "input_audio_buffer.speech_started":
            if (isRecording) voiceStatusText = "🎤 Speaking...";
            break;
        case "input_audio_buffer.speech_stopped":
            if (isRecording) voiceStatusText = "🤖 Thinking...";
            break;
        case "response.output_audio_transcript.delta":
            if (isRecording) voiceStatusText = "🤖 Responding...";
            aiTranscript += msg.delta || "";
            break;
        case "response.output_audio_transcript.done":
            if (aiTranscript.trim()) {
                aiResponses = [...aiResponses, aiTranscript.trim()];
                parseTranscriptCommand(aiTranscript.trim());
                aiTranscript = "";
            }
            if (isRecording) voiceStatusText = "🎤 Listening...";
            break;
        case "response.done":
            if (isRecording) voiceStatusText = "🎤 Listening...";
            break;
        case "relay_closed":
            aiAgentReady = false;
            aiAgentConnecting = false;
            voiceStatusText = "AI Agent disconnected";
            break;
        case "response.function_call_arguments.done":
            handleAIFunctionCall(msg);
            break;
        case "conversation.item.created":
            if (msg.item?.type === "text" && isRecording) {
                voiceStatusText = msg.item.text;
            }
            break;
        case "response.text.delta":
            if (isRecording) voiceStatusText = msg.delta;
            break;
    }
}

function parseTranscriptCommand(text) {
    const cmdRegex = /\[([\w/]+)((?:[-\s]\w+=[-"\d.]+)*)\]/gi;
    let cmdDelayMs = 0;
    let cmdMatch;
    while ((cmdMatch = cmdRegex.exec(text)) !== null) {
        const name = cmdMatch[1].toLowerCase();
        const params = ({});
        const paramRegex = /(\w+)=(-?[\d.]+)/g;
        let pMatch;
        while ((pMatch = paramRegex.exec(cmdMatch[2])) !== null) {
            params[pMatch[1].toLowerCase()] = parseFloat(pMatch[2]);
        }
        const speed = params.speed ?? 0.5;
        const angular = params.angular ?? 0.0;
        const duration = params.duration ?? 0;
        let command = null;
        switch (name) {
            case "forward": case "move":
                command = { action: "move", linear: speed, angular: angular, duration: duration }; break;
            case "back": case "backward":
                command = { action: "move", linear: -speed, angular: angular, duration: duration }; break;
            case "left":
                command = { action: "move", linear: 0.0, angular: Math.abs(angular) || 1.0, duration: duration }; break;
            case "right":
                command = { action: "move", linear: 0.0, angular: -(Math.abs(angular) || 1.0), duration: duration }; break;
            case "stop": command = { action: "stop" }; break;
            case "stand": command = { action: "stand" }; break;
            case "dance": command = { action: "preset", name: "dance_with_beats" }; break;
            case "bow": command = { action: "preset", name: "bow" }; break;
            case "hello": case "wave": case "hello/wave": command = { action: "preset", name: "wave_hand" }; break;
            case "shake": command = { action: "preset", name: "shake_hand" }; break;
            case "clap": command = { action: "preset", name: "clap_hand" }; break;
            case "lion": command = { action: "preset", name: "lion_dance" }; break;
            case "jump": command = { action: "preset", name: "jump_forward" }; break;
            case "heart": command = { action: "preset", name: "draw_heart" }; break;
            case "bark": command = { action: "preset", name: "bark" }; break;
            case "nod": command = { action: "preset", name: "nod_head" }; break;
            case "wag": command = { action: "preset", name: "wag_tail" }; break;
            case "cute": command = { action: "preset", name: "cute" }; break;
            case "think": command = { action: "preset", name: "think" }; break;
            case "sleepy": command = { action: "preset", name: "be_sleepy" }; break;
        }
        if (command && socket && socket.readyState === WebSocket.OPEN) {
            const delay = cmdDelayMs;
            cmdDelayMs += duration > 0 ? (duration * 1000) + 500 : 400;
            setTimeout(() => {
                socket.send(JSON.stringify({ action: "voice_command", command }));
                if ((name === "forward" || name === "move" || name === "back" || name === "backward" || name === "left" || name === "right") && duration > 0) {
                    setTimeout(() => {
                        if (socket && socket.readyState === WebSocket.OPEN) {
                            socket.send(JSON.stringify({ action: "voice_command", command: { action: "stop" } }));
                        }
                    }, duration * 1000);
                }
            }, delay);
        }
    }
}

function handleAIFunctionCall(msg) {
    const { name, arguments: argsStr, item_id } = msg;
    let args = {};
    try { args = JSON.parse(argsStr); } catch (e) {}
    console.log("AI function call:", name, args);
    voiceStatusText = `🎤 ${name} ${JSON.stringify(args)}`;

    let command = null;
    switch (name) {
        case "move":
            command = { action: "move", linear: args.linear ?? 0.5, angular: args.angular ?? 0.0 };
            break;
        case "stop":
            command = { action: "stop" };
            break;
        case "stand":
            command = { action: "stand" };
            break;
        case "damping":
            command = { action: "damping" };
            break;
        case "play_preset":
            command = { action: "preset", name: args.name };
            break;
        case "noop":
            command = null;
            break;
    }

    if (command && socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ action: "voice_command", command }));

        if (name === "move" && args.duration > 0) {
            setTimeout(() => {
                if (socket && socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({ action: "voice_command", command: { action: "stop" } }));
                }
            }, args.duration * 1000);
        }
    }

    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            action: "realtime_function_result",
            call_id: item_id,
            output: JSON.stringify({ status: "ok" })
        }));
    }
}

async function handleAIMicStart() {
    if (!aiAgentReady) return;
    isRecording = true;
    voiceCommand = "";
    voiceStatusText = "🎤 Listening...";
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaStreamAI = stream;
        const win2 = (window);
        const audioCtx = new (win2.AudioContext || win2.webkitAudioContext)({ sampleRate: 24000 });
        audioContextAI = audioCtx;
        const source = audioCtx.createMediaStreamSource(stream);
        const processor = audioCtx.createScriptProcessor(4096, 1, 1);
        processor.onaudioprocess = (e) => {
            if (socket && socket.readyState === WebSocket.OPEN) {
                const float32 = e.inputBuffer.getChannelData(0);
                const int16 = new Int16Array(float32.length);
                for (let i = 0; i < float32.length; i++) {
                    const s = Math.max(-1, Math.min(1, float32[i]));
                    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                const bytes = new Uint8Array(int16.buffer);
                let binary = "";
                for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
                socket.send(JSON.stringify({ action: "realtime_audio", audio: btoa(binary) }));
            }
        };
        audioProcessorAI = processor;
        source.connect(processor);
        processor.connect(audioCtx.destination);
    } catch (err) {
        console.error("AI mic start error:", err);
        isRecording = false;
        voiceStatusText = `Mic error: ${(err).message}`;
    }
}

function handleAIMicEnd() {
    if (audioProcessorAI) { try { audioProcessorAI.disconnect(); } catch (e) {} }
    if (mediaStreamAI) { mediaStreamAI.getTracks().forEach(t => t.stop()); mediaStreamAI = null; }
    if (audioContextAI) { audioContextAI.close(); audioContextAI = null; }
    audioProcessorAI = null;
    isRecording = false;
    voiceStatusText = "AI Agent ready — tap to talk";
}

function handleSpaceDown(e) {
  if (!(e.target instanceof HTMLElement)) return;
  if (e.key === ' ' || e.code === 'Space') {
    if (!isMobile) {
      e.preventDefault();
      if (voiceMode === "ai-agent") {
        handleBigButtonPress();
      } else {
        handleMicStart();
      }
    }
  }
}

function handleSpaceUp(e) {
  if (e.key === ' ' || e.code === 'Space') {
    if (!isMobile) {
      e.preventDefault();
      if (voiceMode === "ai-agent") {
      } else if (isRecording) {
        handleMicEnd();
      }
    }
  }
}

onMount(() => {
  const handleKey = (e) => {
        if (!(e.target instanceof HTMLElement)) return;
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        
        const key = keyMap[e.key];
        if (key) {
            e.preventDefault();
            sendCommand(key, e.type === "keydown");
        }
    };

    window.addEventListener("keydown", handleKey);
    window.addEventListener("keyup", handleKey);
    
    window.addEventListener("keydown", handleSpaceDown);
    window.addEventListener("keyup", handleSpaceUp);
    
    speechRecognitionSupported = !!("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

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
        window.removeEventListener("keydown", handleSpaceDown);
        window.removeEventListener("keyup", handleSpaceUp);
        window.removeEventListener("resize", checkMobile);
        if (socket) { socket.close(); }
        if (aiAgentReady) disconnectAIAgent();
    };
});

const consoleText = $derived(
    connectionState === "disconnected" ? "CONSOLE STANDBY: LINK OFFLINE" :
    connectionState === "connecting" ? "ESTABLISHING SECURE UPLINK TO ROBOT DOG..." :
    connectionState === "failed" ? "CONNECTION FAILURE: LINK TIMEOUT / OFFLINE" :
    voiceMode === "ai-agent" && voiceStatusText ? voiceStatusText :
    voiceStatusText.startsWith("Matched:") ? `🎤 SENT: ${voiceStatusText.replace("Matched: ", "")}` :
    voiceStatusText.includes("Heard") ? "🎤 No word matched" :
    voiceStatusText.startsWith("No speech") ? "🎤 No word matched" :
    isRecording ? (voiceMode === "ai-agent" ? "🎤 AI listening..." : "🎤 LISTENING... SPEAK COMMAND") :
    voiceCommand ? `🎤 SENT: ${voiceCommand}` :
    activeKeys.w ? `● TRANSMITTING: SENDING FORWARD COMMAND${activeKeys.shift ? " (FAST)" : ""}` :
    activeKeys.a ? `● TRANSMITTING: SENDING LEFT TURN MESSAGE${activeKeys.shift ? " (FAST)" : ""}` :
    activeKeys.s ? `● TRANSMITTING: SENDING REVERSE COMMAND${activeKeys.shift ? " (FAST)" : ""}` :
    activeKeys.d ? `● TRANSMITTING: SENDING RIGHT TURN MESSAGE${activeKeys.shift ? " (FAST)" : ""}` :
    activeKeys.shift ? "● LINK STABLE: STANDING BY (FAST SPEED ACTIVE)" :
    "● LINK STABLE: STANDING BY FOR COMMAND"
);

const consoleClass = $derived(
    connectionState === "connecting" || connectionState === "failed" ? "offline" :
    connectionState === "connected" ? (
        voiceMode === "ai-agent" ? (
            aiAgentReady ? (
                isRecording ? "recording" :
                voiceStatusText ? "processing" : "idle"
            ) : aiAgentConnecting ? "processing" : "idle"
        ) :
        isRecording ? (
            voiceStatusText.startsWith("Matched:") ? "active-transmitting" :
            voiceStatusText.includes("Heard") ? "recording" :
            "listening"
        ) :
        voiceStatusText.startsWith("Matched:") ? "active-transmitting" :
        voiceStatusText.includes("Heard") ? "recording" :
        voiceCommand ? "active-transmitting" :
        activeKeys.w || activeKeys.a || activeKeys.s || activeKeys.d ? "active-transmitting" : "idle"
    ) :
    "idle"
);

const voiceBtnClass = $derived(
    voiceMode === "ai-agent" ? (
        isRecording ? "listening" : ""
    ) :
    isRecording ? (
        voiceStatusText.startsWith("Matched:") ? "matched" :
        voiceStatusText.includes("Heard") ? "no-match" :
        "listening"
    ) : ""
);

$effect(() => {
    if (chatPanelEl) {
        void aiResponses;
        void aiTranscript;
        const el = chatPanelEl;
        requestAnimationFrame(() => {
            el.scrollTop = el.scrollHeight;
        });
    }
});
</script>

<main class="app-layout">
  <div class="control-panel-wrapper">
  <div class="control-panel">
    <header class="panel-header">
      <h1>NaviControl v2.0</h1>
      <p>Robotics Tactical Interface</p>
    </header>

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

    <footer class="hud-console">
      <div class="console-text {consoleClass}">
        {consoleText}
      </div>
    </footer>

  <div class="voice-bar">
    <button
      class="voice-bar-btn"
      class:listening={voiceBtnClass === "listening"}
      class:no-match={voiceBtnClass === "no-match"}
      class:matched={voiceBtnClass === "matched"}
      class:connected={connectionState === "connected"}
      onpointerdown={handleBigButtonPress}
      onpointerleave={handleBigButtonRelease}
      disabled={connectionState !== "connected"}
    >
      <span class="voice-bar-icon">🎤</span>
      <span class="voice-bar-label">
        {#if voiceMode === "ai-agent" && !aiAgentReady && !aiAgentConnecting}
          CONNECT AI
        {:else if voiceMode === "ai-agent" && aiAgentConnecting}
          CONNECTING...
        {:else if isRecording && voiceMode === "ai-agent"}
          TAP TO STOP
        {:else if isRecording}
          LISTENING
        {:else if voiceMode === "ai-agent" && aiAgentReady}
          TAP TO TALK
        {:else}
          HOLD TO SPEAK
        {/if}
      </span>
    </button>
    {#if !speechRecognitionSupported}
      <span class="voice-bar-hint">Speech recognition not supported in this browser</span>
    {/if}
  </div>

  <div class="voice-mode-bar">
    <div class="voice-mode-toggle">
      <button
        class="mode-btn"
        class:active={voiceMode === "keywords"}
        onclick={() => { voiceMode = "keywords"; if (aiAgentReady) disconnectAIAgent(); }}
      >
        Keywords
      </button>
      <button
        class="mode-btn"
        class:active={voiceMode === "ai-agent"}
        onclick={() => { voiceMode = "ai-agent"; }}
      >
        AI Agent
      </button>
    </div>
  </div>
  </div>
</div>

  {#if voiceMode === "ai-agent"}
  <div class="chat-panel" bind:this={chatPanelEl}>
    {#if aiResponses.length > 0}
      <div class="ai-chat-box">
        {#each aiResponses as response}
          <div class="ai-chat-bubble">{response}</div>
        {/each}
        {#if aiTranscript}
          <div class="ai-chat-bubble ai-chat-streaming">{aiTranscript}</div>
        {/if}
      </div>
    {/if}
    {#if aiResponses.length === 0 && !aiTranscript}
      <div class="chat-placeholder">Navi's responses appear here</div>
    {/if}
  </div>
  {/if}
</main>
