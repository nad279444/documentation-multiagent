import { useState, useRef, useEffect } from 'react';
import { sendChat } from '../lib/api';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  edited?: boolean;
}

interface Props {
  runId: number;
  onDocumentUpdate: (doc: string) => void;
}

export default function ChatPanel({ runId, onDocumentUpdate }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;

    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setLoading(true);

    try {
      const res = await sendChat(runId, text);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: res.reply, edited: res.edited },
      ]);
      if (res.edited) {
        onDocumentUpdate(res.document);
      }
    } catch (e: unknown) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: e instanceof Error ? e.message : 'Something went wrong.' },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full border border-slate-200 rounded-xl bg-white shadow-sm">
      <div className="px-4 py-3 border-b border-slate-200">
        <h3 className="text-sm font-semibold text-slate-700">Chat</h3>
        <p className="text-xs text-slate-400">Ask questions or request edits to the document</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && (
          <p className="text-sm text-slate-400 text-center mt-8">
            Try: "Rewrite the introduction" or "What does the /users endpoint do?"
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] px-3 py-2 rounded-lg text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-100 text-slate-800'
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.content}</p>
              {msg.edited && (
                <span className="block mt-1 text-xs text-blue-500 font-medium">
                  Document updated
                </span>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-slate-100 px-3 py-2 rounded-lg text-sm text-slate-500">
              Thinking...
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-slate-200 p-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="flex gap-2"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about the document..."
            disabled={loading}
            className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
