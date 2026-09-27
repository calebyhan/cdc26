"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { ArrowUp, Loader2, MapPin, RotateCcw, Sparkles, X } from "lucide-react";

export type AssistantAction =
  | { type: "open_workspace"; workspace: string }
  | { type: "open_state"; state: string; hospitalId?: string | null }
  | { type: "open_navigator"; state: string; hospitalId?: string | null };

type Message = {
  role: "user" | "model";
  text: string;
  actions?: AssistantAction[];
  error?: boolean;
};

const SUGGESTIONS: Record<string, string[]> = {
  atlas: [
    "Where is reported medical-debt collection pressure highest?",
    "Show me North Carolina and explain what stands out",
    "What does “compared with expected” mean?",
  ],
  upload: [
    "Which documents should I upload?",
    "Is my insurance EOB proof that I paid?",
    "What should I check before creating my timeline?",
  ],
  demo: [
    "Explain my case findings in plain language",
    "What should I ask the billing office?",
    "Should I write to the provider or the collector first?",
  ],
  evidence: [
    "How do I correct a value the app read wrong?",
    "Why does each value show a quote?",
  ],
  research: [
    "What do “debt was paid” complaints tell us?",
    "Are these complaints verified?",
  ],
};

const workspaceLabel: Record<string, string> = {
  atlas: "Community map",
  upload: "Upload a case",
  demo: "Case overview",
  evidence: "Documents & review",
  research: "Complaint research",
};

function actionLabel(action: AssistantAction) {
  if (action.type === "open_workspace")
    return `Opened ${workspaceLabel[action.workspace] ?? action.workspace}`;
  if (action.type === "open_state") return `Showing ${action.state} on the map`;
  return `Opened the navigator for ${action.state}`;
}

/** Tiny safe formatter: paragraphs, "- " bullets, and **bold**. No HTML injection. */
function Formatted({ text }: { text: string }) {
  const inline = (line: string) =>
    line.split(/(\*\*[^*]+\*\*)/g).map((chunk, i) =>
      chunk.startsWith("**") && chunk.endsWith("**") ? (
        <strong key={i}>{chunk.slice(2, -2)}</strong>
      ) : (
        <Fragment key={i}>{chunk}</Fragment>
      ),
    );
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length)
      blocks.push(
        <ul key={`u${blocks.length}`}>
          {bullets.map((b, i) => (
            <li key={i}>{inline(b)}</li>
          ))}
        </ul>,
      );
    bullets = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (bullet) bullets.push(bullet[1]);
    else {
      flush();
      if (line) blocks.push(<p key={`p${blocks.length}`}>{inline(line.replace(/^#+\s*/, ""))}</p>);
    }
  }
  flush();
  return <>{blocks}</>;
}

export function Assistant({
  workspace,
  context,
  caseSummary,
  onAction,
}: {
  workspace: string;
  context: { state: string | null; hospitalId: string | null };
  caseSummary: Record<string, unknown> | null;
  onAction: (action: AssistantAction) => void;
}) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [shareCase, setShareCase] = useState(false);
  const request = useRef<AbortController | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  async function ask(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    const history = [...messages.filter((m) => !m.error), { role: "user" as const, text }];
    setMessages((current) => [...current, { role: "user", text }]);
    setDraft("");
    setBusy(true);
    const controller = new AbortController();
    request.current = controller;
    try {
      const response = await fetch("/api/assistant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        signal: controller.signal,
        body: JSON.stringify({
          messages: history.map(({ role, text }) => ({ role, text })),
          context: { workspace, ...context },
          includeCase: shareCase && !!caseSummary,
          caseSummary: shareCase ? caseSummary : null,
        }),
      });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || "The guide is unavailable.");
      const actions: AssistantAction[] = Array.isArray(data.actions) ? data.actions : [];
      actions.forEach(onAction);
      setMessages((current) => [
        ...current,
        { role: "model", text: String(data.reply || ""), actions },
      ]);
    } catch (error) {
      if (controller.signal.aborted) return;
      setMessages((current) => [
        ...current,
        {
          role: "model",
          text: error instanceof Error ? error.message : "The guide is unavailable.",
          error: true,
        },
      ]);
    } finally {
      if (request.current === controller) request.current = null;
      setBusy(false);
    }
  }

  const suggestions = SUGGESTIONS[workspace] ?? SUGGESTIONS.atlas;

  return (
    <>
      {!open && (
        <button className="guide-launcher" onClick={() => setOpen(true)}>
          <Sparkles size={17} aria-hidden="true" />
          Ask the guide
        </button>
      )}
      {open && (
        <section className="guide-panel" aria-label="Not My Debt guide">
          <header className="guide-head">
            <div>
              <strong>
                <Sparkles size={15} aria-hidden="true" /> Guide
              </strong>
              <small>Answers from Google Gemini using the app’s public data</small>
            </div>
            <div className="guide-head-actions">
              {messages.length > 0 && (
                <button
                  className="icon-button"
                  aria-label="Start a new conversation"
                  onClick={() => {
                    request.current?.abort();
                    setMessages([]);
                  }}
                >
                  <RotateCcw size={14} />
                </button>
              )}
              <button className="icon-button" aria-label="Close guide" onClick={() => setOpen(false)}>
                <X size={15} />
              </button>
            </div>
          </header>
          <div className="guide-log" ref={log} aria-live="polite">
            {messages.length === 0 && (
              <div className="guide-empty">
                <p>
                  I can explain the map, walk you through uploading your bills,
                  and help you figure out what to ask billing or a collector.
                </p>
                <div className="guide-suggestions">
                  {suggestions.map((s) => (
                    <button key={s} onClick={() => ask(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`guide-msg ${m.role} ${m.error ? "error" : ""}`}>
                {m.role === "model" ? <Formatted text={m.text} /> : <p>{m.text}</p>}
                {m.actions?.map((a, j) => (
                  <button key={j} className="guide-action" onClick={() => onAction(a)}>
                    <MapPin size={12} /> {actionLabel(a)}
                  </button>
                ))}
              </div>
            ))}
            {busy && (
              <div className="guide-msg model pending">
                <Loader2 className="spin" size={14} /> Thinking…
              </div>
            )}
          </div>
          <footer className="guide-foot">
            {caseSummary && (
              <label className="guide-share">
                <input
                  type="checkbox"
                  checked={shareCase}
                  onChange={(e) => setShareCase(e.target.checked)}
                />
                Share my case summary (balances and findings; no document text)
              </label>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                ask(draft);
              }}
            >
              <textarea
                ref={input}
                value={draft}
                rows={2}
                maxLength={2000}
                placeholder="Ask about the map, your bills, or next steps…"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    ask(draft);
                  }
                }}
              />
              <button
                type="submit"
                className="guide-send"
                disabled={busy || !draft.trim()}
                aria-label="Send"
              >
                <ArrowUp size={16} />
              </button>
            </form>
            <small>
              Questions go to Google Gemini. General information, not legal
              advice. Don’t share Social Security or full account numbers.
            </small>
          </footer>
        </section>
      )}
    </>
  );
}
