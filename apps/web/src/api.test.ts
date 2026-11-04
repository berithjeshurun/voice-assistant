import { describe, expect, it, vi } from "vitest";
import {
  ApiError,
  BUSY_MESSAGE,
  api,
  authKey,
  endSession,
  establishSession,
  getToken,
  reconnectDelay,
  reduceSocketMessage,
  Snapshot,
  turnErrorMessage,
} from "./api";
import { PROTOCOL_VERSION } from "./generated/protocol";

function snap(over: Partial<Snapshot> = {}): Snapshot {
  return {
    protocol_version: PROTOCOL_VERSION,
    name: "Amy",
    state: "idle",
    audio_level: 0,
    last_user: "",
    last_assistant: "",
    detail: "",
    caption: "",
    caption_role: "",
    cards: [],
    activity: [],
    tools: [],
    tasks: [],
    approvals: [],
    guard: { enabled: true, mode: "standard", lockdown: false },
    ...over,
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("reduceSocketMessage", () => {
  it("takes the initial snapshot and the role", () => {
    const ev = reduceSocketMessage(null, { type: "snapshot", data: snap(), role: "user" });
    expect(ev).toEqual({ kind: "snapshot", snapshot: snap(), role: "user" });
  });

  it("merges a patch over the current snapshot without touching other keys", () => {
    const base = snap({ caption: "hello", tools: ["web_search"] });
    const ev = reduceSocketMessage(base, { type: "patch", data: { state: "thinking" } });
    expect(ev.kind).toBe("snapshot");
    if (ev.kind !== "snapshot") return;
    expect(ev.snapshot.state).toBe("thinking");
    expect(ev.snapshot.caption).toBe("hello");
    expect(ev.snapshot.tools).toEqual(["web_search"]);
    expect(base.state).toBe("idle");
  });

  it("ignores a patch that arrives before any snapshot", () => {
    expect(reduceSocketMessage(null, { type: "patch", data: { state: "idle" } }).kind).toBe(
      "ignore",
    );
  });

  it("surfaces turn results and errors", () => {
    expect(reduceSocketMessage(null, { type: "turn_result", ok: false, error: "busy" })).toEqual({
      kind: "turn_result",
      result: { ok: false, reply: "", error: "busy" },
    });
    expect(
      reduceSocketMessage(null, { type: "error", error: "requires admin role", command: "approve" }),
    ).toEqual({ kind: "error", error: "requires admin role", command: "approve" });
  });

  it("accepts bare snapshots from older hosts and ignores junk", () => {
    expect(reduceSocketMessage(null, snap({ state: "speaking" })).kind).toBe("snapshot");
    expect(reduceSocketMessage(null, "nope").kind).toBe("ignore");
    expect(reduceSocketMessage(null, { type: "mystery" }).kind).toBe("ignore");
  });
});

describe("turnErrorMessage", () => {
  it("explains busy, timeout and auth failures", () => {
    expect(turnErrorMessage(new ApiError(409, "409 busy"))).toBe(BUSY_MESSAGE);
    expect(turnErrorMessage(new Error("busy"))).toBe(BUSY_MESSAGE);
    expect(turnErrorMessage(new ApiError(504, "x"))).toMatch(/too long/);
    expect(turnErrorMessage(new ApiError(403, "x"))).toMatch(/not allowed/);
    expect(turnErrorMessage(new Error("boom"))).toBe("boom");
  });
});

describe("reconnectDelay", () => {
  it("backs off exponentially, caps at 30s and waits longer when throttled", () => {
    expect(reconnectDelay(0)).toBeLessThan(1000);
    expect(reconnectDelay(3)).toBeGreaterThanOrEqual(4000);
    expect(reconnectDelay(50)).toBeLessThanOrEqual(30_250);
    expect(reconnectDelay(0, 4429)).toBeGreaterThanOrEqual(15_000);
  });
});

describe("session bootstrap", () => {
  it("trades a URL token for a cookie and scrubs it from the URL and storage", async () => {
    window.history.replaceState(null, "", "/?view=chat&token=secret-123");
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, { ok: true, role: "admin" }))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true, role: "admin" }));

    expect(await establishSession()).toBe(true);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/session");
    expect(new Headers(init?.headers).get("X-Amy-Token")).toBe("secret-123");
    expect(window.location.search).toBe("?view=chat");
    expect(sessionStorage.getItem("amy_token")).toBeNull();
    expect(authKey()).toBeTruthy();
    await endSession();
  });

  it("rejects a bad token without storing a session", async () => {
    window.history.replaceState(null, "", "/?token=wrong");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse(401, { detail: "no" }));
    expect(await establishSession()).toBe(false);
    expect(sessionStorage.getItem("amy_session")).toBeNull();
  });

  it("keeps the token when cookies do not stick", async () => {
    window.history.replaceState(null, "", "/?token=t0k");
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: "no cookie" }));
    expect(await establishSession()).toBe(true);
    expect(getToken()).toBe("t0k");
    await endSession();
  });
});

describe("api requests", () => {
  it("never puts the token in the URL and raises ApiError with the server detail", async () => {
    sessionStorage.setItem("amy_token", "abc");
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(409, { detail: "busy" }));
    const err = await api.turn("hi").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.message).toBe("409 busy");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain("abc");
    expect(new Headers(init?.headers).get("X-Amy-Token")).toBe("abc");
  });
});
