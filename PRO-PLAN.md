# PRO-PLAN.md — Project AMY

> **A**utonomous **M**ulti-agent **Y**ielding assistant — a JARVIS/FRIDAY-class personal AI.

**Status:** Product host + LAN HUD. Phase 2 voice path shipped (measure/warmup/early-speak). LLM: **SSH Ollama** `hf.co/lmstudio-community/Hermes-4-70B-GGUF:Q4_K_M` (`model.endpoint.mode: ssh` → `192.168.68.69`). Current focus: **Phase 3 — The Hive**.
**Owner:** berithjeshurun
**Workspace:** `G:\Amy` · Libraries: `H:\New_VLibs\v4` · Runtime: `G:\HiveSTEAM`
**How to run:** `.\scripts\run.ps1` → `python -m amy serve` (`HIVE_CONFIG=G:\Amy\config\hive.yaml`). LAN: `-Lan` / `--lan`. Not `amy chat`. Section 4 Adopt = pip-editable from H:, never vendor. Brand: **Amy** (not Jarvis). Wake: **hey chloe**.

---

## 1. Vision & Principles

### 1.1 Vision
Amy is an always-available, voice-first, proactive assistant that knows you, controls your digital (and eventually physical) environment, and gets real work done by delegating to a swarm of specialized agents — the "hive."

### 1.2 What "JARVIS/FRIDAY level" means (concrete, testable)
| Capability | Definition of done |
|---|---|
| Natural voice conversation | < 1.2 s end-to-end latency to first spoken word; interruptible (barge-in) |
| Persistent memory | Recalls facts/preferences/events from weeks ago, with source |
| Tool use | Operates calendar, email, files, browser, terminal, smart home |
| Proactivity | Surfaces briefings, reminders, anomalies without being asked |
| Multi-step autonomy | Completes tasks of 10+ steps with checkpoints and rollback |
| Multi-agent delegation | Lead agent spawns specialists, merges results |
| Situational awareness | Knows screen context, time, location, active project |
| Trust & safety | Risky actions require confirmation; full audit log |

### 1.3 Design principles
1. **Voice-first, text-always** — every capability works through both.
2. **Local-first privacy** — sensitive data, wake word, STT and memory stay on-device by default; cloud LLM calls are explicit and minimized.
3. **Tools over prompts** — behavior comes from typed, testable tools, not giant prompts.
4. **Human-in-the-loop for irreversible actions** — send, delete, pay, deploy always confirm.
5. **Observable** — every decision, tool call and memory write is logged and replayable.
6. **Modular** — swap any brain/STT/TTS/memory component without rewriting the rest.
7. **Ship vertical slices** — each phase ends with something usable daily.

### 1.4 Non-goals (v1)
- No autonomous financial transactions.
- No multi-user household profiles (single owner first).
- No custom model training; use existing models + fine-tuned prompts/retrieval.

---

## 2. System Architecture

```
                    ┌──────────────────────────────────────────┐
                    │               INTERFACES                 │
                    │  Voice │ Desktop HUD │ CLI │ Mobile │ API│
                    └───────────────┬──────────────────────────┘
                                    │
┌─────────────┐   ┌─────────────────▼─────────────────┐   ┌──────────────┐
│ Wake word   │──▶│          AMY CORE (Queen)         │◀─▶│   MEMORY     │
│ VAD         │   │  Intent → Plan → Delegate → Merge │   │ working      │
│ STT         │   │  Persona, policy, safety gate     │   │ episodic     │
│ TTS         │   └───────┬───────────┬───────────────┘   │ semantic     │
└─────────────┘           │           │                   │ procedural   │
                          │           │                   └──────────────┘
              ┌───────────▼───┐   ┌───▼──────────────┐
              │  TOOL LAYER   │   │   THE HIVE       │
              │  (MCP servers)│   │  specialist      │
              │  calendar,    │   │  agents (workers)│
              │  email, fs,   │   │  research, code, │
              │  browser, home│   │  ops, writer ... │
              └───────────────┘   └──────────────────┘
                          │
                ┌─────────▼──────────┐
                │ Event bus + Scheduler │  ← proactive triggers, cron, webhooks
                └────────────────────┘
                ┌────────────────────┐
                │ Observability / Audit │
                └────────────────────┘
```

### 2.1 Core components

| # | Component | Responsibility |
|---|---|---|
| 1 | **Audio I/O** | Wake word, VAD, streaming STT, streaming TTS, barge-in |
| 2 | **Amy Core ("Queen")** | Orchestrator: parses intent, plans, delegates, enforces policy |
| 3 | **The Hive** | Pool of specialist worker agents with scoped tools and budgets |
| 4 | **Tool Layer** | MCP-based tools with typed schemas, permission levels |
| 5 | **Memory** | Short/long-term, vector + structured, with forgetting and provenance |
| 6 | **Event bus & scheduler** | Proactive triggers, background jobs, webhooks |
| 7 | **Context engine** | Collects screen, active app, location, time, recent activity |
| 8 | **Safety & policy** | Permission tiers, confirmation, sandboxing, audit |
| 9 | **UI / HUD** | Desktop overlay, transcript, task board, approvals |
| 10 | **Observability** | Traces, cost, latency, replay |

### 2.2 Recommended tech stack

| Layer | Primary choice | Alternatives |
|---|---|---|
| Language | Python 3.12 (core), TypeScript (UI) | Go/Rust for hot paths |
| LLM brain | Claude via API (tool use, long context) | Local: Llama/Qwen via Ollama for offline fallback |
| Wake word | openWakeWord / Porcupine | Custom-trained "Hey Amy" |
| VAD | Silero VAD | WebRTC VAD |
| STT | faster-whisper (local) | Deepgram / cloud streaming |
| TTS | Piper / Kokoro (local) | ElevenLabs / cloud for premium voice |
| Agent framework | Thin custom orchestrator + MCP | LangGraph, Claude Agent SDK |
| Tools | MCP servers | Native Python functions |
| Vector store | SQLite + sqlite-vec / LanceDB | Qdrant, Chroma |
| Structured store | SQLite (WAL) → Postgres later | — |
| Event bus | asyncio + Redis streams | NATS |
| Scheduler | APScheduler | Temporal (later) |
| Desktop UI | Tauri + React | Electron, Wails |
| Mobile | PWA first, native later | Flutter |
| Observability | OpenTelemetry + Langfuse/Phoenix | Custom JSONL logs |
| Packaging | Docker Compose (services), uv (Python) | Nix |
| CI | GitHub Actions | — |

### 2.3 Product layout (host + HUD — current)

```
G:\Amy\
├── amy\                      # product host (AmbientHost, AmyServer, protocol)
├── apps\
│   ├── web\                  # React HUD (phones + desktop)
│   ├── desktop\              # Tauri shell titled Amy
│   └── orb\                  # Bevy companion (presentation-only)
├── config\hive.yaml          # HIVE_CONFIG; profile ambient; wake hey amy
├── identity\AMY.md
├── prompts\ambient.md
├── docs\
└── scripts\                  # run/bootstrap/autostart (.ps1 + .sh)
```

Amy **owns** host + UI code. Hive packages stay on H: (import only). Central server: `run -Lan` → local link for phones/laptops.

---

## 3. Capability Roadmap by Domain

### 3.1 Voice & conversation
- Wake word → VAD → streaming STT → LLM stream → streaming TTS (pipelined sentence-by-sentence).
- Barge-in: user speech cancels TTS and in-flight generation.
- Persona: concise, dry wit, calm under pressure; configurable verbosity.
- Spoken-friendly output mode (no markdown, short sentences, numbers read naturally).
- Multilingual support (English first; Hindi/Telugu stretch).

### 3.2 Memory
| Layer | Contents | Store | Retention |
|---|---|---|---|
| Working | Current conversation, active task state | RAM | Session |
| Episodic | What happened, when, with whom | SQLite + embeddings | Months, decays |
| Semantic | Facts, preferences, relationships | Structured + vector | Long-term, editable |
| Procedural | Learned routines/"playbooks" | Versioned files | Until revoked |

Rules: every memory has `source`, `confidence`, `created_at`, `last_used`. User can say "forget that" and "what do you know about X". Nightly consolidation job summarizes, dedupes and expires.

### 3.3 Tool/skill surface (prioritized)
1. **Time & tasks:** calendar, reminders, todos, timers
2. **Comms:** email (read/draft/send-with-approval), messages
3. **Files & notes:** search, summarize, organize
4. **Web:** search, fetch, browser automation
5. **Dev ops:** git, terminal (sandboxed), CI status, deployments
6. **System control:** open apps, volume, window management, clipboard
7. **Smart home:** Home Assistant bridge
8. **Media:** music, podcasts
9. **Vision:** screen understanding, camera, OCR
10. **Finance (read-only):** summaries, alerts

**Amy Apps (packs):** installable ecosystem under `apps/packs/` with `SKILL.md` + tools + `~/.amy/secrets/`. First pack: **SmartPanels** (HTTP login + Playwright fallback). See [`docs/apps.md`](docs/apps.md).

### 3.4 Proactivity
- Morning briefing (calendar, weather, priority email, tasks).
- Context nudges ("Meeting in 10 min, you haven't opened the doc").
- Anomaly alerts (CI failing, unusual calendar conflicts).
- Habit learning → suggested routines, always opt-in.
- Interrupt budget: max N unsolicited interruptions/hour, respects focus mode.

### 3.5 Autonomy levels
| Level | Behavior | Example |
|---|---|---|
| L0 | Answer only | "What's on my calendar?" |
| L1 | Read-only tools | Search email, read files |
| L2 | Reversible writes | Create event, draft email |
| L3 | Irreversible with confirm | Send email, delete, deploy |
| L4 | Irreversible without confirm | **Disabled by default**; per-rule opt-in only |

---

## 4. Hive Integration (Repo Audit — COMPLETED 2026-10-24)

> Audited via `gh` + local arsenal `H:\New_VLibs\v4`. Amy **adopts** the arsenal as libraries (pip editable); does **not** vendor source into this monorepo.

### 4.1 Audit table

| Repo | Language | Purpose | Smoke\* | Reusable parts | Overlaps with Amy component | Decision |
|---|---|---|---|---|---|---|
| `hive-v4` | Python | Umbrella ambient Desktop Friday + companions | pass (import) | `pyhive` OS, profiles, ambient/voice/idle/UI, config | Queen runtime, Audio I/O, Tools, Observability | **Adopt** (canonical lib root) |
| `hivepersona` | Python | User biometrics + clearance | pass (import) | enroll/verify face/voice, dual clearance | Safety & policy, Audio I/O gates | **Adopt** |
| `hivescreen` | Python | Desktop capture + OCR | pass (import) | screen_shot/ocr/describe | Context engine, Eyes | **Adopt** |
| `hivesteam` | Python | Tools + VCE / forge adapters | pass (import) | tool arsenal, VCE STT/TTS | Tool layer, Audio I/O | **Adopt** |
| `hivedb` | Python | Durable memory stores | pass (import) | chunking, graph, injection | Memory | **Adopt** |
| `hiveworkers` | Python | Job / worker queue shapes | pass (import); **unpublished** (local `H:\…\hiveworkers` only) | plan_jobs, worker_* tools | Hive workers / event bus | **Adopt** (weakest dep) |
| `hivepulse` | Python | Idle + presence / psyche | pass (import) | IdleSupervisor, presence tools | Proactivity, Context | **Adopt** |
| `hivesense` | Python | Sense I/O shims | pass (import) | voice/wake/shell companions | Audio I/O | **Adopt** |
| `hivecraft` | Python | Coding / repair capabilities | pass (import) | coder/repair paths | Coder agent | **Adopt** |
| `hiveknow` | Python | Retrieval / wiki / research | pass (import) | research sessions, wiki | Scout, Memory semantic | **Adopt** |
| `hivetrace` | Python | Telemetry / evals / HCI | pass (import) | spans, eval hooks | Observability | **Adopt** |

\*Smoke = importable from Amy env as of 2026-10-25. Former “maturity 3–4” scores were provisional/unmeasured and are retired.

### 4.2 Decision rubric
- **Adopt** — install as **pip-editable libraries** from `H:\New_VLibs\v4` (or matching GitHub repos). **Never vendor** companion source into `G:\Amy`. Product host code lives in `G:\Amy\amy` + `apps/`; Hive OS packages remain on H:.
- **Refactor** — good ideas, needs interface cleanup to match message schemas in 5.2.
- **Reference** — borrow patterns only.
- **Archive** — superseded.

### 4.3 Mapping hive concepts to Amy (default assumptions)
| Hive concept | Amy role |
|---|---|
| Lead / coordinator agent | Amy Core (Queen) |
| Worker agents | Specialist agents in `hive/agents/` |
| Shared state / pads / blackboard | Task board + working memory |
| Task queue | Event bus + job queue |
| Agent profiles | `AgentSpec` (prompt, tools, budget, permissions) |
| Health/doctor commands | Observability + self-diagnostics |

### 4.4 Integration checklist
- [x] Inventory all hive repos (stars, last commit, language, license)
- [x] Identify duplicate functionality across repos (companions are complementary; `hive-v4` is umbrella)
- [x] Pick one canonical orchestration repo → `hive-v4` / `pyhive` at `H:\New_VLibs\v4`
- [x] Define adapter interface for AgentSpec (prior Phase 0 scaffolding; wiped with chat harness — reintroduce when Hive product layer returns)
- [x] Migrate or archive each repo with a recorded decision → all **Adopt** as libraries; none vendored into `G:\Amy`

---

## 5. The Hive: Multi-Agent Design

### 5.1 Roles

| Agent | Purpose | Tools | Permission ceiling |
|---|---|---|---|
| **Amy (Queen)** | Talk to user, plan, delegate, approve | all (via delegation) | L3 |
| **Scout** | Web/doc research with citations | search, fetch | L1 |
| **Scribe** | Writing, summaries, email drafts | notes, mail-draft | L2 |
| **Coder** | Code changes in sandbox, tests | git, shell (sandbox) | L2 |
| **Ops** | Calendar, tasks, reminders, system | calendar, todo, OS | L2 |
| **Home** | Smart-home control | Home Assistant | L2 |
| **Archivist** | Memory read/write/consolidate | memory API | L2 |
| **Sentinel** | Policy checks, red-team of risky plans | policy engine | L1 (veto power) |
| **Eyes** | Screen/camera understanding | vision | L1 |

### 5.2 Message schemas (v1)

```jsonc
// Task
{
  "task_id": "uuid",
  "parent_id": "uuid|null",
  "goal": "string",
  "context_refs": ["memory:123", "file:/..."],
  "constraints": { "deadline": "iso8601", "budget_usd": 0.50, "max_steps": 20 },
  "permission_level": "L1",
  "return_format": "summary|structured|artifact"
}

// Result
{
  "task_id": "uuid",
  "status": "ok|partial|failed|needs_approval",
  "output": "...",
  "artifacts": [],
  "evidence": [{"type":"url|tool_call","ref":"..."}],
  "cost": {"tokens": 0, "usd": 0.0, "ms": 0},
  "followups": []
}
```

### 5.3 Orchestration loop
1. Receive input (voice/text/event).
2. Classify: chat / quick tool / complex task / background job.
3. **Quick path** (<2 tool calls): Amy handles directly.
4. **Complex path:** plan → decompose → assign to workers (parallel where independent).
5. Sentinel reviews plan for risk; approvals gathered via voice or HUD.
6. Workers execute with budgets; progress streamed to task board.
7. Amy merges, verifies against the goal, reports in spoken-friendly form.
8. Archivist stores outcome and lessons.

### 5.4 Failure handling
- Timeouts, retries with backoff, circuit breakers per tool.
- Worker returns `partial` with what it got; Amy decides to retry, reroute or ask the user.
- Every plan has a rollback note for L2+ actions.
- Hard stop phrase: **"Amy, stop."** cancels everything immediately.

---

## 6. Safety, Privacy & Security

### 6.1 Threat model
| Threat | Mitigation |
|---|---|
| Prompt injection via web/email content | Treat tool outputs as untrusted data; strip instructions; Sentinel check before acting on externally-sourced text |
| Over-permissioned tools | Least privilege per agent; scoped OAuth tokens |
| Secret leakage | Secrets in OS keychain/vault, never in prompts or logs |
| Runaway cost/loops | Per-task token + USD + step budgets; global daily cap |
| Unintended destructive actions | Confirmation tiers (L3), dry-run mode, undo journal |
| Always-on mic abuse | Local wake word; hardware mute; visual/audio listening indicator |
| Data exfiltration | Egress allowlist for sandboxed tools |

### 6.2 Privacy
- Raw audio never persisted by default; transcripts only (configurable).
- Clear data inventory + one-command export and wipe.
- Cloud calls log what was sent; PII redaction option.

### 6.3 Auditability
Append-only audit log: who/what/when/inputs/outputs/approval for every tool call at L2+.

---

## 7. Phased Delivery Plan

### Phase 0 — Foundations — DISCARDED as product surface (2026-10-25)
Chat-as-exit harness (`amy chat`, chatbot scaffolds, STATUS theater) was wiped. Audit + Adopt decisions in §4 still stand. Re-seeded `config/hive.yaml` + thin voice host.

### Phase 1 — Text Brain + Tools
Deferred as product entry. Tools still available under ambient when needed. No chat REPL product.

### Phase 2 — Voice (HANDOFF → dogfood on local `deepseek-r1:8b`)
- [x] Product entry: `scripts\run.ps1` → `python -m amy serve` (`hey amy` wake; assistant name Amy)
- [x] Amy Python host imports PyHive AmbientHost APIs
- [x] LAN AmyServer + React HUD for phones/laptops
- [x] Tauri desktop shell + Bevy orb scaffolds
- [x] Warm session assemble-once + LLM/Piper warmup on `AmbientHost.start`
- [x] Barge-in (TTS); sentence-chunk TTS; LLM→first-sentence early-speak hook (ambient)
- [x] Spoken-output style layer; TTFW measured (`latency ttfw_ms=…` + `scripts/_smoke_latency.py`)
- [x] Local Ollama endpoint + `deepseek-r1:8b` (was SSH nemotron 120B)
- [ ] Ambient dogfood: chase measured TTFW toward &lt;1.2 s on local 8B
- [ ] Custom ONNX wake model tuned for "hey chloe" / product wake phrase

**Exit:** Hands-free conversation under 1.2 s to first word on target hardware.

### Phase 3 — The Hive (CURRENT)
- [x] Agent registry kickoff: `amy/hive` AgentSpec + Scout/Ops + Queen `hive_delegate`
- [x] Scribe + Archivist AgentSpecs; task board on EventBus (`tasks` in snapshot)
- [x] HUD task pills + cancel (`POST /api/hive/cancel`, WS `hive_cancel`)
- [ ] Worker runtime / parallel plan fan-out on ambient (`workers: true` when ready)
- [ ] Coder (sandboxed) agent
- [ ] Sentinel policy agent with veto
- [ ] Richer task board UI (budgets visible end-to-end on voice turns)
- [ ] Integrate/adopt chosen hive repos (procedure workers)

**Exit:** "Research X, draft a summary, and schedule time to review it" runs end-to-end with one voice command.

### Phase 4 — HUD & Context Awareness (IN PROGRESS)
- [x] Tauri + React HUD scaffold (title Amy); Bevy orb sidecar scaffold
- [x] Shared web HUD served by AmyServer (LAN token link)
- [ ] Polish approvals / memory browser / task board in HUD
- [ ] Context engine: active window, clipboard (opt-in), screen capture on demand
- [ ] Eyes agent (screen Q&A, OCR)

**Exit:** "What's wrong with this error?" works on whatever is on screen.

### Phase 5 — Proactivity (Week 16–18)
- [ ] Event bus, scheduler, webhooks
- [ ] Morning/evening briefings, nudges, focus mode, interrupt budget
- [ ] Routine learning (suggest, never silently adopt)

**Exit:** Useful unprompted help ≥ 3×/day with < 1 annoyance/day (tracked).

### Phase 6 — Smart Home & Devices (Week 19–21)
- [ ] Home Assistant integration
- [ ] Multi-room audio endpoints / mobile PWA
- [ ] Presence-aware behavior

### Phase 7 — Hardening & Polish (Week 22–24)
- [ ] Red-team prompt-injection suite
- [ ] Offline fallback (local LLM + local STT/TTS)
- [ ] Backup/restore, wipe, export
- [ ] Voice persona tuning, custom voice
- [ ] Documentation + onboarding

### Phase 8 — Stretch
- Multilingual voice, camera/vision presence, wearable/phone companion, plugin marketplace, learned preference models.

---

## 8. Testing & Evaluation

| Type | What | Tooling |
|---|---|---|
| Unit | Tools, schema validation, memory ops | pytest |
| Contract | Agent ↔ Queen messages | schema tests |
| Scenario evals | Scripted multi-turn tasks with graded outcomes | `evals/` + LLM judge + assertions |
| Latency | Per-stage and end-to-end voice timing | trace spans |
| Safety | Prompt injection, permission escalation, loop/cost caps | red-team suite |
| Regression | Re-run all evals on every prompt/model change | CI gate |
| Dogfooding | Daily use log + weekly review | personal journal |

**Key metrics:** task success rate, approvals-per-task, time-to-first-word, cost/day, hallucinated-tool-call rate, memory recall precision, unwanted-interruption count.

---

## 9. Budget & Hardware

| Item | Recommendation |
|---|---|
| Dev machine | 16 GB RAM min; GPU (8 GB+ VRAM) optional for local STT/LLM |
| Mic | Decent USB/array mic; speaker for testing |
| Cloud LLM | Set daily cap (e.g., $3–5/day during dev) |
| Always-on host | Mini-PC / home server for scheduler + Home Assistant |

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Scope creep ("do everything") | High | High | Vertical slices; each phase must ship |
| Voice latency too high | Med | High | Pipelining, local STT, small TTS, measure from Phase 2 |
| Multi-agent chaos/cost blowup | Med | High | Budgets, step caps, Sentinel, trace everything |
| Prompt injection | Med | High | Untrusted-data handling, confirmations, red-team |
| Fragmented legacy hive repos | High | Med | Audit → one canonical core, adapters for the rest |
| Memory pollution/wrong recall | Med | Med | Provenance, confidence, user-editable memory |
| Burnout on solo build | Med | High | Small weekly milestones, dogfood early |

---

## 11. Immediate Next Actions (This Week)

1. [x] Wipe chat/HUD scaffolds; re-seed Amy-branded ambient config.
2. [x] Thin voice host: `scripts\bootstrap.ps1` + `scripts\run.ps1`.
3. [x] Verify `run.ps1` reaches `ambient_listening` (`logs/verify_ambient.txt`).
4. [x] Instrument TTFW + ambient latency profile (`ack_timeout_ms: 400`, `think: false`) + early-speak.
5. [x] Switch LLM to **local** Ollama **`deepseek-r1:8b`** (`model.endpoint.mode: local`).
6. [x] Phase 3 kickoff: Amy `AgentSpec` registry + Scout/Ops + `hive_delegate` (`amy/hive`).
7. [x] Task board → HUD + cancel API; Scribe + Archivist registered.
8. [ ] Dogfood: local `deepseek-r1:8b` voice + `hive_delegate` (“have Scout research X”).
9. [ ] Coder specialist + optional ambient `workers: true` for plan fan-out.

---

## Appendix A — Repo Audit Script

**Status:** audit **complete** (2026-10-24). Results live in Section 4 (HIVE_AUDIT.md was wiped with the chat harness; §4.1 is canonical). Re-run only when inventory may have changed:

```bash
gh repo list berithjeshurun --limit 200 --json name,description,primaryLanguage,updatedAt,stargazerCount,isArchived,url \
  --jq '.[] | select(.name | test("hive"; "i")) | [.name, (.primaryLanguage.name // "-"), .updatedAt[0:10], .description // "-", .url] | @tsv'
```

Do not treat a fresh dump as “Section 4 incomplete” — update §4.1 / HIVE_AUDIT.md if new repos appear.

## Appendix B — Example Amy Interaction (Target Behavior)

> **You:** "Hey Amy, I need to prep for Thursday's client call."
> **Amy:** "On it. Pulling the thread history and last quarter's notes. Give me a moment." *(spawns Scout + Archivist)*
> **Amy:** "Three open issues from their last email, and they asked about pricing twice. I've drafted a one-page brief and blocked 45 minutes tomorrow at 10. Want me to send you the brief now?"
> **You:** "Yes, and move my 10 AM."
> **Amy:** "Moving the 10 AM standup to 11 requires notifying four people. Confirm?"

## Appendix C — Glossary
- **Queen/Core:** top-level orchestrator and the only agent that speaks to the user.
- **Hive:** the pool of specialist worker agents.
- **MCP:** Model Context Protocol, the standard for exposing tools to LLMs.
- **Barge-in:** user interrupts while Amy is speaking.
- **Sentinel:** policy agent that can veto risky plans.