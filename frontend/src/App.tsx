import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { ScopeProvider } from "./lib/scope";
import { Overview } from "./features/overview/Overview";
import { MemoryExplorer } from "./features/explorer/MemoryExplorer";
import { Projects } from "./features/scope/Projects";
import { Agents } from "./features/scope/Agents";
import { StatusPage } from "./features/system/StatusPage";
import { ContextSelectionProvider } from "./lib/contextSelection";
import { LoadingState } from "./components/ui/States";

const MemoryGraph = lazy(() => import("./features/graph/MemoryGraph").then((module) => ({ default: module.MemoryGraph })));
const ContextPreview = lazy(() => import("./features/context/ContextPreview").then((module) => ({ default: module.ContextPreview })));
const Timeline = lazy(() => import("./features/temporal/Timeline").then((module) => ({ default: module.Timeline })));
const ConflictCenter = lazy(() => import("./features/temporal/ConflictCenter").then((module) => ({ default: module.ConflictCenter })));

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/overview" replace />} />
      <Route path="/overview" element={<Overview />} />
      <Route path="/graph" element={<MemoryGraph />} />
      <Route path="/memories" element={<MemoryExplorer />} />
      <Route path="/projects" element={<Projects />} />
      <Route path="/agents" element={<Agents />} />
      <Route path="/status" element={<StatusPage />} />
      <Route path="/context" element={<ContextPreview />} />
      <Route path="/timeline" element={<Timeline />} />
      <Route path="/conflicts" element={<ConflictCenter />} />
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
