"use client";

import { useState, useEffect, useRef } from "react";
import { CopilotChat } from "@copilotkit/react-ui";
import { useCopilotChat } from "@copilotkit/react-core";
import SessionSidebar from "./components/SessionSidebar";
import { useSessionManager } from "./hooks/useSessionManager";

export default function Home() {
  const {
    sessions,
    activeSessionId,
    loadSessions,
    switchSession,
    newChat,
    removeSession,
  } = useSessionManager();

  const { isLoading } = useCopilotChat();
  const wasLoading = useRef(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Refresh session list when a message completes
  useEffect(() => {
    if (wasLoading.current && !isLoading) {
      loadSessions();
    }
    wasLoading.current = isLoading;
  }, [isLoading, loadSessions]);

  return (
    <div className="flex h-screen bg-zinc-50 dark:bg-zinc-950">
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={(id) => {
          switchSession(id);
          setSidebarOpen(false);
        }}
        onNewChat={() => {
          newChat();
          setSidebarOpen(false);
        }}
        onDeleteSession={removeSession}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
      />

      <div className="flex flex-col flex-1 min-w-0">
        <header className="flex items-center justify-between px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white font-bold text-sm">
              AI
            </div>
            <div>
              <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
                OnCall AI Assistant
              </h1>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                K8s Diagnostics &amp; GitOps
              </p>
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-hidden">
          <CopilotChat
            className="h-full"
            labels={{
              initial: "How can I help with your oncall investigation?",
              placeholder:
                "Ask about pods, deployments, GitOps, or incidents...",
            }}
          />
        </main>
      </div>
    </div>
  );
}
