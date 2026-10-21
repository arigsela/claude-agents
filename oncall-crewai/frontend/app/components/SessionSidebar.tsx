"use client";

import { SessionSummary } from "../lib/sessions";

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

interface SessionSidebarProps {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  isOpen: boolean;
  onToggle: () => void;
  username?: string | null;
  onLogout?: () => void;
}

export default function SessionSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  isOpen,
  onToggle,
  username,
  onLogout,
}: SessionSidebarProps) {
  return (
    <>
      {/* Mobile toggle */}
      <button
        onClick={onToggle}
        className="md:hidden fixed top-4 left-4 z-50 p-2 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
        aria-label="Toggle sidebar"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          {isOpen ? (
            <path d="M18 6L6 18M6 6l12 12" />
          ) : (
            <path d="M3 12h18M3 6h18M3 18h18" />
          )}
        </svg>
      </button>

      {/* Sidebar */}
      <aside
        className={`
          ${isOpen ? "translate-x-0" : "-translate-x-full"}
          md:translate-x-0
          fixed md:relative z-40
          w-64 h-full
          bg-zinc-900 border-r border-zinc-800
          flex flex-col
          transition-transform duration-200 ease-in-out
        `}
      >
        {/* New Chat button */}
        <div className="p-3 border-b border-zinc-800">
          <button
            onClick={onNewChat}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg
                       bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium
                       transition-colors"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M12 5v14M5 12h14" />
            </svg>
            New Chat
          </button>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto">
          {sessions.length === 0 ? (
            <p className="p-4 text-sm text-zinc-500 text-center">
              No conversations yet
            </p>
          ) : (
            <ul className="py-1">
              {sessions.map((session) => (
                <li
                  key={session.session_id}
                  className={`
                    group relative px-3 py-2 mx-1 my-0.5 rounded-lg cursor-pointer
                    transition-colors text-sm
                    ${
                      session.session_id === activeSessionId
                        ? "bg-zinc-700 text-white"
                        : "text-zinc-300 hover:bg-zinc-800"
                    }
                  `}
                  onClick={() => onSelectSession(session.session_id)}
                >
                  <div className="pr-6 truncate font-medium">
                    {session.title}
                  </div>
                  <div className="text-xs text-zinc-500 mt-0.5">
                    {timeAgo(session.last_accessed)}
                    {session.message_count > 0 &&
                      ` \u00B7 ${session.message_count} msgs`}
                  </div>

                  {/* Delete button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteSession(session.session_id);
                    }}
                    className="absolute right-2 top-2 p-1 rounded
                               opacity-0 group-hover:opacity-100
                               text-zinc-500 hover:text-red-400 hover:bg-zinc-700
                               transition-opacity"
                    aria-label="Delete session"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path d="M18 6L6 18M6 6l12 12" />
                    </svg>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* User info & logout */}
        {username && (
          <div className="p-3 border-t border-zinc-800">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <div className="w-7 h-7 rounded-full bg-blue-600/20 flex items-center justify-center text-blue-400 text-xs font-bold shrink-0">
                  {username.charAt(0).toUpperCase()}
                </div>
                <span className="text-sm text-zinc-300 truncate">
                  {username}
                </span>
              </div>
              {onLogout && (
                <button
                  onClick={onLogout}
                  className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors shrink-0"
                  aria-label="Sign out"
                >
                  Sign out
                </button>
              )}
            </div>
          </div>
        )}
      </aside>

      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="md:hidden fixed inset-0 z-30 bg-black/50"
          onClick={onToggle}
        />
      )}
    </>
  );
}
