"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  SessionSummary,
  fetchSessions,
  fetchSession,
  deleteSession as apiDeleteSession,
} from "../lib/sessions";
import { TextMessage, Role } from "@copilotkit/runtime-client-gql";
import { useCopilotMessagesContext } from "@copilotkit/react-core";
import { useThread } from "../providers";

const ACTIVE_SESSION_KEY = "oncall-active-session";

export function useSessionManager() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const { setMessages } = useCopilotMessagesContext();
  const { threadId, setThreadId } = useThread();
  const initialized = useRef(false);

  const restoreSession = useCallback(
    async (id: string) => {
      const detail = await fetchSession(id);
      if (!detail || detail.messages.length === 0) {
        setMessages([]);
        return;
      }

      const restored = detail.messages.map(
        (msg) =>
          new TextMessage({
            content: msg.content,
            role: msg.role === "user" ? Role.User : Role.Assistant,
          })
      );
      setMessages(restored);
    },
    [setMessages]
  );

  // Load sessions and restore active session on mount
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    (async () => {
      const list = await fetchSessions();
      setSessions(list);

      const stored = localStorage.getItem(ACTIVE_SESSION_KEY);
      if (stored && list.some((s) => s.session_id === stored)) {
        setThreadId(stored);
        await restoreSession(stored);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist activeSessionId to localStorage
  useEffect(() => {
    if (threadId) {
      localStorage.setItem(ACTIVE_SESSION_KEY, threadId);
    }
  }, [threadId]);

  const loadSessions = useCallback(async () => {
    const list = await fetchSessions();
    setSessions(list);
  }, []);

  const switchSession = useCallback(
    async (id: string) => {
      setThreadId(id);
      await restoreSession(id);
    },
    [setThreadId, restoreSession]
  );

  const newChat = useCallback(() => {
    const newId = crypto.randomUUID();
    setThreadId(newId);
    setMessages([]);
  }, [setThreadId, setMessages]);

  const removeSession = useCallback(
    async (id: string) => {
      const ok = await apiDeleteSession(id);
      if (!ok) return;

      const remaining = sessions.filter((s) => s.session_id !== id);
      setSessions(remaining);

      if (id === threadId) {
        if (remaining.length > 0) {
          await switchSession(remaining[0].session_id);
        } else {
          newChat();
        }
      }
    },
    [threadId, sessions, switchSession, newChat]
  );

  return {
    sessions,
    activeSessionId: threadId,
    loadSessions,
    switchSession,
    newChat,
    removeSession,
  };
}
