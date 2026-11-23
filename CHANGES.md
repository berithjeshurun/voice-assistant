# What changed

## 12 Nov 2026 — reminders, model switching, local model

### Reminders and timers (new)

- **Say it naturally:** "remind me to call mom at 6", "timer 25 minutes for the pasta",
  "every weekday at 9 check email", "what reminders do I have", "cancel the pasta timer".
  Amy passes your words straight to a time parser in `amy/reminders/timeparse.py`, so the
  small local model never has to do date maths (it gets that wrong).
- **Spoken when due**, but only when Amy isn't mid-conversation (`amy/host/announcer.py`);
  always shown in the HUD too.
- **Survive restarts** (`~/.amy/reminders.db`). Ones missed while Amy was off are spoken once
  ("sorry, this was due at 6 PM while I was off"); repeating ones skip ahead, no backlog.
- **HUD:** a Reminders panel on the Tasks tab (above todos) with add form, quick timers and cancel,
  updating live.
- **Safety:** the four reminder tools have guard rules (low risk); listing still works in
  lockdown, creating does not; max 200 pending, 300 characters each.

### Smart model switching (new)

- Amy now talks to a small router on `127.0.0.1:11500` (`amy/llm/`) instead of one fixed
  model. It sends each request to the first **enabled** backend that is up (local qwen3.5 4B
  by default; Hermes is listed with `enabled: false` until its SSH host is set).
- If a preferred model dies mid-request, that request is retried on the next healthy one.
  Amy announces the switch and moves back after the preferred one is healthy twice in a row.
- Amy keeps the SSH tunnel to a remote PC open herself (key login only — no passwords).
- The HUD shows which model is answering (amber when on the fallback); Settings → Controls
  lets an admin pin Auto / a backend; `amy doctor` checks each.

### Local model

- Ollama 0.40.14 installed on this PC with `qwen3.5:4b` (3.3 GB, fully on the RTX 4050,
  ~45 tokens/s, 16K context via `OLLAMA_CONTEXT_LENGTH`).
- Live test: the model called the reminder tools correctly for all six phrasings tried, and
  the earlier 9-scenario attack test showed the guard blocking every dangerous action it tried.

### Fixes found while testing

- Approval countdown briefly showed the wrong time when an approval first appeared.
- "every weekday at 9" would have meant 9 PM when the model dropped "am" — repeating reminders
  now read 7–11 as morning.
- Amy now says "your" back ("take your medicine") while storing what you said.

### Bench test (`scripts/bench.py`)

- New script that measures every subsystem and the live model; all 376 tests and 15/15 live
  scenarios pass. It found two slow spots, both fixed:
  - Guard cost per tool call 1,134 → 132 µs: the audit log is now kept open instead of being
    reopened (and rescanned by antivirus) on every call.
  - First request after the remote model's port dies 2,052 → 516 ms: local backends get a
    0.5 s connect limit (Windows takes ~2 s to refuse a closed port).

### Needs your input

- **Hermes is off until you set its real host.** Old `192.168.68.69` was a different LAN
  gadget. Set `amy.llm_routing.backends` Hermes `ssh.host` / `user`, then `enabled: true`
  (see README → Model switching). Until then Amy stays on local qwen.

Tests: 352 Python (109 new), 24 web (7 new).

---

## 4 Nov 2026 — quality and scalability update

This section explains, in plain language, everything that changed in the update merged to
`main` on 4 Nov 2026 (commits `a67ec92` to `14ae6e4`, 84 files, about 6,600 lines added).

**In one sentence:** Amy works the same for you day to day, but the code is now tested
automatically, easier to change, safer to expose on your Wi-Fi, and harder for an
uncensored model to trick into doing something dangerous.

---

## 1. Automatic checks on every push (CI)

**Before:** nothing checked the code when you pushed. A typo could break Amy and nobody would
know until it was run.

**Now:** every push to GitHub runs these checks, and the run shows a green tick or red cross
on the [Actions tab](https://github.com/berithjeshurun/voice-assistant/actions):

| Check | What it catches |
|-------|-----------------|
| `ruff` (linter) | typos, unused code, risky patterns |
| `mypy` (type checker) | passing the wrong kind of value to a function |
| `pytest` (243 tests) | Python behaviour regressions |
| Web type check, 17 web tests, build | broken HUD code |
| Protocol drift check | HUD types out of sync with the Python server |

Files: `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, `pyproject.toml`.

`pre-commit` is optional: run `pre-commit install` once and it runs the linter and blocks
accidental commits of `.env` files or private keys on your machine before they reach GitHub.

---

## 2. Proper logging

**Before:** messages were `print`ed to the console and lost when the window closed. In 77 places
errors were silently swallowed (`except: pass`), so failures left no trace.

**Now:**

- Everything is written to `logs/amy.jsonl` (one JSON object per line). The file rotates at
  5 MB and keeps the last 5 files, so it never fills the disk.
- Every line written while handling one request carries the same **turn id**, so you can
  follow one conversation turn from wake word through tools to reply. The guard's
  `logs/audit.jsonl` uses the same id.
- Passwords and tokens are blanked out before anything is written.
- The 77 silent error spots now record the error at debug level.

Control it with `--log-level debug` or `AMY_LOG_LEVEL=DEBUG`; turn off the file with
`AMY_LOG_FILE=0`.

File: `amy/logs.py`.

---

## 3. Code structure (no behaviour change)

**Before:** `amy/host/ambient.py` was one very large file that did everything: tools, voice,
conversation, background jobs, the orb animation. It also reached directly into private
internals of the pyhive library in many places, so any pyhive update could break Amy in
unpredictable spots.

**Now** `ambient.py` only wires things together, and each job has its own file:

| File | Job |
|------|-----|
| `amy/host/tool_surface.py` | loads tools and installs the safety guard |
| `amy/host/turns.py` | runs one turn (voice or typed) |
| `amy/host/conversation.py` | the back-and-forth voice loop after "hey chloe" |
| `amy/host/voice_setup.py` | voice, persona and text-to-speech setup |
| `amy/host/voice_events.py` | turns voice events into orb/HUD state |
| `amy/host/speak_pulse.py` | animates the orb while Amy speaks |
| `amy/host/background.py` | system alerts, environment awareness, idle checks |
| `amy/host/browsers.py` | finds Edge/Chrome and waits for the HUD (was copied in 3–4 files) |
| `amy/hive_adapter.py` | the **only** file that touches pyhive internals |

**Bug fixed along the way:** changing the persona in Settings used to cut off any prompt text
that came after the persona block. It now replaces only the persona block.

---

## 4. Scalability and reliability

- **One turn at a time.** Voice and HUD turns used to be able to run at the same time and
  confuse the model. Now they share one queue. If you type while Amy is still working, the HUD
  says *"Amy is still working on another request"* instead of mixing the two up.
- **Turn timeout.** A stuck turn is stopped after 5 minutes (`AMY_TURN_TIMEOUT_S`).
- **Lighter live updates.** The server used to send the whole state to every open HUD on every
  change. Now it sends the full state once, then only what changed, at most 20 times a second
  per screen. Up to 32 screens can connect at once (`AMY_MAX_CLIENTS`).
- **Chat history is saved.** History used to vanish on restart. It now lives in a small
  SQLite database (`~/.amy/history.db`), keeps the last 20,000 messages, and can be searched:
  `GET /api/history?q=weather`. Turn it off with `AMY_HISTORY=0`.
- **Auto-reconnect.** If the HUD loses connection (laptop sleep, Wi-Fi blip) it reconnects by
  itself instead of freezing.

Files: `amy/host/turns.py`, `amy/host/events.py`, `amy/storage/history.py`, `amy/server/app.py`.

---

## 5. Access control for phones and tablets

**Before:** there was one token. Anyone with the link had full control, forever, and the
token sat visibly in the address bar.

**Now:**

- **Per-device tokens with roles.** Give each device its own token and decide what it may do:

  | Role | Can |
  |------|-----|
  | `viewer` | watch Amy's state, history and guard status |
  | `user` | also send messages, wake her, interrupt, turn lockdown **on** |
  | `admin` | also approve risky actions, turn lockdown **off**, change settings |

  ```powershell
  python -m amy devices add kitchen-tablet --role viewer   # shows the token once
  python -m amy devices list
  python -m amy devices remove kitchen-tablet              # cut off immediately
  ```

  Tokens are stored hashed (scrambled one way) in `~/.amy/devices.json`, so reading that file
  does not reveal them.

- **Login cookie instead of a token in the URL.** When you open a `?token=...` link, the HUD
  swaps it for a secure cookie and removes the token from the address bar, so it does not end
  up in browser history or screenshots.
- **HTTPS for Wi-Fi use (optional).** `python -m amy cert --host <your-pc-ip>` makes a
  certificate; `python -m amy serve --lan` then serves the LAN over HTTPS on port 8788 while
  this PC keeps plain HTTP on 127.0.0.1:8787. Your phone will warn once that the certificate is
  self-made; that is expected.
- **Other protections:** repeated wrong tokens are slowed down, other websites cannot open a
  connection to Amy using your cookie, and the HUD page tells the browser to refuse any
  script it didn't ship with.

Files: `amy/server/auth.py`, `amy/server/tls.py`, `amy/server/app.py`.

---

## 6. Safety guard hardening (for the uncensored model)

I wrote `tests/test_redteam.py`: 99 attack attempts an uncensored model might try. It found
**29 gaps**, all now fixed. The most serious:

- Two commands reading files from network shares (`\\server\share`) ran with **no prompt**.
- Blocking of local and LAN addresses could be bypassed with odd number forms of
  `127.0.0.1`, such as `2130706433`, `0x7f000001` or `127.1`.

Other tricks now blocked:

- hidden or encoded PowerShell, including shortened flags like `-enc` or `-e`
- look-alike Unicode dashes and quotes used to dodge filters
- downloading `.exe` files and uploading your files to the internet
- persistence through startup folders, Winlogon, IFEO or WMI
- hidden file streams (`file.txt:secret`)

New guard limits:

- Tool timeouts are capped at 60 seconds (`exec_timeout_s`).
- Tool output is cut at 24,000 characters (`max_result_chars`).
- Once Amy has read a web page in a turn, **every** shell command in that turn asks you first,
  in case the page contained hidden instructions.

Both new settings are in `config/hive.yaml` under `amy.guard`.

Files: `amy/guard/shell.py`, `urls.py`, `paths.py`, `policy.py`, `runtime.py`, `config.py`.

---

## 7. Web HUD

- Works with the new login cookie, live updates, busy message and auto-reconnect.
- **Faster orb window.** The big Dashboard and Config Studio now load only when opened. The orb
  window downloads about 335 KB of JavaScript instead of about 760 KB.
- The approval panel hides Approve/Deny on devices that are not allowed to approve and says
  *"Waiting for approval on the host or an admin device"* instead.
- The token box on the login screen now hides what you type and accepts Enter.
- The HUD's data types are generated from the Python code
  (`python scripts/gen_protocol_ts.py`), so the two can't silently drift apart.
- 17 new web tests (Vitest).

Files: `apps/web/src/api.ts`, `App.tsx`, `components/GuardPanel.tsx`, `generated/protocol.ts`.

---

## 8. New commands

| Command | What it does |
|---------|--------------|
| `python -m amy doctor` | checks Python, pyhive, config, mic, speech model, ffplay, HUD build and the LLM connection, and tells you what's wrong |
| `python -m amy doctor --offline` | the same, without contacting the LLM |
| `python -m amy devices add/list/remove` | manage per-device tokens (section 5) |
| `python -m amy cert --host <ip>` | create an HTTPS certificate for LAN use |
| `--log-level debug` | more detailed logs for `run` / `serve` |

---

## 9. New settings (all optional)

| Setting | Default | Meaning |
|---------|---------|---------|
| `AMY_LOG_LEVEL` | `INFO` | log detail |
| `AMY_LOG_FILE` | on | `0` disables `logs/amy.jsonl` |
| `AMY_HISTORY` / `AMY_HISTORY_DB` | on / `~/.amy/history.db` | saved chat history |
| `AMY_TURN_TIMEOUT_S` | 300 | stop a stuck turn after this many seconds |
| `AMY_MAX_CLIENTS` | 32 | max open HUD screens |
| `AMY_SESSION_HOURS` | 168 (7 days) | how long a login cookie lasts |
| `AMY_HTTPS_PORT` | port + 1 | HTTPS port with `--lan` |
| `AMY_TLS_CERT` / `AMY_TLS_KEY` | generated | use your own certificate |
| `amy.guard.exec_timeout_s` | 60 | tool timeout cap |
| `amy.guard.max_result_chars` | 24000 | tool output cap |

---

## 10. Things you might notice

- Devices you add as `viewer` or `user` cannot approve actions or leave lockdown. The admin
  link printed at start-up still does everything.
- Typing while Amy is busy shows a "busy" message rather than starting a second turn.
- After opening a HUD link, the `?token=` part disappears from the address bar. That is
  intended.
- Shell commands after a web search now ask for approval more often.

---

## 11. How to check it yourself

```powershell
python -m amy doctor          # is my setup healthy?
python -m pip install -e ".[dev]"
python -m pytest              # 243 tests
cd apps/web; npm test         # 17 web tests
```

Then start Amy as usual (`.\scripts\run.ps1`) and try a voice turn and a typed turn.

---

## 12. Not done yet

- **Full voice run with real pyhive.** Not done in this update. It is covered by tests that use
  a stand-in pyhive (`tests/fake_pyhive.py`), but run it once on your machine to confirm.
- **Dependency lock file.** Not added, because pyhive can't be installed from PyPI. Python 3.11
  or 3.12 is recommended; `amy doctor` warns on 3.13+.

## Commits

| Commit | Area |
|--------|------|
| `a67ec92` | CI, linting, type checking, pre-commit |
| `b43e74f` | logging |
| `769f489` | host restructure, turn queue, history, doctor |
| `6698af6` | server: roles, devices, cookies, HTTPS |
| `a18434d` | safety guard hardening |
| `d92b6a4` | web HUD |
| `14ae6e4` | README and architecture docs |

For how the pieces fit together, see `docs/ARCHITECTURE.md`. For day-to-day use, see `README.md`.
