import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { ScopeProvider } from "./lib/scope";
import { Overview } from "./features/overview/Overview";
import { MemoryExplorer } from "./features/explorer/MemoryExplorer";
import { Projects } from "./features/scope/Projects";
import { Agents } from "./features/scope/Agents";
import { StatusPage } from "./features/system/StatusPage";
import { Observations } from "./features/observations/Observations";
import { ContextSelectionProvider } from "./lib/contextSelection";
import { LoadingState } from "./components/ui/States";
import { RouteErrorBoundary } from "./components/errors/RouteErrorBoundary";

const MemoryGraph = lazy(() => import("./features/graph/MemoryGraph").then((module) => ({ default: module.MemoryGraph })));
const ContextPreview = lazy(() => import("./features/context/ContextPreview").then((module) => ({ default: module.ContextPreview })));
const Timeline = lazy(() => import("./features/temporal/Timeline").then((module) => ({ default: module.Timeline })));
const ConflictCenter = lazy(() => import("./features/temporal/ConflictCenter").then((module) => ({ default: module.ConflictCenter })));

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/overview" replace />} />
      <Route path="/overview" element={<Overview />} />
      <Route path="/memories" element={<MemoryExplorer />} />
      <Route path="/graph" element={<RouteErrorBoundary routeLabel="memory graph"><MemoryGraph /></RouteErrorBoundary>} />
      <Route path="/context" element={<RouteErrorBoundary routeLabel="context retrieval"><ContextPreview /></RouteErrorBoundary>} />
      <Route path="/observations" element={<Observations />} />
      <Route path="/timeline" element={<RouteErrorBoundary routeLabel="temporal trace"><Timeline /></RouteErrorBoundary>} />
      <Route path="/conflicts" element={<RouteErrorBoundary routeLabel="conflict center"><ConflictCenter /></RouteErrorBoundary>} />
      <Route path="/agents" element={<Agents />} />
      <Route path="/projects" element={<Projects />} />
      <Route path="/status" element={<StatusPage />} />
      <Route path="*" element={<Navigate to="/overview" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <ScopeProvider initial="project:munin">
      <ContextSelectionProvider>
        <BrowserRouter><AppShell><Suspense fallback={<LoadingState label="LOADING OPERATIONS MODULE" />}><AppRoutes /></Suspense></AppShell></BrowserRouter>
      </ContextSelectionProvider>
    </ScopeProvider>
  );
}
