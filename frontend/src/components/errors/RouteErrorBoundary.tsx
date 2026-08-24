import { Component, type ErrorInfo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { PatternAlert } from "@mdrbx/nerv-ui";

interface Props { children: ReactNode; routeLabel?: string }
interface State { error: Error | null; retryKey: number }

export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null, retryKey: 0 };

  static getDerivedStateFromError(error: Error): Partial<State> { return { error }; }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[MUNIN] ${this.props.routeLabel ?? "route"} renderer failure`, error, info);
  }

  retry = () => this.setState(({ retryKey }) => ({ error: null, retryKey: retryKey + 1 }));

  render() {
    if (!this.state.error) return <div key={this.state.retryKey} className="contents">{this.props.children}</div>;
    return (
      <div className="flex h-full items-center justify-center bg-black p-6">
        <div className="w-full max-w-2xl border border-[var(--munin-red)] bg-black p-4">
          <PatternAlert designation="GRAPH RENDERER FAILURE" pattern="MEMORY DATA REMAINS AVAILABLE" bloodType="RED" color="red" animated={false} />
          <p className="mt-4 font-body text-base text-[var(--munin-text)]">The active visual renderer stopped. Stored memory data and backend state were not changed.</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" className="munin-btn munin-btn-danger" onClick={this.retry}>RETRY RENDERER</button>
            <Link className="munin-btn" to="/memories">OPEN MEMORY EXPLORER</Link>
          </div>
          {import.meta.env.DEV && <pre className="mt-4 max-h-28 overflow-auto border-t border-[var(--munin-border)] pt-3 font-mono text-[10px] text-[var(--munin-muted)]">{this.state.error.message}</pre>}
        </div>
      </div>
    );
  }
}
