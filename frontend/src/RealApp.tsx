import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, FormEvent } from "react";

type Discussion = { id: number; topic: string; expert_count: number; status: string; is_preset: boolean; created_at: string; summary?: string | null };
type Participant = { id: number; role: "host" | "expert"; name: string; title: string; background: string; stance: string; color: string };
type Message = { id: number; speaker_id: number; sequence: number; content: string; created_at: string; action?: string | null };
type Insight = { id: number; kind: "consensus" | "disagreement"; content: string; is_active: boolean; version: number; evidence_message_ids: number[] };
type StudioEvent = { discussion_id: number; sequence: number; type: string; payload: Record<string, unknown> };

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(path, options); }
  catch { throw new Error("无法连接后端，请确认 FastAPI 服务已启动"); }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `请求失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<T>;
}

const base = (id: number) => `/api/v1/discussions/${id}`;
const statusText: Record<string, string> = { draft: "待生成嘉宾", roster_ready: "待确认阵容", confirmed: "阵容已确认", running: "讨论进行中", completed: "讨论完成", stopped: "已停止", failed: "运行失败" };
const terminal = new Set(["completed", "stopped", "failed"]);
const actionText: Record<string, string> = { open: "开场", invite: "邀请发言", answer: "回应", add: "补充", rebut: "反驳", question: "追问", interrupt: "插话", moderate: "串联", summary: "总结" };

export default function RealApp({ onDemo }: { onDemo: () => void }) {
  const [discussions, setDiscussions] = useState<Discussion[]>([]);
  const [current, setCurrent] = useState<Discussion | null>(null);
  const [people, setPeople] = useState<Participant[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [statuses, setStatuses] = useState<Record<number, { status: string; focus?: string; action?: string }>>({});
  const [view, setView] = useState<"hall" | "roster" | "studio">("hall");
  const [topic, setTopic] = useState("");
  const [expertCount, setExpertCount] = useState(4);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("");
  const cursor = useRef(0);
  const activeId = useRef<number | null>(null);
  const transcriptRef = useRef<HTMLElement | null>(null);
  const shouldFollow = useRef(true);

  const loadList = useCallback(async () => {
    setLoading(true);
    try { setDiscussions(await api<Discussion[]>("/api/v1/discussions")); setError(""); }
    catch (cause) { setError((cause as Error).message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void loadList(); }, [loadList]);

  const loadDiscussion = useCallback(async (id: number) => {
    activeId.current = id;
    cursor.current = 0;
    setError(""); setStatuses({}); setMessages([]); setInsights([]); setPeople([]); setLoading(true);
    try {
      const [d, p, m, i] = await Promise.all([
        api<Discussion>(base(id)), api<Participant[]>(`${base(id)}/participants`),
        api<Message[]>(`${base(id)}/transcript`), api<Insight[]>(`${base(id)}/insights`),
      ]);
      if (activeId.current !== id) return;
      setCurrent(d); setPeople(p); setMessages(m); setInsights(i);
      setView(["running", "completed", "stopped", "failed", "confirmed"].includes(d.status) ? "studio" : "roster");
    } catch (cause) { setError((cause as Error).message); }
    finally { if (activeId.current === id) setLoading(false); }
  }, []);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!topic.trim()) { setError("请输入讨论话题"); return; }
    setBusy(true); setError("");
    try {
      const d = await api<Discussion>("/api/v1/discussions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: topic.trim(), expert_count: expertCount }),
      });
      await loadDiscussion(d.id);
      await generateRoster(d.id);
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };

  const generateRoster = async (id: number) => {
    setBusy(true); setError("");
    try {
      const roster = await api<Participant[]>(`${base(id)}/roster`, { method: "POST" });
      if (activeId.current !== id) return;
      setPeople(roster);
      setCurrent(await api<Discussion>(base(id)));
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };

  const confirm = async () => {
    if (!current) return;
    setBusy(true); setError("");
    try { setCurrent(await api<Discussion>(`${base(current.id)}/confirm`, { method: "POST" })); setView("studio"); }
    catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };

  const start = async () => {
    if (!current) return;
    setBusy(true); setError("");
    try { await api(`${base(current.id)}/start`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      setCurrent(d => d && ({ ...d, status: "running" })); }
    catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };

  const stop = async () => {
    if (!current) return;
    setBusy(true); setError("");
    try { await api(`${base(current.id)}/stop`, { method: "POST" });
      setCurrent(d => d && ({ ...d, status: "stopped" })); }
    catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    if (!current || view !== "studio" || terminal.has(current.status)) return;
    const id = current.id;
    const stream = new EventSource(`${base(id)}/events?after=${cursor.current}`);
    let streamClosed = false;
    const names = ["discussion.status", "participant.status", "participant.hand_raised", "message.created", "insights.updated", "discussion.summary", "discussion.error"];
    const handle = (event: Event) => {
      const update = JSON.parse((event as MessageEvent).data) as StudioEvent;
      if (activeId.current !== id || update.discussion_id !== id || update.sequence <= cursor.current) return;
      cursor.current = update.sequence;
      setConnection("");
      const payload = update.payload;
      if (update.type === "discussion.status") {
        const status = String(payload.status);
        setCurrent(d => d && ({ ...d, status }));
        if (terminal.has(status)) { setStatuses({}); setConnection(""); streamClosed = true; stream.close(); }
      } else if (update.type === "message.created") {
        const panel = transcriptRef.current;
        shouldFollow.current = !panel || panel.scrollHeight - panel.scrollTop - panel.clientHeight < 90;
        const item: Message = { id: Number(payload.message_id), speaker_id: Number(payload.speaker_id),
          sequence: Number(payload.sequence), content: String(payload.content), created_at: new Date().toISOString(), action: String(payload.action) };
        setMessages(items => items.some(existing => existing.id === item.id)
          ? items.map(existing => existing.id === item.id ? { ...existing, action: item.action } : existing)
          : [...items, item].sort((a, b) => a.sequence - b.sequence));
      } else if (update.type === "participant.status" || update.type === "participant.hand_raised") {
        const participantId = Number(payload.participant_id);
        setStatuses(old => ({ ...old, [participantId]: {
          status: update.type === "participant.hand_raised" ? "hand_raised" : String(payload.status),
          focus: typeof payload.focus === "string" ? payload.focus : old[participantId]?.focus,
          action: typeof payload.action === "string" ? payload.action : old[participantId]?.action,
        } }));
      } else if (update.type === "insights.updated") {
        void api<Insight[]>(`${base(id)}/insights`).then(items => { if (activeId.current === id) setInsights(items); });
      } else if (update.type === "discussion.summary") {
        setCurrent(d => d && ({ ...d, summary: String(payload.text) }));
      } else if (update.type === "discussion.error") {
        setError(String(payload.message));
      }
    };
    names.forEach(name => stream.addEventListener(name, handle));
    stream.onerror = () => { if (!streamClosed && activeId.current === id) setConnection("实时连接中断，正在自动重连…"); };
    return () => { streamClosed = true; stream.close(); };
  }, [current?.id, current?.status, view]);

  useEffect(() => {
    if (shouldFollow.current && transcriptRef.current) transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
  }, [messages.length]);

  const home = () => { activeId.current = null; setView("hall"); setCurrent(null); setError(""); void loadList(); };
  if (view === "hall") return <main className="hall"><header><b>AI PANEL STUDIO</b><span>AI 圆桌讨论演播厅</span><button onClick={onDemo}>体验 Mock 演示</button></header>
    <section className="hero"><p>多元视角，不止一轮回答</p><h1>让观点在同一张桌上交锋</h1>
      <form onSubmit={create}><input value={topic} onChange={e => setTopic(e.target.value)} placeholder="输入真实讨论话题" aria-label="讨论话题"/>
        <select value={expertCount} onChange={e => setExpertCount(Number(e.target.value))} aria-label="专家人数">{[2,3,4,5,6].map(x => <option key={x} value={x}>{x} 位专家</option>)}</select>
        <button disabled={busy}>{busy ? "正在生成嘉宾…" : "创建并生成嘉宾"}</button></form>
      {error && <p role="alert" className="error">{error} <button onClick={() => void loadList()}>重试列表</button></p>}</section>
    <section className="list"><h2>讨论大厅</h2>{loading ? <p>正在加载讨论…</p> : discussions.length ? discussions.map(d =>
      <button className="discussion" onClick={() => void loadDiscussion(d.id)} key={d.id}><i className={d.status}/><strong>{d.topic}</strong>
        <span>{statusText[d.status] ?? d.status} · {d.expert_count} 位专家 · {new Date(d.created_at).toLocaleDateString("zh-CN")}{d.is_preset ? " · 预设样例" : ""}</span></button>) : <p>暂无讨论，创建第一场圆桌讨论。</p>}</section></main>;

  return <main className="studio"><header><button onClick={home}>← 大厅</button><div><b>{current?.topic ?? "正在加载"}</b><small>真实 AI 模式 · DeepSeek 生成并持久化</small></div>
    <span className="pill">{statusText[current?.status ?? ""] ?? "加载中"}</span></header>
    {error && <p role="alert" className="error">{error}</p>}{connection && <p className="connection">{connection}</p>}
    {loading ? <p className="empty">正在读取讨论数据…</p> : view === "roster" ?
      <section className="roster"><div><p>嘉宾阵容</p><h1>{current?.topic}</h1><small>{current?.is_preset ? "预设样例嘉宾，非实时 AI 生成" : "以下阵容由真实模型生成，确认后方可开始讨论"}</small></div>
        {people.length ? <div className="cards">{people.map(p => <article style={{ "--c": p.color } as CSSProperties} key={p.id}>
          <em>{p.role === "host" ? "主持人" : "专家"}</em><h3>{p.name}</h3><b>{p.title}</b><p>{p.background}</p><q>{p.stance}</q></article>)}</div>
          : <p className="empty">等待生成嘉宾阵容。{busy ? "正在请求模型…" : "生成失败时可重试。"}</p>}
        {current?.status === "draft" ? <button className="primary" disabled={busy} onClick={() => void generateRoster(current.id)}>生成真实嘉宾阵容</button>
          : <button className="primary" disabled={busy || !people.length} onClick={() => void confirm()}>确认阵容，进入演播厅</button>}</section>
      : <section className="grid"><aside className="participants"><h3>嘉宾状态</h3>{people.map(p => {
        const state = statuses[p.id];
        const status = state?.status ?? "idle";
        const label = status === "speaking" ? "发言中" : status === "preparing" ? "准备发言" : status === "hand_raised" ? "申请发言" : "待机";
        return <article className={`participant-card ${p.role} ${status}`} data-status={status} style={{ "--c": p.color } as CSSProperties} key={p.id}>
          <div className="participant-head"><i/><div><b>{p.name}</b><small>{p.title}</small></div><em>{p.role === "host" ? "主持人" : "专家"}</em></div>
          <span className="participant-state">{label}{state?.action ? ` · ${actionText[state.action] ?? state.action}` : ""}</span>
          <p className="participant-focus"><b>公开关注点</b>{state?.focus ?? p.stance}</p>
        </article>; })}</aside>
        <section className="transcript" ref={transcriptRef}><div className="controls"><b>实时 Transcript</b>
          {current?.status === "confirmed" && <button disabled={busy} onClick={() => void start()}>开始真实讨论</button>}
          {current?.status === "running" && <button disabled={busy} onClick={() => void stop()}>停止讨论</button>}</div>
          {messages.length ? messages.map(m => { const p = people.find(x => x.id === m.speaker_id); return <article key={m.id}>
            <i style={{ background: p?.color ?? "#64d2ff" }}/><b>{p?.name ?? "嘉宾"}</b><small>{p?.title} · {String(m.sequence).padStart(2, "0")}{m.action ? ` · ${actionText[m.action] ?? m.action}` : ""}</small><p>{m.content}</p></article>; })
            : <p className="empty">{current?.status === "confirmed" ? "阵容已确认，点击开始讨论。" : "等待主持人开场…"}</p>}
          {current?.summary && <footer><b>主持人总结</b><p>{current.summary}</p></footer>}</section>
        <aside className="insights"><h3>共识</h3>{insights.filter(i => i.is_active && i.kind === "consensus").length ? insights.filter(i => i.is_active && i.kind === "consensus").map(i =>
          <p className="active" key={i.id}>{i.content}<small>依据发言 #{i.evidence_message_ids.map(id => messages.find(m => m.id === id)?.sequence).filter(Boolean).join("、")}</small></p>) : <p>随着真实发言逐步形成</p>}
          <h3>分歧</h3>{insights.filter(i => i.is_active && i.kind === "disagreement").length ? insights.filter(i => i.is_active && i.kind === "disagreement").map(i =>
            <p className="active" key={i.id}>{i.content}<small>依据发言 #{i.evidence_message_ids.map(id => messages.find(m => m.id === id)?.sequence).filter(Boolean).join("、")}</small></p>) : <p>等待观点交锋</p>}</aside></section>}
  </main>;
}
