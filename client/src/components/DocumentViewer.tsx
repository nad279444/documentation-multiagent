import { Children, isValidElement, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import mermaid from "mermaid";

interface MermaidBlockProps {
  code: string;
}

function getMermaidCodeFromPre(children: React.ReactNode) {
  const child = Children.toArray(children)[0];
  if (!isValidElement(child)) return null;

  const props = child.props as {
    className?: string;
    children?: React.ReactNode;
  };
  if (!props.className?.includes("language-mermaid")) return null;

  return String(props.children).replace(/\n$/, "");
}
function MermaidBlock({ code }: MermaidBlockProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let bindFunctions: ((el: Element) => void) | undefined;

    async function render() {
      const el = ref.current;
      if (!el) return;
      try {
        mermaid.initialize({
          startOnLoad: false,
          theme: "base",
          darkMode: false,
          themeVariables: {
            background: "#ffffff",
            primaryColor: "#eef2ff",
            primaryTextColor: "#0f172a",
            primaryBorderColor: "#a5b4fc",
            clusterBkg: "#f8fafc",
            clusterBorder: "#e2e8f0",
            edgeLabelBackground: "#ffffff",
            lineColor: "#64748b",
            fontFamily: "inherit",
          },
        });
        // Force left-to-right flow so wide data-flow diagrams read horizontally.
        const horizontalCode = code.replace(
          /^(graph|flowchart)\s+(TB|TD|BT|RL)\s/m,
          "$1 LR\n",
        );
        const id = `mermaid-${Math.random().toString(36).slice(2, 10)}`;
        const result = await mermaid.render(id, horizontalCode);
        const { svg } = result;
        bindFunctions = result.bindFunctions;
        if (cancelled) return;
        el.innerHTML = svg;
        const svgEl = el.querySelector("svg");
        if (svgEl) {
          svgEl.style.backgroundColor = "#ffffff";
          svgEl.style.minWidth = "960px";
          svgEl.style.maxWidth = "none";
          svgEl.style.height = "auto";
        }
        bindFunctions?.(el);
        setError(null);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Diagram failed to render");
        }
      }
    }

    render();
    return () => {
      cancelled = true;
      if (bindFunctions && ref.current) bindFunctions(ref.current);
    };
  }, [code]);

  return (
    <div className="my-6 -mx-2 sm:-mx-6">
      {error ? (
        <pre className="bg-red-50 border border-red-200 text-red-700 text-xs rounded-lg p-3 overflow-x-auto">
          {code}
          <div className="mt-2 font-sans">Mermaid error: {error}</div>
        </pre>
      ) : (
        <div
          ref={ref}
          className="mermaid-diagram-canvas w-full overflow-x-auto bg-white rounded-xl border border-slate-200 p-4 sm:p-6 shadow-sm"
        />
      )}
    </div>
  );
}

interface Props {
  content: string;
  onSave: (edited: string) => void;
  onDownload: () => void;
  onNewDoc: () => void;
  saving: boolean;
}

export default function DocumentViewer({
  content,
  onSave,
  onDownload,
  onNewDoc,
  saving,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(content);

  const handleSave = () => {
    onSave(draft);
    setEditing(false);
  };

  return (
    <div className="space-y-4 w-full h-full flex flex-col">
      {/* Folder Header Toolbar */}
      <div className="bg-slate-900 text-white p-3 rounded-2xl border border-slate-800 shadow-sm flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3 pl-2">
          <div className="w-3 h-3 rounded-full bg-red-500/80" />
          <div className="w-3 h-3 rounded-full bg-amber-500/80" />
          <div className="w-3 h-3 rounded-full bg-emerald-500/80" />
          <span className="text-xs font-mono text-slate-400 border-l border-slate-700 pl-3">
            document_output.md
          </span>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            onClick={() => {
              setDraft(content);
              setEditing(!editing);
            }}
            className="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg transition cursor-pointer flex items-center gap-1.5"
          >
            <svg
              className="w-3.5 h-3.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
              />
            </svg>
            {editing ? "Cancel" : "Edit Sheet"}
          </button>

          {editing && (
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-3 py-1.5 text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg disabled:opacity-50 transition cursor-pointer flex items-center gap-1.5 shadow-sm"
            >
              <svg
                className="w-3.5 h-3.5"
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
              {saving ? "Saving..." : "Save Changes"}
            </button>
          )}

          <button
            onClick={onDownload}
            className="px-3 py-1.5 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-lg transition cursor-pointer flex items-center gap-1.5 shadow-sm"
          >
            <svg
              className="w-3.5 h-3.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
              />
            </svg>
            Export PDF
          </button>

          <button
            onClick={onNewDoc}
            className="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded-lg transition cursor-pointer"
          >
            New Document
          </button>
        </div>
      </div>

      {/* Main Document Paper Sheet */}
      <div className="bg-white border border-slate-200/90 rounded-2xl shadow-document px-4 sm:px-8 py-6 relative overflow-hidden transition-all duration-300 flex-1 min-h-0 flex flex-col">
        {/* Decorative Top Paper Crease Line */}
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-sky-500 via-indigo-500 to-slate-800" />

        {editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full min-h-[45vh] sm:min-h-[650px] p-4 font-mono text-xs sm:text-sm text-slate-800 leading-relaxed bg-slate-50/50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 resize-y"
          />
        ) : (
          <article
            id="document-content"
            className="markdown-body prose prose-slate max-w-none flex-1 min-h-0 overflow-y-auto"
          >
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                pre({ children, ...props }) {
                  const mermaidCode = getMermaidCodeFromPre(children);
                  if (mermaidCode) return <MermaidBlock code={mermaidCode} />;
                  return <pre {...props}>{children}</pre>;
                },
                code({ className, children, ...props }) {
                  const isMermaid =
                    typeof className === "string" &&
                    className.includes("language-mermaid");
                  if (isMermaid) return <code className={className}>{children}</code>;
                  return (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  );
                },
              }}
            >
              {content}
            </ReactMarkdown>
          </article>
        )}
      </div>
    </div>
  );
}