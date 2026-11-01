import { Component, lazy, Suspense, type ErrorInfo, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Shell from "./components/Shell.tsx";
import HomePage from "./pages/HomePage.tsx";

const AgentsPage = lazy(() => import("./pages/AgentsPage.tsx"));
const EndpointPage = lazy(() => import("./pages/EndpointPage.tsx"));
const ExecutionPage = lazy(() => import("./pages/ExecutionPage.tsx"));
const HistoryPage = lazy(() => import("./pages/HistoryPage.tsx"));

class RouteErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Route failed to render", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="page">
          <div className="notice error">
            <div>{this.state.error.message}</div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <Shell>
      <RouteErrorBoundary>
        <Suspense fallback={<div className="page"><h2>Loading page…</h2></div>}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/execution" element={<ExecutionPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/hardware" element={<EndpointPage key="devices" kind="devices" />} />
            <Route path="/tools" element={<EndpointPage key="tools" kind="tools" />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </RouteErrorBoundary>
    </Shell>
  );
}
