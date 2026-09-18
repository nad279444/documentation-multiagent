import { useCallback, useEffect, useRef, useState } from "react";
import { getRun, submitGeneration } from "./lib/api";
import SubmitForm from "./components/SubmitForm";
import DocumentViewer from "./components/DocumentViewer";
import ChatPanel from "./components/ChatPanel";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";

type Phase = "submit" | "polling" | "view";

export default function App() {
  const [phase, setPhase] = useState<Phase>("submit");
  const [runId, setRunId] = useState<number | null>(null);
  const [status, setStatus] = useState("");
  const [document, setDocument] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cacheHit, setCacheHit] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  const handleSubmit = async (
    url: string,
    docType: "api" | "architecture",
    branch: string,
  ) => {
    setSubmitting(true);
    setError("");
    try {
      const res = await submitGeneration({
        repo_url: url,
        doc_type: docType,
        branch: branch || null,
      });
      setRunId(res.run_id);
      setStatus(res.status);

      const terminal = [
        "approved",
        "needs_revision",
        "needs_human_review",
        "error",
      ];
      if (terminal.includes(res.status)) {
        setCacheHit(res.cached);
        try {
          const run = await getRun(res.run_id);
          if (run.output) {
            setDocument(run.output);
            setPhase("view");
          } else {
            setPhase("polling");
            startPolling(res.run_id);
          }
        } catch {
          setPhase("polling");
          startPolling(res.run_id);
        }
      } else {
        setPhase("polling");
        startPolling(res.run_id);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  const startPolling = (id: number) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const run = await getRun(id);
        setStatus(run.status);
        const terminal = [
          "approved",
          "needs_revision",
          "needs_human_review",
          "error",
        ];
        if (terminal.includes(run.status)) {
          stopPolling();
          if (run.output) {
            setDocument(run.output);
            setPhase("view");
          } else if (run.status === "error") {
            setError(
              run.eval_report && "error" in run.eval_report
                ? String(run.eval_report.error)
                : "Generation failed",
            );
          }
        }
      } catch {
        stopPolling();
        setError("Lost connection to server");
      }
    }, 2000);
  };

  const handleSave = async (edited: string) => {
    setSaving(true);
    try {
      setDocument(edited);
    } finally {
      setSaving(false);
    }
  };

  const handleDownload = async () => {
    const el = window.document.getElementById("document-content");
    if (!el) return;

    const canvas = await html2canvas(el, { scale: 2, useCORS: true });
    const imgData = canvas.toDataURL("image/png");
    const pdf = new jsPDF("p", "mm", "a4");
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const imgWidth = pageWidth - 20;
    const imgHeight = (canvas.height * imgWidth) / canvas.width;

    if (imgHeight <= pageHeight - 20) {
      pdf.addImage(imgData, "PNG", 10, 10, imgWidth, imgHeight);
    } else {
      let remaining = imgHeight;
      let srcY = 0;
      while (remaining > 0) {
        const sliceH = Math.min(remaining, pageHeight - 20);
        const sliceRatio = sliceH / imgHeight;
        const sliceCanvas = window.document.createElement("canvas");
        sliceCanvas.width = canvas.width;
        sliceCanvas.height = canvas.height * sliceRatio;
        const ctx = sliceCanvas.getContext("2d")!;
        ctx.drawImage(
          canvas,
          0,
          srcY,
          canvas.width,
          canvas.height * sliceRatio,
          0,
          0,
          canvas.width,
          canvas.height * sliceRatio,
        );
        pdf.addImage(
          sliceCanvas.toDataURL("image/png"),
          "PNG",
          10,
          10,
          imgWidth,
          sliceH,
        );
        remaining -= sliceH;
        srcY += canvas.height * sliceRatio;
        if (remaining > 0) pdf.addPage();
      }
    }

    pdf.save("documentation.pdf");
  };

  const handleNewDoc = () => {
    setPhase("submit");
    setRunId(null);
    setDocument("");
    setStatus("");
    setError("");
  };

  const statusLabel: Record<string, string> = {
    queued: "Queued in Cabinet",
    cloning: "Fetching Repository Files",
    parsing: "Extracting AST & Structure",
    embedding: "Building Knowledge Index",
    generating: "Drafting Document Leaf",
    evaluating: "Reviewing Quality & Tone",
    needs_revision: "Refine Document",
    approved: "Filing Complete",
    needs_human_review: "Manual Inspection Required",
    error: "Filing Error",
  };

  return (
    <div className="min-h-screen bg-slate-100/80 flex flex-col font-sans text-slate-800 antialiased selection:bg-sky-100 selection:text-sky-900">
      {/* Top Navigation Header */}
      <header className="bg-slate-900 text-white border-b border-slate-800 sticky top-0 z-30 shadow-md">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-sky-500/10 border border-sky-500/30 rounded-lg text-sky-400">
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
                  d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
                />
              </svg>
            </div>
            <div>
              <h1 className="text-base font-semibold tracking-wide text-slate-100 flex items-center gap-2">
                DocAgent{" "}
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono border border-slate-700">
                  v2.0
                </span>
              </h1>
              <p className="text-xs text-slate-400">
                Automated Documentation Workspace
              </p>
            </div>
          </div>

          {/* Folder Tabs Progress Header */}
          <div className="hidden sm:flex items-center gap-1 bg-slate-800/80 p-1 rounded-xl border border-slate-700/50">
            <div
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${phase === "submit" ? "bg-sky-500 text-white shadow-sm" : "text-slate-400 hover:text-slate-200"}`}
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
                  d="M12 4v16m8-8H4"
                />
              </svg>
              1. Source
            </div>
            <span className="text-slate-600 text-xs">/</span>
            <div
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${phase === "polling" ? "bg-sky-500 text-white shadow-sm" : "text-slate-400 hover:text-slate-200"}`}
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
                  d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"
                />
              </svg>
              2. Processing
            </div>
            <span className="text-slate-600 text-xs">/</span>
            <div
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${phase === "view" ? "bg-sky-500 text-white shadow-sm" : "text-slate-400 hover:text-slate-200"}`}
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
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
              3. Document Sheet
            </div>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 py-8 w-full flex flex-col">
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 text-red-700 rounded-xl shadow-sm flex items-center justify-between animate-slide-down">
            <div className="flex items-center gap-3">
              <svg
                className="w-5 h-5 text-red-500 shrink-0"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              <span className="text-sm font-medium">{error}</span>
            </div>
            <button
              onClick={() => setError("")}
              className="text-xs font-semibold uppercase tracking-wider text-red-600 hover:text-red-800 transition"
            >
              Dismiss
            </button>
          </div>
        )}

        {phase === "submit" && (
          <div className="animate-slide-down max-w-3xl mx-auto w-full my-auto">
            <div className="text-center mb-8">
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-sky-100 text-sky-800 border border-sky-200 mb-3">
                <span className="w-2 h-2 rounded-full bg-sky-500 animate-ping" />
                Folder Repository Indexing
              </span>
              <h2 className="text-3xl font-bold text-slate-900 tracking-tight mb-2">
                Generate Technical Documentation
              </h2>
              <p className="text-slate-500 text-sm max-w-lg mx-auto">
                Provide a public GitHub repository link. DocAgent will extract
                structural context and organize standard documentation into
                folder tabs.
              </p>
            </div>
            <SubmitForm onSubmit={handleSubmit} loading={submitting} />
          </div>
        )}

        {phase === "polling" && (
          <div className="max-w-md mx-auto my-auto text-center py-12 px-6 bg-white border border-slate-200/80 rounded-2xl shadow-document relative overflow-hidden animate-slide-down">
            <div className="absolute inset-0 bg-gradient-to-b from-sky-50/50 to-transparent pointer-events-none" />
            <div className="relative z-10">
              <div className="w-16 h-16 bg-sky-100/80 text-sky-600 rounded-2xl flex items-center justify-center mx-auto mb-6 shadow-inner animate-pulse-glow">
                <svg
                  className="w-8 h-8 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="2"
                    d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                  />
                </svg>
              </div>
              <h2 className="text-xl font-bold text-slate-800 mb-1">
                {statusLabel[status] || status}
              </h2>
              <p className="text-slate-400 text-xs font-mono mb-6">
                Process Run ID: #{runId}
              </p>

              {/* Animated Progress Bar */}
              <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden border border-slate-200/60 mb-2">
                <div className="bg-gradient-to-r from-sky-500 to-indigo-500 h-full w-2/3 animate-pulse rounded-full" />
              </div>
              <p className="text-xs text-slate-400">
                Parsing code structure and formatting document sheets...
              </p>
            </div>
          </div>
        )}

        {phase === "view" && runId && (
          <div className="flex flex-col lg:flex-row gap-6 h-[calc(100vh-140px)] animate-document-unfold">
            {cacheHit && (
              <div className="absolute top-20 left-1/2 -translate-x-1/2 z-20 px-4 py-1.5 bg-amber-50 border border-amber-200 text-amber-800 rounded-full text-xs font-medium shadow-md flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-amber-500" />
                Retrieved from cache index
              </div>
            )}

            {/* Left: Interactive Paper Document Viewer */}
            <div className="flex-1 overflow-y-auto pr-1">
              <DocumentViewer
                content={document}
                onSave={handleSave}
                onDownload={handleDownload}
                onNewDoc={handleNewDoc}
                saving={saving}
              />
            </div>

            {/* Right: Modern Floating Assistant Sidebar */}
            <div className="w-full lg:w-96 shrink-0 h-full">
              <ChatPanel
                runId={runId}
                onDocumentUpdate={(doc) => setDocument(doc)}
              />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
