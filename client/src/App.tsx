import { useCallback, useEffect, useRef, useState } from 'react';
import { getRun, submitGeneration } from './lib/api';
import SubmitForm from './components/SubmitForm';
import DocumentViewer from './components/DocumentViewer';
import ChatPanel from './components/ChatPanel';
import html2canvas from 'html2canvas';
import jsPDF from 'jspdf';

type Phase = 'submit' | 'polling' | 'view';

export default function App() {
  const [phase, setPhase] = useState<Phase>('submit');
  const [runId, setRunId] = useState<number | null>(null);
  const [status, setStatus] = useState('');
  const [document, setDocument] = useState('');
  const [error, setError] = useState('');
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

  const handleSubmit = async (url: string, docType: 'api' | 'architecture', branch: string) => {
    setSubmitting(true);
    setError('');
    try {
      const res = await submitGeneration({ repo_url: url, doc_type: docType, branch: branch || null });
      setRunId(res.run_id);
      setStatus(res.status);

      // Cache hit — skip polling, go straight to viewing
      const terminal = ['approved', 'needs_revision', 'needs_human_review', 'error'];
      if (terminal.includes(res.status)) {
        setCacheHit(res.cached);
        try {
          const run = await getRun(res.run_id);
          if (run.output) {
            setDocument(run.output);
            setPhase('view');
          } else {
            setPhase('polling');
            startPolling(res.run_id);
          }
        } catch {
          setPhase('polling');
          startPolling(res.run_id);
        }
      } else {
        setPhase('polling');
        startPolling(res.run_id);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Submission failed');
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
        const terminal = ['approved', 'needs_revision', 'needs_human_review', 'error'];
        if (terminal.includes(run.status)) {
          stopPolling();
          if (run.output) {
            setDocument(run.output);
            setPhase('view');
          } else if (run.status === 'error') {
            setError(run.eval_report && 'error' in run.eval_report ? String(run.eval_report.error) : 'Generation failed');
          }
        }
      } catch {
        stopPolling();
        setError('Lost connection to server');
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
    const el = document.getElementById('document-content');
    if (!el) return;

    const canvas = await html2canvas(el, { scale: 2, useCORS: true });
    const imgData = canvas.toDataURL('image/png');
    const pdf = new jsPDF('p', 'mm', 'a4');
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const imgWidth = pageWidth - 20;
    const imgHeight = (canvas.height * imgWidth) / canvas.width;

    if (imgHeight <= pageHeight - 20) {
      pdf.addImage(imgData, 'PNG', 10, 10, imgWidth, imgHeight);
    } else {
      let remaining = imgHeight;
      let srcY = 0;
      while (remaining > 0) {
        const sliceH = Math.min(remaining, pageHeight - 20);
        const sliceRatio = sliceH / imgHeight;
        const sliceCanvas = document.createElement('canvas');
        sliceCanvas.width = canvas.width;
        sliceCanvas.height = canvas.height * sliceRatio;
        const ctx = sliceCanvas.getContext('2d')!;
        ctx.drawImage(canvas, 0, srcY, canvas.width, canvas.height * sliceRatio, 0, 0, canvas.width, canvas.height * sliceRatio);
        pdf.addImage(sliceCanvas.toDataURL('image/png'), 'PNG', 10, 10, imgWidth, sliceH);
        remaining -= sliceH;
        srcY += canvas.height * sliceRatio;
        if (remaining > 0) pdf.addPage();
      }
    }

    pdf.save('documentation.pdf');
  };

  const handleNewDoc = () => {
    setPhase('submit');
    setRunId(null);
    setDocument('');
    setStatus('');
    setError('');
  };

  const statusLabel: Record<string, string> = {
    queued: 'Queued',
    cloning: 'Cloning repository',
    parsing: 'Parsing files',
    embedding: 'Building embeddings',
    generating: 'Generating draft',
    evaluating: 'Evaluating quality',
    needs_revision: 'Revision needed',
    approved: 'Complete',
    needs_human_review: 'Needs human review',
    error: 'Error',
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <header className="bg-white border-b border-slate-200 shrink-0">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center text-white font-bold text-sm">D</div>
          <h1 className="text-lg font-semibold text-slate-800">DocAgent</h1>
        </div>
      </header>

      <main className="flex-1 max-w-7xl mx-auto px-6 py-10 w-full">
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 text-red-700 rounded-lg">
            {error}
            <button onClick={() => setError('')} className="ml-2 underline cursor-pointer">dismiss</button>
          </div>
        )}

        {phase === 'submit' && (
          <div className="text-center mb-10">
            <h2 className="text-3xl font-bold text-slate-900 mb-3">
              Generate documentation from any GitHub repo
            </h2>
            <p className="text-slate-500 mb-8">
              Paste a public repository URL. The AI will analyze the codebase and produce editable documentation.
            </p>
            <SubmitForm onSubmit={handleSubmit} loading={submitting} />
          </div>
        )}

        {phase === 'polling' && (
          <div className="max-w-md mx-auto text-center py-20">
            <div className="mb-6">
              <svg className="animate-spin h-12 w-12 text-blue-600 mx-auto" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-slate-800 mb-2">
              {statusLabel[status] || status}
            </h2>
            <p className="text-slate-500 text-sm">
              Run #{runId} — This may take a few minutes.
            </p>
          </div>
        )}

        {phase === 'view' && runId && (
          <div className="flex gap-6 h-[calc(100vh-120px)]">
            {cacheHit && (
              <div className="absolute top-20 left-1/2 -translate-x-1/2 z-10 px-4 py-2 bg-amber-50 border border-amber-200 text-amber-700 rounded-lg text-sm shadow-sm">
                Loaded from cache — previously generated document
              </div>
            )}
            <div className="flex-1 overflow-y-auto">
              <DocumentViewer
                content={document}
                onSave={handleSave}
                onDownload={handleDownload}
                onNewDoc={handleNewDoc}
                saving={saving}
              />
            </div>
            <div className="w-96 shrink-0">
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
