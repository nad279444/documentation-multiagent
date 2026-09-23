import { useState } from "react";

type DocType = "api" | "architecture";

interface Props {
  onSubmit: (
    url: string,
    docTypes: DocType[],
    branch: string,
  ) => void;
  loading: boolean;
}

const GITHUB_URL_RE = /^https?:\/\/(www\.)?github\.com\/[^/]+\/[^/]+\/?$/;

const DOCUMENT_OPTIONS: Array<{
  id: DocType;
  title: string;
  description: string;
  detail: string;
  accent: string;
}> = [
  {
    id: "api",
    title: "API Reference",
    description: "Endpoints, inputs, responses, and integration notes.",
    detail: "Best for SDK users and backend teams",
    accent: "from-sky-500 to-cyan-500",
  },
  {
    id: "architecture",
    title: "Architecture",
    description: "System shape, modules, data flow, and design decisions.",
    detail: "Best for onboarding and technical reviews",
    accent: "from-violet-500 to-slate-700",
  },
];

export default function SubmitForm({ onSubmit, loading }: Props) {
  const [url, setUrl] = useState("");
  const [docTypes, setDocTypes] = useState<DocType[]>(["api"]);
  const [branch, setBranch] = useState("");
  const [urlError, setUrlError] = useState("");

  const toggleDocType = (t: DocType) => {
    setDocTypes((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t],
    );
  };

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
    if (url.trim() && !urlError && docTypes.length > 0)
      onSubmit(url.trim(), docTypes, branch.trim());
  };

  const selectedLabel =
    docTypes.length === 2
      ? "Create a complete documentation bundle"
      : docTypes.length === 1
        ? `Create ${DOCUMENT_OPTIONS.find((o) => o.id === docTypes[0])?.title}`
        : "Choose at least one document";

  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 shadow-document p-6 sm:p-8 relative">
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

        <div>
          <label className="block text-xs font-bold uppercase tracking-wider text-slate-600 mb-2">
            Documentation Output{" "}
            <span className="text-slate-400 font-normal">
              (choose one or both)
            </span>
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {DOCUMENT_OPTIONS.map((option) => {
              const selected = docTypes.includes(option.id);
              return (
                <button
                  key={option.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => toggleDocType(option.id)}
                  className={`group min-h-36 text-left rounded-xl border p-4 transition-all duration-200 cursor-pointer focus:outline-none focus:ring-2 focus:ring-sky-500/30 ${
                    selected
                      ? "bg-white border-sky-300 shadow-document ring-1 ring-sky-200"
                      : "bg-slate-50/70 border-slate-200 hover:bg-white hover:border-slate-300 hover:shadow-sm"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <span
                      className={`w-10 h-10 rounded-lg bg-gradient-to-br ${option.accent} text-white flex items-center justify-center shadow-sm`}
                    >
                      {option.id === "api" ? (
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
                            d="M8 9l3 3-3 3m5 0h3M5 5h14a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2z"
                          />
                        </svg>
                      ) : (
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
                            d="M4 7h6v6H4V7zm10 0h6v6h-6V7zM4 17h6m4 0h6M10 10h4"
                          />
                        </svg>
                      )}
                    </span>
                    <span
                      className={`w-6 h-6 rounded-full border flex items-center justify-center transition-all ${
                        selected
                          ? "bg-sky-600 border-sky-600 text-white"
                          : "bg-white border-slate-300 text-transparent group-hover:border-slate-400"
                      }`}
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
                          strokeWidth="3"
                          d="M5 13l4 4L19 7"
                        />
                      </svg>
                    </span>
                  </div>
                  <div className="mt-4">
                    <h3 className="text-sm font-bold text-slate-900">
                      {option.title}
                    </h3>
                    <p className="mt-1 text-sm leading-5 text-slate-600">
                      {option.description}
                    </p>
                    <p className="mt-3 text-xs font-medium text-slate-400">
                      {option.detail}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>
          {docTypes.length === 0 && (
            <p className="mt-1.5 text-xs text-red-600 font-medium">
              Select at least one document type
            </p>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Generation Queue
            </p>
            <p className="text-sm font-medium text-slate-800">
              {selectedLabel}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {DOCUMENT_OPTIONS.map((option) => (
              <span
                key={option.id}
                className={`px-2.5 py-1 rounded-full text-xs font-semibold border ${
                  docTypes.includes(option.id)
                    ? "bg-sky-50 text-sky-700 border-sky-200"
                    : "bg-white text-slate-400 border-slate-200"
                }`}
              >
                {option.title}
              </span>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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

          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
            <p className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Flow
            </p>
            <div className="mt-2 flex items-center gap-2 text-xs font-medium text-slate-500">
              <span className="text-slate-900">Repository</span>
              <span className="h-px flex-1 bg-slate-200" />
              <span className="text-slate-900">Docs</span>
              <span className="h-px flex-1 bg-slate-200" />
              <span className="text-slate-900">Review</span>
            </div>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading || !url.trim() || docTypes.length === 0}
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
