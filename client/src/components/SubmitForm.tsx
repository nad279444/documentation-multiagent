import { useState } from 'react';

interface Props {
  onSubmit: (url: string, docType: 'api' | 'architecture', branch: string) => void;
  loading: boolean;
}

const GITHUB_URL_RE = /^https?:\/\/(www\.)?github\.com\/[^/]+\/[^/]+\/?$/;

export default function SubmitForm({ onSubmit, loading }: Props) {
  const [url, setUrl] = useState('');
  const [docType, setDocType] = useState<'api' | 'architecture'>('api');
  const [branch, setBranch] = useState('');
  const [urlError, setUrlError] = useState('');

  const validateUrl = (val: string) => {
    setUrl(val);
    if (!val.trim()) {
      setUrlError('');
    } else if (!GITHUB_URL_RE.test(val.trim())) {
      setUrlError('Must be a valid GitHub URL (e.g. https://github.com/owner/repo)');
    } else {
      setUrlError('');
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (url.trim() && !urlError) onSubmit(url.trim(), docType, branch.trim());
  };

  return (
    <form onSubmit={handleSubmit} className="max-w-2xl mx-auto space-y-6">
      <div>
        <label className="block text-sm font-medium text-slate-700 mb-1">
          GitHub Repository URL
        </label>
        <input
          type="url"
          required
          placeholder="https://github.com/owner/repo"
          value={url}
          onChange={(e) => validateUrl(e.target.value)}
          className={`w-full px-4 py-2.5 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition ${
            urlError ? 'border-red-300 bg-red-50' : 'border-slate-300'
          }`}
        />
        {urlError && <p className="mt-1 text-sm text-red-600">{urlError}</p>}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Documentation Type
          </label>
          <select
            value={docType}
            onChange={(e) => setDocType(e.target.value as 'api' | 'architecture')}
            className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition bg-white"
          >
            <option value="api">API Reference</option>
            <option value="architecture">Architecture</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Branch <span className="text-slate-400">(optional)</span>
          </label>
          <input
            type="text"
            placeholder="main"
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
          />
        </div>
      </div>

      <button
        type="submit"
        disabled={loading || !url.trim()}
        className="w-full py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition cursor-pointer"
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Generating...
          </span>
        ) : (
          'Generate Documentation'
        )}
      </button>
    </form>
  );
}
