"use client";

import { createContext, useContext, useState } from "react";
import { CopilotKit } from "@copilotkit/react-core";
import "@copilotkit/react-ui/styles.css";

interface ThreadContextValue {
  threadId: string;
  setThreadId: (id: string) => void;
}

const ThreadContext = createContext<ThreadContextValue | null>(null);

export function useThread() {
  const ctx = useContext(ThreadContext);
  if (!ctx) throw new Error("useThread must be used within Providers");
  return ctx;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [threadId, setThreadId] = useState(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("oncall-active-session");
      if (stored) return stored;
    }
    return crypto.randomUUID();
  });

  return (
    <ThreadContext.Provider value={{ threadId, setThreadId }}>
      <CopilotKit
        runtimeUrl="/api/copilotkit"
        agent="oncallAgent"
        showDevConsole={false}
        threadId={threadId}
      >
        {children}
      </CopilotKit>
    </ThreadContext.Provider>
  );
}
