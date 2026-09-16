import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface Props {
  content: string;
  onSave: (edited: string) => void;
  onDownload: () => void;
  onNewDoc: () => void;
  saving: boolean;
}

export default function DocumentViewer({ content, onSave, onDownload, onNewDoc, saving }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(content);

  const handleSave = () => {
    onSave(draft);
    setEditing(false);
  };

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold text-slate-800">Generated Document</h2>
        <div className="flex gap-2">
          <button
            onClick={() => { setDraft(content); setEditing(!editing); }}
            className="px-4 py-2 text-sm border border-slate-300 rounded-lg hover:bg-slate-50 transition cursor-pointer"
          >
            {editing ? 'Cancel Edit' : 'Edit'}
          </button>
          {editing && (
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 transition cursor-pointer"
            >
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          )}
          <button
            onClick={onDownload}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition cursor-pointer"
          >
            Download PDF
          </button>
          <button
            onClick={onNewDoc}
            className="px-4 py-2 text-sm border border-slate-300 rounded-lg hover:bg-slate-50 transition cursor-pointer"
          >
            New Document
          </button>
        </div>
      </div>

      <div className="border border-slate-200 rounded-xl overflow-hidden bg-white shadow-sm">
        {editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full min-h-[600px] p-6 font-mono text-sm leading-relaxed resize-y focus:outline-none"
          />
        ) : (
          <article id="document-content" className="markdown-body p-8 prose prose-slate max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </article>
        )}
      </div>
    </div>
  );
}
