// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import RealApp from "./RealApp";

const discussion = { id: 7, topic: "真实议题", expert_count: 4, status: "draft", is_preset: false, created_at: "2026-10-16T00:00:00" };
const roster = [{ id: 11, role: "host", name: "真实主持", title: "主持人", background: "公共议题", stance: "中立", color: "#112233" }];
const json = (data: unknown, status = 200) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(data) } as Response);

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners = new Map<string, (event: Event) => void>();
  onerror: (() => void) | null = null;
  constructor(public url: string) { FakeEventSource.instances.push(this); }
  addEventListener(name: string, callback: (event: Event) => void) { this.listeners.set(name, callback); }
  close() {}
  emit(name: string, sequence: number, payload: Record<string, unknown>) {
    this.listeners.get(name)?.({ data: JSON.stringify({ discussion_id: 7, sequence, type: name, payload }) } as MessageEvent);
  }
}

beforeEach(() => { FakeEventSource.instances = []; vi.stubGlobal("EventSource", FakeEventSource); });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("creates a real discussion with four experts by default and requests a real roster", async () => {
  const calls: Array<{ path: string; options?: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn((path: string, options?: RequestInit) => {
    calls.push({ path, options });
    if (path === "/api/v1/discussions" && options?.method === "POST") return json(discussion);
    if (path === "/api/v1/discussions") return json([]);
    if (path.endsWith("/roster")) return json(roster);
    if (path.endsWith("/participants")) return json([]);
    if (path.endsWith("/transcript") || path.endsWith("/insights")) return json([]);
    if (path.endsWith("/7")) return json({ ...discussion, status: "roster_ready" });
    throw Error(path);
  }));
  render(<RealApp onDemo={() => {}} />);
  fireEvent.change(await screen.findByLabelText("讨论话题"), { target: { value: "真实议题" } });
  fireEvent.click(screen.getByRole("button", { name: "创建并生成嘉宾" }));
  await screen.findByText("真实主持");
  const created = calls.find(x => x.options?.method === "POST" && x.path === "/api/v1/discussions");
  expect(JSON.parse(String(created?.options?.body)).expert_count).toBe(4);
  expect(calls.some(x => x.path.endsWith("/roster"))).toBe(true);
});

it("shows a useful error when the real API is unavailable", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
  render(<RealApp onDemo={() => {}} />);
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("无法连接后端"));
});

it("does not show preset conclusions for an existing real discussion", async () => {
  vi.stubGlobal("fetch", vi.fn((path: string) => {
    if (path === "/api/v1/discussions") return json([{ ...discussion, status: "completed" }]);
    if (path.endsWith("/participants")) return json(roster);
    if (path.endsWith("/transcript") || path.endsWith("/insights")) return json([]);
    return json({ ...discussion, status: "completed", summary: null });
  }));
  render(<RealApp onDemo={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /真实议题/ }));
  expect(await screen.findByText("随着真实发言逐步形成")).toBeTruthy();
  expect(screen.getByText("等待观点交锋")).toBeTruthy();
});

it("updates messages, participant state, and insights only from backend events", async () => {
  let insightReady = false;
  vi.stubGlobal("fetch", vi.fn((path: string) => {
    if (path === "/api/v1/discussions") return json([{ ...discussion, status: "running" }]);
    if (path.endsWith("/participants")) return json(roster);
    if (path.endsWith("/transcript")) return json([]);
    if (path.endsWith("/insights")) return json(insightReady ? [{ id: 3, kind: "consensus", content: "已发表的共识", is_active: true, version: 1, evidence_message_ids: [42] }] : []);
    return json({ ...discussion, status: "running", summary: null });
  }));
  render(<RealApp onDemo={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /真实议题/ }));
  await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
  const stream = FakeEventSource.instances[0];
  stream.emit("participant.hand_raised", 1, { participant_id: 11 });
  expect(await screen.findByText("申请发言")).toBeTruthy();
  stream.emit("participant.status", 2, { participant_id: 11, status: "speaking", action: "rebut" });
  expect(await screen.findByText("发言中")).toBeTruthy();
  stream.emit("message.created", 3, { message_id: 42, speaker_id: 11, sequence: 1, content: "针对前一观点，我提出反驳。", action: "rebut" });
  stream.emit("message.created", 3, { message_id: 42, speaker_id: 11, sequence: 1, content: "针对前一观点，我提出反驳。", action: "rebut" });
  expect((await screen.findAllByText("针对前一观点，我提出反驳。")).length).toBe(1);
  expect(await screen.findByText(/· 反驳$/)).toBeTruthy();
  insightReady = true;
  stream.emit("insights.updated", 4, { insight_ids: [3] });
  expect(await screen.findByText("已发表的共识")).toBeTruthy();
});
