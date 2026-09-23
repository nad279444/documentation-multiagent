import { useCallback, useEffect, useRef, useState } from "react";
import { getRun, submitGeneration } from "./lib/api";
import { clearToken, getCurrentUser, getToken } from "./lib/auth";
import SubmitForm from "./components/SubmitForm";
import DocumentViewer from "./components/DocumentViewer";
import ChatPanel from "./components/ChatPanel";
import GoogleSignIn from "./components/GoogleSignIn";
import heroImage from "./assets/hero.png";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";

type DocType = "api" | "architecture";

interface DocRun {
  docType: DocType;
  runId: number;
  status: string;
  document: string;
  cacheHit: boolean;
}

type Phase = "login" | "submit" | "polling" | "view";

const TERMINAL_STATUSES = [
  "approved",
  "needs_revision",
  "needs_human_review",
  "error",
];

export default function App() {
  const [phase, setPhase] = useState<Phase>("login");
  const [user, setUser] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [runs, setRuns] = useState<DocRun[]>([]);
  const [activeDoc, setActiveDoc] = useState<DocType>("api");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
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

  // Check if already logged in on mount
  useEffect(() => {
    const checkAuth = async () => {
      const token = getToken();
      if (token) {
        try {
          const userInfo = await getCurrentUser();
          setUser(userInfo);
          setPhase("submit");
        } catch (_e) {
          // Token invalid or expired
          clearToken();
          setPhase("login");
        }
      }
      setLoading(false);
    };

    checkAuth();
  }, []);

  const handleLoginSuccess = (userInfo: any) => {
    setUser(userInfo);
    setPhase("submit");
  };

  const handleLogout = () => {
    clearToken();
    stopPolling();
    setUser(null);
    setPhase("login");
  };

  const handleSubmit = async (
    url: string,
    docTypes: DocType[],
    branch: string,
  ) => {
    setSubmitting(true);
    setError("");
    try {
      const results = await Promise.all(
        docTypes.map(async (docType) => {
          const res = await submitGeneration({
            repo_url: url,
            doc_type: docType,
            branch: branch || null,
          });
          // Cache hits return a completed run immediately.
          let document = "";
          if (res.cached) {
            try {
              const run = await getRun(res.run_id);
              if (run.output) document = run.output;
            } catch {
              /* ignore, polling will surface it */
            }
          }
          return {
            docType,
            runId: res.run_id,
            status: res.status,
            document,
            cacheHit: res.cached,
          } satisfies DocRun;
        }),
      );

      setRuns(results);
      setActiveDoc(docTypes[0]);

      if (results.some((r) => r.status === "queued")) {
        setPhase("polling");
        startPolling();
      } else {
        refreshFinished(results);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  const refreshFinished = async (current: DocRun[]) => {
    const terminal = TERMINAL_STATUSES;
    const refreshed = await Promise.all(
      current.map(async (r) => {
        if (terminal.includes(r.status) && r.document) return r;
        try {
          const run = await getRun(r.runId);
          return {
            ...r,
            status: run.status,
            document: run.output ?? r.document,
          };
        } catch {
          return r;
        }
      }),
    );
    setRuns(refreshed);
    const done = refreshed.every((r) => terminal.includes(r.status));
    const hasAnyDocs = refreshed.some((r) => r.document);
    if (done) {
      stopPolling();
      setPhase(hasAnyDocs ? "view" : "submit");
      if (!hasAnyDocs) setError("Generation completed without any output");
    }
  };

  const startPolling = () => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const current = runsRef.current;
        const terminal = TERMINAL_STATUSES;
        const updated = await Promise.all(
          current.map(async (r) => {
            if (terminal.includes(r.status) && r.document) return r;
            const run = await getRun(r.runId);
            setStatus(run.status);
            if (run.status === "error" && !run.output) {
              setError(
                run.eval_report && "error" in run.eval_report
                  ? String(run.eval_report.error)
                  : "Generation failed",
              );
            }
            return {
              ...r,
              status: run.status,
              document: run.output ?? r.document,
            };
          }),
        );
        setRuns(updated);
        const done = updated.every((r) => terminal.includes(r.status));
        if (done) {
          stopPolling();
          const hasAnyDocs = updated.some((r) => r.document);
          setPhase(hasAnyDocs ? "view" : "submit");
          if (!hasAnyDocs) setError("Generation completed without any output");
        }
      } catch {
        stopPolling();
        setError("Lost connection to server");
      }
    }, 2000);
  };

  const runsRef = useRef(runs);
  runsRef.current = runs;

  const handleSave = async (edited: string) => {
    setSaving(true);
    try {
      setRuns((prev) =>
        prev.map((r) =>
          r.docType === activeDoc
            ? { ...r, document: edited }
            : r,
        ),
      );
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
    setRuns([]);
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

  const activeRun = runs.find((r) => r.docType === activeDoc);

  if (loading) {
    return <div className="p-4">Loading...</div>;
  }

  if (phase === "login") {
    return (
      <div className="min-h-screen overflow-hidden bg-[#eef5f8] text-slate-900 relative">
        <div className="login-background-grid" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(14,165,233,0.22),transparent_30%),radial-gradient(circle_at_80%_10%,rgba(124,58,237,0.16),transparent_28%),linear-gradient(135deg,rgba(255,255,255,0.92),rgba(226,232,240,0.72))]" />

        <main className="relative z-10 min-h-screen max-w-6xl mx-auto px-6 py-8 flex items-center">
          <div className="grid lg:grid-cols-[1.05fr_0.95fr] gap-10 items-center w-full">
            <section className="min-h-[520px] flex flex-col justify-between">
              <div className="inline-flex items-center gap-3 text-sm font-semibold text-slate-700">
                <span className="w-10 h-10 rounded-xl bg-slate-900 text-white flex items-center justify-center shadow-lg shadow-slate-900/15">
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
                </span>
                Documentation Agent
              </div>

              <div className="max-w-xl py-10">
                <p className="text-xs font-bold uppercase tracking-[0.22em] text-sky-700 mb-4">
                  Repository to client-ready documentation
                </p>
                <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-slate-950 leading-tight">
                  Turn codebases into polished technical documents.
                </h1>
                <p className="mt-5 text-base sm:text-lg leading-8 text-slate-600 max-w-lg">
                  Sign in to generate API references, architecture briefs, and review-ready documentation from a GitHub repository.
                </p>
              </div>

              <div className="grid grid-cols-3 gap-3 max-w-lg text-xs sm:text-sm">
                <div className="rounded-xl border border-white/70 bg-white/60 px-3 py-3 shadow-sm backdrop-blur">
                  <p className="font-bold text-slate-900">1. Source</p>
                  <p className="mt-1 text-slate-500">Paste a GitHub repo</p>
                </div>
                <div className="rounded-xl border border-white/70 bg-white/60 px-3 py-3 shadow-sm backdrop-blur">
                  <p className="font-bold text-slate-900">2. Select</p>
                  <p className="mt-1 text-slate-500">Pick doc outputs</p>
                </div>
                <div className="rounded-xl border border-white/70 bg-white/60 px-3 py-3 shadow-sm backdrop-blur">
                  <p className="font-bold text-slate-900">3. Deliver</p>
                  <p className="mt-1 text-slate-500">Review and export</p>
                </div>
              </div>
            </section>

            <section className="relative min-h-[560px] flex items-center justify-center">
              <div className="absolute inset-x-8 top-8 bottom-8 rounded-[2rem] bg-white/45 border border-white/80 shadow-2xl shadow-slate-900/10 backdrop-blur-xl" />
              <div className="document-handoff-scene" aria-hidden="true">
                <img
                  src={heroImage}
                  alt=""
                  className="handoff-backdrop"
                />
                <div className="person person-left">
                  <span className="person-head" />
                  <span className="person-body" />
                  <span className="person-arm arm-left" />
                </div>
                <div className="person person-right">
                  <span className="person-head" />
                  <span className="person-body" />
                  <span className="person-arm arm-right" />
                </div>
                <div className="handoff-document">
                  <span />
                  <span />
                  <span />
                </div>
                <div className="handoff-shadow" />
              </div>

              <div className="relative z-10 self-end w-full max-w-sm mb-10 bg-white rounded-2xl border border-slate-200/80 shadow-2xl shadow-slate-900/10 p-7">
                <div className="mb-6 text-center">
                  <h2 className="text-2xl font-bold tracking-tight text-slate-950">
                    Welcome back
                  </h2>
                  <p className="mt-2 text-sm leading-6 text-slate-500">
                    Continue with Google to open your documentation workspace.
                  </p>
                </div>
                {error && (
                  <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
                    {error}
                  </div>
                )}
                <GoogleSignIn
                  onSuccess={handleLoginSuccess}
                  onError={(err) => setError(err)}
                />
              </div>
            </section>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="app-gradient-shell min-h-screen flex flex-col font-sans text-slate-800 antialiased selection:bg-sky-100 selection:text-sky-900">
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
                Documentation Agent{" "}
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
          <div className="flex items-center gap-4">
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

            {user && (
              <div className="flex items-center gap-3">
                {user.picture && (
                  <img
                    src={user.picture}
                    alt={user.name}
                    className="w-9 h-9 rounded-full border border-slate-700"
                  />
                )}
                <div className="hidden md:block">
                  <p className="text-sm font-medium text-slate-100">
                    {user.name}
                  </p>
                  <p className="text-xs text-slate-400">{user.email}</p>
                </div>
                <button
                  onClick={handleLogout}
                  className="px-3 py-1.5 bg-red-600 text-white text-xs font-medium rounded-lg hover:bg-red-700 transition"
                >
                  Sign Out
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl mx-auto px-2 sm:px-3 py-2 w-full flex flex-col">
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
                <span className="w-2 h-2 rounded-full bg-sky-500" />
                Folder Repository Indexing
              </span>
              <h2 className="text-3xl font-bold text-slate-900 tracking-tight mb-2">
                Generate Technical Documentation
              </h2>
              <p className="text-slate-500 text-sm max-w-lg mx-auto">
                Provide a public GitHub repository link. Documentation Agent will extract
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
              <div className="w-16 h-16 bg-sky-100/80 text-sky-600 rounded-2xl flex items-center justify-center mx-auto mb-6 shadow-inner">
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
                {runs
                  .map(
                    (r) =>
                      `#${r.runId} ${r.docType === "api" ? "API" : "Arch"}`,
                  )
                  .join(" / ") || "Starting..."}
              </p>

              {/* Animated Progress Bar */}
              <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden border border-slate-200/60 mb-2">
                <div className="bg-gradient-to-r from-sky-500 to-indigo-500 h-full w-2/3 rounded-full" />
              </div>
              <p className="text-xs text-slate-400">
                Parsing code structure and formatting document sheets...
              </p>
            </div>
          </div>
        )}

        {phase === "view" &&
        activeRun &&
        (() => {
          const activeRunRun = activeRun;
          const docTitle =
            activeRunRun.docType === "api" ? "API Reference" : "Architecture";
          const docSubtitle =
            activeRunRun.docType === "api"
              ? "Endpoints, payloads, and integration details"
              : "System structure, modules, and data flow";
          return (
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_24rem] gap-3 h-[calc(100vh-40px)] animate-document-unfold">
              <section className="min-w-0 flex flex-col gap-3 overflow-hidden">
                <div className="bg-white border border-slate-200/80 rounded-2xl shadow-document px-4 py-3 sm:px-5">
                  <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                    <div className="min-w-0">
                      <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-400">
                        Generated Document
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <h2 className="text-lg font-bold text-slate-950">
                          {docTitle}
                        </h2>
                        {activeRunRun.cacheHit && (
                          <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">
                            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                            Cache
                          </span>
                        )}
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                          Ready
                        </span>
                      </div>
                      <p className="mt-1 text-sm text-slate-500">
                        {docSubtitle}
                      </p>
                    </div>

                    {runs.length > 1 && (
                      <div className="grid grid-cols-2 gap-2 rounded-xl border border-slate-200 bg-slate-50 p-1 min-w-full sm:min-w-[24rem] xl:min-w-[27rem]">
                        {runs.map((r) => {
                          const selected = activeDoc === r.docType;
                          const title =
                            r.docType === "api" ? "API Reference" : "Architecture";
                          const shortTitle = r.docType === "api" ? "API" : "Architecture";
                          return (
                            <button
                              key={r.docType}
                              type="button"
                              onClick={() => setActiveDoc(r.docType)}
                              className={`min-h-16 rounded-lg px-3 py-2 text-left transition-all cursor-pointer border focus:outline-none focus:ring-2 focus:ring-sky-500/30 ${
                                selected
                                  ? "bg-white border-sky-200 shadow-sm text-slate-950"
                                  : "border-transparent text-slate-500 hover:bg-white/70 hover:text-slate-800"
                              }`}
                            >
                              <span className="flex items-center justify-between gap-2">
                                <span className="flex items-center gap-2 min-w-0">
                                  <span
                                    className={`h-8 w-8 shrink-0 rounded-lg flex items-center justify-center ${
                                      r.docType === "api"
                                        ? "bg-sky-100 text-sky-700"
                                        : "bg-violet-100 text-violet-700"
                                    }`}
                                  >
                                    {r.docType === "api" ? (
                                      <svg
                                        className="h-4 w-4"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                      >
                                        <path
                                          strokeLinecap="round"
                                          strokeLinejoin="round"
                                          strokeWidth="2"
                                          d="M8 9l3 3-3 3m5 0h3M5 5h14a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2z"
                                        />
                                      </svg>
                                    ) : (
                                      <svg
                                        className="h-4 w-4"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                      >
                                        <path
                                          strokeLinecap="round"
                                          strokeLinejoin="round"
                                          strokeWidth="2"
                                          d="M4 7h6v6H4V7zm10 0h6v6h-6V7zM4 17h6m4 0h6M10 10h4"
                                        />
                                      </svg>
                                    )}
                                  </span>
                                  <span className="min-w-0">
                                    <span className="block truncate text-sm font-bold">
                                      {title}
                                    </span>
                                    <span className="block truncate text-xs text-slate-400">
                                      Run #{r.runId}
                                    </span>
                                  </span>
                                </span>
                                {r.document && (
                                  <span
                                    className={`hidden sm:inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${
                                      selected
                                        ? "bg-emerald-50 text-emerald-700"
                                        : "bg-slate-100 text-slate-500"
                                    }`}
                                  >
                                    Ready
                                  </span>
                                )}
                              </span>
                              <span className="mt-1 block text-xs font-medium text-slate-400 sm:hidden">
                                {shortTitle} document
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                  <DocumentViewer
                    content={activeRunRun.document}
                    onSave={handleSave}
                    onDownload={handleDownload}
                    onNewDoc={handleNewDoc}
                    saving={saving}
                  />
                </div>
              </section>

              <aside className="w-full min-h-0 shrink-0 lg:h-full">
                <ChatPanel
                  runId={activeRunRun.runId}
                  onDocumentUpdate={(doc) =>
                    setRuns((prev) =>
                      prev.map((r) =>
                        r.docType === activeDoc ? { ...r, document: doc } : r,
                      ),
                    )
                  }
                />
              </aside>
            </div>
          );
        })()}
      </main>
    </div>
  );
}
