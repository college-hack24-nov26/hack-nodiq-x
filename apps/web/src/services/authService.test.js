/**
 * Session-resilience tests — the "logged out after one analysis" regression.
 *
 * fetchCurrentUser must only clear the cached session when the server
 * *definitively* rejects the credential (401/403). Transient failures
 * (5xx, network blips while a heavy analysis hogs the server) must keep
 * the cached user — otherwise the next page load after an analysis logs
 * the user out.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchCurrentUser, getCurrentUser, setCurrentUser, logoutUser } from "./authService";

if (typeof globalThis.localStorage === "undefined") {
  let store = {};
  globalThis.localStorage = {
    getItem: (key) => store[key] ?? null,
    setItem: (key, value) => { store[key] = String(value); },
    removeItem: (key) => { delete store[key]; },
    clear: () => { store = {}; },
  };
}

const USER = { id: "USR-1", email: "probe@test.local", name: "Probe" };

describe("fetchCurrentUser session resilience", () => {
  beforeEach(() => {
    localStorage.clear();
    setCurrentUser(USER);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("keeps the cached session when /api/auth/me returns 5xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "internal" }), { status: 503 })));
    const user = await fetchCurrentUser();
    expect(user).toEqual(expect.objectContaining({ email: USER.email }));
    expect(getCurrentUser()).not.toBeNull();
  });

  it("keeps the cached session when the network fails entirely", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const user = await fetchCurrentUser();
    expect(user).toEqual(expect.objectContaining({ email: USER.email }));
    expect(getCurrentUser()).not.toBeNull();
  });

  it("keeps the cached session on 429 rate limiting", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "too many requests" }), { status: 429 })));
    const user = await fetchCurrentUser();
    expect(user).not.toBeNull();
    expect(getCurrentUser()).not.toBeNull();
  });

  it("clears the session when the server definitively rejects (401)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 })));
    const user = await fetchCurrentUser();
    expect(user).toBeNull();
    expect(getCurrentUser()).toBeNull();
  });

  it("clears the session when the server definitively rejects (403)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "forbidden" }), { status: 403 })));
    const user = await fetchCurrentUser();
    expect(user).toBeNull();
    expect(getCurrentUser()).toBeNull();
  });

  it("refreshes the cached user on a successful probe", async () => {
    const fresh = { ...USER, name: "Renamed" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ user: fresh }), { status: 200 })));
    const user = await fetchCurrentUser();
    expect(user.name).toBe("Renamed");
    expect(getCurrentUser().name).toBe("Renamed");
  });

  it("returns null when there is no cached session at all", async () => {
    localStorage.clear();
    const user = await fetchCurrentUser();
    expect(user).toBeNull();
  });

  it("logout still clears everything even if the server call fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await logoutUser();
    expect(getCurrentUser()).toBeNull();
  });
});
