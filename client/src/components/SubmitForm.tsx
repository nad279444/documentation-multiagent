import { useState } from "react";

interface Props {
  onSubmit: (
    url: string,
    docType: "api" | "architecture",
    branch: string,
  ) => void;
  loading: boolean;
}

const GITHUB_URL_RE = /^https?:\/\/(www\.)?github\.com\/[^/]+\/[^/]+\/?$/;

export default function SubmitForm({ onSubmit, loading }: Props) {
  const [url, setUrl] = useState("");
  const [docType, setDocType] = useState<"api" | "architecture">("api");
  const [branch, setBranch] = useState("");
  const [urlError, setUrlError] = useState("");

  const validateUrl = (val: string) => {
    setUrl(val);
    if (!val.trim()) {
      setUrlError("");
    } else if (!GITHUB_URL_RE.test(val.trim())) {
      setUrlError(
        "Must be a valid GitHub URL (e.g. https://github.com/owner/repo)",
      );
    } else {
      setUrlError("");
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (url.trim() && !urlError) onSubmit(url.trim(), docType, branch.trim());
  };

  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 shadow-document p-6 sm:p-8 relative">
      {/* Folder Tab Header Accent */}
      <div className="absolute -top-3.5 left-6 px-4 py-1 bg-slate-800 text-slate-200 text-xs font-semibold rounded-t-lg shadow-folder-tab border-t border-x border-slate-700 flex items-center gap-2">
        <svg
          className="w-3.5 h-3.5 text-sky-400"
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
        New Document Request
      </div>

      <form onSubmit={handleSubmit} className="space-y-6 mt-2">
        <div>
          <label className="block text-xs font-bold uppercase tracking-wider text-slate-600 mb-2">
            Repository URL
          </label>
          <div className="relative">
            <input
              type="url"
              required
              placeholder="https://github.com/owner/repo"
              value={url}
              onChange={(e) => validateUrl(e.target.value)}
              className={`w-full pl-10 pr-4 py-3 bg-slate-50/50 border rounded-xl text-sm focus:bg-white focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 outline-none transition-all ${
                urlError
                  ? "border-red-300 bg-red-50/30 text-red-900"
                  : "border-slate-300/80"
              }`}
            />
            <svg
              className="w-5 h-5 text-slate-400 absolute left-3 top-3.5 pointer-events-none"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"
              />
            </svg>
          </div>
          {urlError && (
            <p className="mt-1.5 text-xs text-red-600 font-medium">
              {urlError}
            </p>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-600 mb-2">
              Document Preset
            </label>
            <div className="grid grid-cols-2 gap-2 p-1 bg-slate-100 rounded-xl border border-slate-200">
              <button
                type="button"
                onClick={() => setDocType("api")}
                className={`py-2 px-3 text-xs font-semibold rounded-lg transition-all ${
                  docType === "api"
                    ? "bg-white text-sky-700 shadow-sm border border-slate-200"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                API Reference
              </button>
              <button
                type="button"
                onClick={() => setDocType("architecture")}
                className={`py-2 px-3 text-xs font-semibold rounded-lg transition-all ${
                  docType === "architecture"
                    ? "bg-white text-sky-700 shadow-sm border border-slate-200"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Architecture
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-600 mb-2">
              Branch Name{" "}
              <span className="text-slate-400 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              placeholder="main"
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              className="w-full px-4 py-2.5 bg-slate-50/50 border border-slate-300/80 rounded-xl text-sm focus:bg-white focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 outline-none transition-all"
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={loading || !url.trim()}
          className="w-full py-3.5 bg-gradient-to-r from-sky-600 to-slate-800 text-white font-semibold text-sm rounded-xl hover:from-sky-500 hover:to-slate-700 disabled:opacity-50 disabled:cursor-not-allowed shadow-md hover:shadow-lg transition-all duration-200 cursor-pointer flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <svg
                className="animate-spin h-4 w-4 text-white"
                viewBox="0 0 24 24"
                fill="none"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              <span>Creating Folder & Files...</span>
            </>
          ) : (
            <>
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
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
              <span>Generate Documentation Sheet</span>
            </>
          )}
        </button>
      </form>
    </div>
  );
}
