import { useState, useRef, useEffect } from "react";
import { clearChat, loadChatHistory, sendChat } from "../lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  edited?: boolean;
}

interface Props {
  runId: number;
  onDocumentUpdate: (doc: string) => void;
}

// Reveals text at a readable "typing" pace instead of appearing instantly.
// The parent remounts this with a fresh key per reply so typing always starts
// at zero — no state resets needed inside.
function TypewriterText({
  text,
  chunk = 3,
  speed = 32,
}: {
  text: string;
  chunk?: number;
  speed?: number;
}) {
  const [length, setLength] = useState(0);

  useEffect(() => {
    const iv = setInterval(() => {
      setLength((prev) => {
        if (prev >= text.length) {
          clearInterval(iv);
          return prev;
        }
        return Math.min(text.length, prev + chunk);
      });
    }, speed);
    return () => clearInterval(iv);
  }, [text, chunk, speed]);

  return <>{text.slice(0, length)}</>;
}

export default function ChatPanel({ runId, onDocumentUpdate }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  // Index of the assistant message currently being typed out (null = show full).
  const [typingIndex, setTypingIndex] = useState<number | null>(null);
  const [historyIndex, setHistoryIndex] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const historyRef = useRef<string[]>([]);
  const draftRef = useRef<string>("");
  const messagesRef = useRef<Message[]>([]);
  const initialLoadDoneRef = useRef(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, historyLoading]);

  // Load the shared conversation for this repo's workspace. The first mount
  // shows a loading state; switching between the API/Architecture tabs hits
  // the same thread, so it refreshes silently and the conversation persists.
  useEffect(() => {
    let cancelled = false;
    const firstLoad = !initialLoadDoneRef.current;
    if (firstLoad) setHistoryLoading(true);
    setTypingIndex(null);
    loadChatHistory(runId)
      .then((history) => {
        if (cancelled) return;
        initialLoadDoneRef.current = true;
        const withEdits: Message[] = history.map((m) => ({
          role: m.role,
          content: m.content,
          edited: m.edited,
        }));
        messagesRef.current = withEdits;
        setMessages(withEdits);
      })
      .catch(() => {
        /* non-fatal: start an empty conversation */
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  // Sync the input box when navigating command history.
  useEffect(() => {
    if (historyIndex === null) {
      setInput(draftRef.current);
    } else {
      setInput(historyRef.current[historyIndex] ?? draftRef.current);
    }
  }, [historyIndex]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowUp") {
      const history = historyRef.current;
      if (history.length === 0) return;
      e.preventDefault();
      if (historyIndex === null) {
        draftRef.current = input;
        setHistoryIndex(history.length - 1);
      } else {
        setHistoryIndex((i) => (i !== null && i > 0 ? i - 1 : 0));
      }
    } else if (e.key === "ArrowDown") {
      if (historyIndex === null) return;
      e.preventDefault();
      if (historyIndex >= historyRef.current.length - 1) {
        setHistoryIndex(null);
      } else {
        setHistoryIndex((i) => (i !== null ? i + 1 : i));
      }
    }
  };

  const handleClear = async () => {
    setMessages([]);
    messagesRef.current = [];
    historyRef.current = [];
    draftRef.current = "";
    setHistoryIndex(null);
    setTypingIndex(null);
    try {
      await clearChat(runId);
    } catch {
      /* history will reload on next visit — non-fatal */
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setHistoryIndex(null);
    draftRef.current = "";
    historyRef.current = [...historyRef.current, text];

    const userMessage: Message = { role: "user", content: text };
    const nextMessages = [...messagesRef.current, userMessage];
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    setLoading(true);

    try {
      const res = await sendChat(runId, text);
      const reply: Message = {
        role: "assistant",
        content: res.reply,
        edited: res.edited,
      };
      const updated = [...messagesRef.current, reply];
      messagesRef.current = updated;
      setMessages(updated);
      // Animate only this freshly received reply, never reloaded history.
      setTypingIndex(updated.length - 1);
      if (res.edited) {
        onDocumentUpdate(res.document);
      }
    } catch (e: unknown) {
      const errMessage: Message = {
        role: "assistant",
        content: e instanceof Error ? e.message : "Something went wrong.",
      };
      const updated = [...messagesRef.current, errMessage];
      messagesRef.current = updated;
      setMessages(updated);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white border border-slate-200/90 rounded-2xl shadow-document overflow-hidden">
      {/* Drawer Folder Tab Header */}
      <div className="px-5 py-3.5 bg-slate-900 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg
            className="w-4 h-4 text-sky-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
            />
          </svg>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200">
            Document Assistant
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
            Run #{runId}
          </span>
          <button
            type="button"
            onClick={handleClear}
            disabled={messages.length === 0 || historyLoading}
            title="Clear chat history"
            className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700 hover:text-red-300 hover:border-red-400/50 disabled:opacity-40 disabled:cursor-not-allowed transition cursor-pointer"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Chat History Container */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3.5 bg-slate-50/50">
        {historyLoading && (
          <div className="flex justify-start animate-slide-down">
            <div className="bg-white border border-slate-200 px-4 py-2.5 rounded-2xl text-xs text-slate-500 flex items-center gap-2 shadow-sm rounded-bl-xs">
              <span className="w-1.5 h-1.5 rounded-full bg-sky-500 animate-pulse" />
              <span>Loading conversation...</span>
            </div>
          </div>
        )}

        {!historyLoading && messages.length === 0 && (
          <div className="text-center py-8 px-4">
            <div className="w-10 h-10 rounded-full bg-sky-50 text-sky-600 flex items-center justify-center mx-auto mb-3 border border-sky-100">
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M13 10V3L4 14h7v7l9-11h-7z"
                />
              </svg>
            </div>
            <p className="text-xs font-semibold text-slate-700 mb-1">
              Interactive Assistant
            </p>
            <p className="text-xs text-slate-400 leading-relaxed">
              Ask questions about this repo or request live document
              modifications.
            </p>
          </div>
        )}

        {messages.map((msg, i) => {
          const animating = msg.role === "assistant" && i === typingIndex && msg.content.length > 0;
          return (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} animate-slide-down`}
            >
              <div
                className={`max-w-[88%] px-3.5 py-2.5 rounded-2xl text-xs leading-relaxed shadow-sm ${
                  msg.role === "user"
                    ? "bg-slate-900 text-white rounded-br-xs"
                    : "bg-white border border-slate-200 text-slate-800 rounded-bl-xs"
                }`}
              >
                <p className="whitespace-pre-wrap">
                  {animating ? (
                    <TypewriterText key={i} text={msg.content} />
                  ) : (
                    msg.content
                  )}
                  {animating && (
                    <span className="inline-block w-1 h-3 bg-sky-500 animate-pulse align-middle ml-0.5" />
                  )}
                </p>
                {msg.edited && (
                  <span className="inline-flex items-center gap-1 mt-2 text-[10px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
                    <svg
                      className="w-3 h-3"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="2"
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                    Updated Document Sheet
                  </span>
                )}
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="flex justify-start animate-slide-down">
            <div className="bg-white border border-slate-200 px-4 py-2.5 rounded-2xl text-xs text-slate-500 flex items-center gap-2 shadow-sm rounded-bl-xs">
              <span className="w-1.5 h-1.5 rounded-full bg-sky-500" />
              <span>Analyzing & drafting response...</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Chat Input Field */}
      <div className="p-3 bg-white border-t border-slate-200/80">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="flex items-center gap-2"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask or request edits..."
            disabled={loading || historyLoading}
            className="flex-1 px-3.5 py-2.5 bg-slate-50 border border-slate-300/80 rounded-xl text-xs focus:bg-white focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 outline-none disabled:opacity-50 transition-all"
          />
          <button
            type="submit"
            disabled={loading || historyLoading || !input.trim()}
            className="p-2.5 bg-slate-900 text-white rounded-xl hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition cursor-pointer shrink-0"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M14 5l7 7m0 0l-7 7m7-7H3"
              />
            </svg>
          </button>
        </form>
      </div>
    </div>
  );
}