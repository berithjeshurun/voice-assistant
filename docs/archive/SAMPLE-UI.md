> **Amy note:** This file is a **reference design** for the desktop HUD/orb.
> Product name is **Amy** (never Jarvis in UI). Intelligence runs in the
> Python Amy host + PyHive libraries — not a Rust agent core. Tauri + Bevy
> are clients of Amy’s HTTP/WebSocket protocol.

## My recommended stack for a cinematic companion HUD

🚀 Building "LISA" — My Personal Jarvis on Linux - DEV Community

TiTi - Hệ thống AI cá nhân hóa của riêng bạn

aiworldservice | Elite IT Services, Software Engineering & AI Automation - aiworldservice | Elite IT Services & Software Engineering

I'd build it as a persistent AI desktop companion with a reactive 3D HUD, voice interaction, an animated assistant presence, and a separate agent backend.

## Recommended architecture

3D interface

Tauri + React + CSS 3D + WebGL/Three.js

Rust agent core

Tokio · async tasks · tools · memory · permissions

Voice

Wake word, STT, TTS

OS integration

Apps, files, system actions

### Libraries I'd actually use

| Component | Library | Purpose |
| --- | --- | --- |
| Desktop shell | Tauri | Native desktop app |
| 3D parallax | Three.js | 3D objects, particles, depth |
| UI | React | HUD, chat, panels |
| Rust async runtime | Tokio | Background tasks and streaming |
| Voice | sherpa-onnx | Local speech processing |
| Native 3D alternative | Bevy | Entire interface rendered in a 3D engine |

Useful links: [Tauri](<https://tauri.app/?utm_source=chatgpt.com>) · [Three.js](<https://threejs.org/?utm_source=chatgpt.com>) · [Tokio](<https://tokio.rs/?utm_source=chatgpt.com>) · [sherpa-onnx](<https://github.com/k2-fsa/sherpa-onnx?utm_source=chatgpt.com>) · [Bevy](<https://bevy.org/?utm_source=chatgpt.com>).

For an interface that feels like a cinematic AI companion, I'd start with Tauri + React + Three.js and Rust for the intelligence and system integration. You can build the visual experience faster than writing a complete GPU UI renderer from scratch.

Choose Bevy instead if the entire screen should behave like a 3D world, with actual spatial panels and a camera moving through them.

One important distinction: the visual layer makes it feel like Jarvis or Friday; voice, reasoning, memory, tool execution, and safe OS access are what make it function like a real assistant.


Yes\! You can combine Bevy + Tauri, and for your Jarvis/Friday-style AI companion, it's a genuinely interesting architecture. You can use Bevy for the real-time 3D holographic experience and Tauri for the desktop shell, conventional UI, and native integration.

The key is to give each engine a distinct job rather than rendering the same interface twice.

## Recommended architecture

## Tauri desktop shell

Window management · Tray · Shortcuts · Permissions

IPC / local messaging

### Bevy

3D orb, particles, shaders, spatial panels, animation

### Web UI

Chat, settings, history, dashboards, forms

### Rust AI core

LLM integration · Voice · Memory · Tools · Automation

## How I'd divide the work

| Component | Responsibility |
| --- | --- |
| Bevy | Animated AI avatar, 3D HUD, mouse parallax, particle effects, reactive visualizations |
| Tauri | Desktop windows, system tray, global shortcuts, OS integration |
| React + CSS | Chat interface, settings, notifications, history |
| Rust backend | AI orchestration, speech pipeline, memory, tool execution |

Official projects: [Bevy](<https://bevy.org/?utm_source=chatgpt.com>) · [Tauri](<https://tauri.app/?utm_source=chatgpt.com>).

## Three ways to combine them

🔧 Teaching LLMs to Learn by Themselves: Inside MIT’s Self-Adapting Language Models (SEAL) | by Ranjanunicode | Medium

1. Bevy as a separate transparent window

Run Bevy in its own native window, positioned over or beside the Tauri interface. Use Tauri for controls and Bevy for the 3D avatar.

Best starting pointEasier to develop and debug independently, though transparent windows, click-through behavior, and window positioning need platform-specific testing.

AI Personal Assistant for Work: Save 10+ Hours (2026) | Arahi AI

2. Bevy embedded inside the Tauri interface

Put the 3D view inside a designated area of the application and render the rest of the interface with web technologies.

This can deliver a seamless experience, but embedding a Bevy renderer into a webview is considerably more complicated than opening two windows.

Abstract hi-tech HUD sci-fi display interface frame digital technology element on black background.

3. Bevy renders the entire visual interface

Use Tauri mainly for desktop lifecycle and native integration, with Bevy handling almost all visible graphics.

Ideal if you want a fully spatial, game-like interface rather than a conventional desktop app.

## What about memory consumption?

Combining them introduces additional overhead because you may have both a webview and a GPU renderer running.

- Tauri + Bevy together: budget for both processes or subsystems, including their graphics resources.
- Idle mode: pause or throttle rendering, unload unnecessary assets, and keep the AI backend idle when possible.
- AI inference: account for model memory separately; a local LLM can dwarf the UI's memory requirements.

I wouldn't promise a particular RAM figure until you've built a minimal prototype and measured it on your target OS.

## My recommendation

For a high-end desktop AI companion, I'd choose Tauri + Bevy + a shared Rust AI core, initially running Bevy in a separate window. Build the orb and visualizer first, then connect them to voice activity, assistant states, and AI responses.

# Jarvis/Friday desktop companion: implementation blueprint

My recommendation is a hybrid architecture with Tauri as the application shell, Bevy as a dedicated 3D rendering process, and one shared Rust application core for AI and automation.

The important architectural decision is to avoid embedding Bevy directly inside the Tauri webview at first. Tauri is built around native desktop windows and webviews, while Bevy manages its own rendering and window lifecycle. Keeping them separate makes the first version easier to develop and debug.

Tauri

+1

## 1. Window strategy

Sphere - AI Voice Assistant by AmazingUI on Dribbble

Window A — Companion orb

Always available- Small, borderless Bevy window.
- Transparent background where the OS compositor supports it.
- Idle animation, voice activity rings, particles and subtle mouse parallax.
- Clicking the orb opens the full HUD.
- Reduced frame rate or paused animation while idle.

Hermes Jarvis — your talking AI butler

Window B — Full assistant HUD

Tauri + React

- Chat and streaming responses.
- Memory browser and conversation history.
- Tool execution approvals and activity timeline.
- Voice controls, settings and system status.
- Optional Bevy visualizer window or a Three.js scene within the HUD.

Cross-platform caveat: transparent, always-on-top, click-through windows and taskbar behavior differ across Windows, macOS and Linux. Bevy exposes transparency configuration, but its documentation specifically notes platform limitations, including macOS caveats. Build a fallback opaque orb window and test the target desktop environments early.

Rust

+2

## 2. Recommended Rust crates

Use a workspace so your assistant logic is independent of either UI.

| Crate | Role |
| --- | --- |
| `bevy` | 3D renderer, ECS, animation, camera, particles |
| `tauri` | Desktop shell, windows, native commands |
| `tokio` | Async tasks, concurrency, network operations |
| `serde` + `serde_json` | Typed messages and serialization |
| `tracing` + `tracing-subscriber` | Structured logs and diagnostics |
| `reqwest` | HTTP requests to model providers |
| `sqlx` + `sqlite` | Persistent conversations and metadata |
| `keyring` | Secure storage for API credentials |
| `cpal` | Audio capture and playback building blocks |
| `sherpa-onnx` | Local speech recognition and speech processing |
| `uuid` | Request and conversation identifiers |

Useful references: [Bevy docs](<https://docs.rs/bevy/latest/bevy/?utm_source=chatgpt.com>) · [Tauri v2 docs](<https://v2.tauri.app/?utm_source=chatgpt.com>) · [Tokio docs](<https://docs.rs/tokio/latest/tokio/?utm_source=chatgpt.com>) · [SQLx docs](<https://docs.rs/sqlx/latest/sqlx/?utm_source=chatgpt.com>) · [sherpa-onnx](<https://github.com/k2-fsa/sherpa-onnx?utm_source=chatgpt.com>).

Keep the dependencies modular. You don't need to implement every subsystem immediately, and a cloud speech or LLM provider can replace the corresponding local engine without changing the UI protocol.

## 3. Workspace layout

I'd structure the repository like this:

text

```
jarvis/
├── Cargo.toml
├── crates/
│   ├── assistant-core/      # AI orchestration and state machine
│   ├── assistant-protocol/  # Shared message types
│   ├── assistant-memory/    # SQLite, history, preferences
│   ├── assistant-voice/     # Audio, STT, TTS, wake word
│   └── assistant-tools/     # OS actions and permissions
├── apps/
│   ├── desktop/             # Tauri + React HUD
│   │   ├── src/
│   │   └── src-tauri/
│   └── companion-renderer/  # Bevy orb and 3D effects
└── assets/
    ├── shaders/
    ├── audio/
    └── models/
```

The `assistant-protocol` crate is particularly important: both the Bevy renderer and Tauri backend use the same message definitions, so you don't end up maintaining two different representations of assistant state.

## 4. Inter-process communication

Use two communication paths, depending on the message.

Tauri frontend

Chat, controls, approvals

Tauri commands and events

Shared Rust application core

State, model requests, voice, tools

Local IPC transport

Bevy renderer

Receives visual state and emits interactions

### Which transport should you use?

- Tauri commands: request-response operations, such as starting a conversation or opening the settings window.
- Tauri events or channels: assistant state updates and streaming output to the web frontend. Tauri documents commands as request-response IPC and events as fire-and-forget notifications.
  GitHub
  +1
- Tokio `mpsc` channels: communication between Rust tasks inside the application core.
- Local socket or WebSocket: communication between the separate Bevy process and the Rust core.

For the Bevy process, I'd start with a local WebSocket using `tokio` and `tokio-tungstenite`, bound only to loopback and authenticated with a random per-launch token. A Unix domain socket or named pipe is also worth considering later. Don't expose an unauthenticated control server on the network.

### Define a small, versioned protocol

For example, the shared protocol could contain these messages:

rust

```
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AssistantSnapshot {
    pub protocol_version: u16,
    pub state: AssistantState,
    pub audio_level: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AssistantState {
    Idle,
    Listening,
    Thinking,
    Speaking,
    NeedsApproval,
    Error,
}
```

This is a starting point for the shared types, not a complete networking implementation.

The core publishes snapshots to the renderer. The renderer turns `Listening` into reactive rings, `Thinking` into a pulsing orb, `Speaking` into audio-reactive effects, and `NeedsApproval` into a distinct warning animation.

Keep the renderer presentation-only. It should not independently execute shell commands, access arbitrary files, or hold model API credentials.

## 5. Launching Bevy from Tauri

For the first version, package the Bevy renderer as a Tauri sidecar executable. Tauri supports bundling and launching external binaries, including platform-specific builds.

Tauri

I'd use newline-delimited JSON over the sidecar's standard input/output initially:

- Tauri starts the Bevy process.
- Tauri sends commands to Bevy over stdin.
- Bevy emits interaction events and renderer status over stdout.
- Tauri forwards relevant events to React.
- The shared Rust core owns assistant state and coordinates everything.

This avoids opening a network port just for communication between two processes. Reserve sockets for a later architecture if you need multiple independent clients or more complex streaming.

Example messages:

json

```
{"type":"set_state","state":"listening"}
{"type":"set_state","state":"thinking"}
{"type":"set_state","state":"speaking"}
{"type":"open_hud"}
{"type":"renderer_ready"}
```

Treat each line as an independent message, validate the message type, and handle process crashes and restarts. Never use renderer messages as authorization to perform privileged operations.

## 6. Make the orb feel intelligent

Design the visualizer around a small state machine instead of ad hoc animation triggers.

Minimal cyan translucent sphere on a dark background with soft inner glow, suited to modern tech, AI and innovation branding.

Idle

Slow breathing animation, subtle particles, low rendering activity.

Cyan energy core with concentric neon rings and fine blue mesh waves on black. Abstract futuristic background with luminous circular patterns and flowing lines.

Listening

Reactive rings, microphone level visualization and gentle pulse.

Sphere of particles in cyberspace. Impulse dynamic flow of global energy energy.

Thinking

Orbiting particles, animated shader noise and changing light intensity.

AudioX - Seedance 1.0 Audio Generator for AI Videos

Speaking

Audio-reactive deformation and synchronized visual feedback.

Implement the visuals with Bevy materials, meshes, shader effects and particle systems. Start with a single orb, a camera and a few particle layers before building a full holographic environment.

For performance, target a lower frame rate while idle and increase it during interaction. Use profiling to decide whether the renderer should stop rendering entirely when hidden.

## 7. Practical implementation plan

1. Phase 1 — Establish the desktop shell
   Create a Tauri v2 app with a React frontend. Add a system tray, show/hide behavior, a normal application window and a minimal Rust backend.
   Deliverable: a working cross-platform desktop shell.
2. Phase 2 — Build the Bevy orb
   Create a separate Bevy executable with a 3D sphere, animated shader, particles, transparent-window experiment and basic mouse interaction.
   Deliverable: a standalone animated orb that works on your target operating systems.
3. Phase 3 — Connect both processes
   Bundle Bevy as a sidecar. Implement versioned JSON messages over stdin/stdout, startup handshaking, error handling and automatic restart.
   Deliverable: the Tauri shell can control the orb's visual state.
4. Phase 4 — Add the shared assistant core
   Implement asynchronous model requests, conversation state, cancellation, streaming, persistent history and tool permissions.
   Deliverable: a functional text-based assistant whose state drives the orb.
5. Phase 5 — Add voice
   Integrate microphone capture, speech recognition, wake-word detection if needed, and text-to-speech. Connect audio activity and voice state to the renderer.
   Deliverable: hands-free interaction with visual feedback.
6. Phase 6 — Build the full HUD
   Add chat, memory search, tool approval dialogs, settings, system status and conversation history. Add a larger Bevy visualization only where actual 3D improves the experience.
   Deliverable: a polished companion with a compact orb and a full assistant workspace.
7. Phase 7 — Optimize and package
   Test startup, shutdown, idle CPU usage, RAM, GPU utilization, audio-device changes, window positioning and crash recovery on each supported OS.
   Deliverable: platform-specific release builds and measured resource usage.

## 8. Three design decisions I'd make early

- One source of truth: the Rust assistant core owns conversation state, voice state, memory and tool permissions. Both UIs are clients of that state.
- No privileged actions from the renderer: the orb can request an action, but the core validates it and obtains approval when appropriate.
- Graceful degradation: if Bevy crashes, the assistant and chat should continue working. If transparency fails on a particular desktop environment, show the orb in a normal borderless window.

## 9. Your first milestone

Don't build the entire AI system immediately. First prove this complete loop:

1. Launch the Tauri application.
2. Launch the Bevy orb as a sidecar.
3. Click a button in the HUD to set the assistant state to `Thinking`.
4. Watch the orb change animation.
5. Set the state back to `Idle`.
6. Close the application and verify that both processes exit cleanly.

Once this works on Windows, Linux and macOS, you've validated the hardest architectural boundary.

Final recommendation: use Tauri v2 + React for the desktop application, Bevy for the separate 3D orb, and a shared Rust core for intelligence and automation. Start with sidecar stdin/stdout IPC; introduce a socket only if your needs grow. This provides a practical path to the Jarvis/Friday experience without forcing every UI element into a 3D engine.