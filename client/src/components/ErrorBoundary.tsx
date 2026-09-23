import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("ErrorBoundary caught:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen bg-slate-100 flex items-center justify-center p-6">
          <div className="bg-white rounded-lg shadow-lg p-8 max-w-lg w-full border border-red-200">
            <h1 className="text-xl font-bold text-red-700 mb-3">
              Something went wrong
            </h1>
            <pre className="text-sm bg-red-50 border border-red-200 text-red-800 p-4 rounded-lg overflow-x-auto whitespace-pre-wrap break-words max-h-96 overflow-y-auto">
              {this.state.error.message || String(this.state.error)}
            </pre>
            <button
              onClick={() => this.setState({ error: null })}
              className="mt-4 px-4 py-2 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-700 transition"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}