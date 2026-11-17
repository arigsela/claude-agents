---
name: tmux-orchestrator
description: Use when one Claude Code session coordinates other Claude Code sessions running in tmux panes or tabs, such as an orchestrator with one agent per repo, ticket or PR. Triggers include starting or spawning agents in tmux, asking what the agents are doing, an agent's checkpoint or status block waiting for a reply, an agent saying SendMessage is not loaded, a closed, crashed or dead agent pane, a trust or permission prompt in an agent pane, wanting every agent visible on one screen, tmux keys (prefix, Ctrl-b, zoom, detach, reattach), resuming an orchestrator, or shutting the agents down.
---

# tmux orchestrator

## Overview

Each agent is a separate Claude Code session in a pane of the orchestrator's tmux session. tmux is the channel that always works: read an agent's screen, type a reply into its prompt. SendMessage is a bonus when the agent has it loaded.

**Core principle: the panes are the truth.** What you remember about an agent is stale the moment you stop looking.

**The orchestrator must run inside tmux.** The user starts it from any terminal with the `tmux-claude` shell function (`scripts/tmux-claude.sh`, sourced from `~/.zshrc`):

```bash
tmux-claude <session> <repo> ["Use tmux-orchestrator to spin up agents for the handovers in ~/git/a and ~/git/b"]
```

`<repo>` is a path or a folder name under `~/git`. If a user asks you to orchestrate from a session that is not in tmux, give them that command, with their request as the prompt, instead of starting agents yourself.

Script: `bash ~/.claude/skills/tmux-orchestrator/scripts/agents.sh <command>` (written `agents.sh` below). Run inside the orchestrator's pane, it finds the session itself. From a Claude session outside tmux, prefix it with `ORCH_PANE=%<id>`. To find the id, run `tmux list-panes -a -F '#{pane_id} #{session_name} #{b:pane_current_path}'`.

## Start of every orchestrator session, including after a resume

1. Run ListAgents and note "This session is `<name>`". The name changes when a session is resumed, so check it every time.
2. Run `agents.sh doctor`. If it, or ListAgents, shows another Claude session in the orchestrator's directory acting as orchestrator, stop and ask the user which one coordinates. Two orchestrators answer the same agents and edit the same handover files.
3. Run `agents.sh init <name>`. This records the name that spawned agents are told to report to, labels your pane, and lays out the window.
4. If any handover or plan file names an older orchestrator name, update it.
5. Run `agents.sh status` before you say anything about any agent.
6. Agents that are already running still have the old name, or none. Send each one that is idle or working: `agents.sh send <name> "Load SendMessage with ToolSearch query select:SendMessage and report to <name> from now on"`.
7. Start `agents.sh watch` with `run_in_background`.

## Quick reference

| Command | Does |
|---|---|
| `init <orch-name>` | Record your SendMessage name, label your pane, lay out the window |
| `spawn <name> <dir> [--tab] [--prompt TEXT]` | Start an agent in a pane on the right, or in its own tab with `--tab` |
| `status` (or `list`) | Every agent's name, pane, window, state and directory |
| `peek <name> [lines]` | The last lines of an agent's screen (default 40) |
| `send <name> [--force] <message>` | Type one line into the agent's prompt and submit it. Refuses if the input line already has text, unless `--force` |
| `watch [--timeout S]` | Block until any agent goes idle, hits a prompt, or closes. Run it in the background |
| `focus <name>` | Move the user's keyboard to that pane, for prompts only they may answer |
| `restart <name> [--fresh]` | Relaunch Claude in a dead pane with `claude --continue`, or a new conversation with `--fresh` |
| `stop <name>` or `stop --all [--force]` | Send `/exit`. Skips agents at prompts; skips working agents unless `--force` |
| `kill <name>` | Close a stopped agent's pane |
| `name <pane_id> <name>` | Label a pane that was started by hand |
| `gather` | Pull agent tabs into the orchestrator window as panes |
| `break <name>` | Move an agent pane out to its own tab |
| `layout` | Orchestrator on the left half, agents stacked on the right, names on pane borders |
| `doctor` | Check the recorded name, look for a second orchestrator, show states |

| State | Meaning | Your move |
|---|---|---|
| `working` | Spinner showing | Leave it. `watch` tells you when it stops |
| `idle` | At its prompt | `peek` it. A checkpoint block means it is waiting for you |
| `permission` | Asking to run a tool | Tell the user which agent and what command. Never answer it |
| `trust` | Folder trust dialog | Tell the user to pick "Yes, I trust this folder". Esc or "No, exit" closes the agent |
| `dead` | Claude exited; pane kept | `restart` |
| `shell` | Shell prompt, no Claude | `restart`, or ask the user |

## Seeing state at a glance

`scripts/agent-state-hook.sh` runs from four user-level hooks in `~/.claude/settings.json`: UserPromptSubmit, Notification, Stop and PostToolUse (async). Every Claude session in a tmux pane records its state on that pane, and outside tmux the hooks do nothing. `agents.sh layout` draws the result:

| Where | Shows |
|---|---|
| Pane border | Yellow `● aurora · working for orchestrator · 09:14`, red `! workflows · needs you · 09:15`, green `✓ app-iam · done · 09:12` |
| Status bar, right | `agents ●●○●`, one dot per agent in every window: yellow working, red needs you, green done, grey no hook data yet |
| `agents.sh status` DETAIL column | `working for orchestrator since 09:14`, or `no hooks` |

- "for orchestrator" means the prompt started with `Orchestrator:`, which `send` adds. "for you" means the user typed it.
- `status` and `watch` use the hook state first, the screen for trust and permission dialogs, and the screen alone for panes showing `no hooks`.
- An Esc interrupt fires no Stop hook. A pane whose screen shows "Interrupted" reads as idle even if its hook state says working.
- Claude Code reloads settings while running, so hooks added mid-session reach running agents on their next prompt. That was seen on 2026-11-13, not guaranteed.

## Launching agents

- **Use `agents.sh spawn <name> <dir>`.** Its default prompt tells the agent to:
  - follow `HANDOVER.md`,
  - load SendMessage with ToolSearch (`select:SendMessage`),
  - report to your recorded name,
  - otherwise print its checkpoint block and wait at its prompt.
- **`--prompt` replaces the whole default.** Keep its SendMessage and fallback sentences in any prompt you write.
- **Each spawn needs its own short name** (`aurora`, `app-iam`). Names appear on the pane borders.
- **Tell the user about the trust dialog.** A folder Claude hasn't opened before starts on that dialog. Tell the user which pane needs them, and that "No, exit" or Esc closes the agent.
- **Agents started by hand** with `tmux new-window` and `join-pane`: run `agents.sh name %<id> <name>` for each, then `agents.sh gather`.

## Monitoring loop

1. Run `agents.sh status`.
2. For each `idle` agent, run `agents.sh peek <name> 60` and find its checkpoint or question.
3. Decide who answers. Answer it yourself when the plan already settles it or the user has delegated that decision. Otherwise, show the user the agent's question with your proposed reply, and send it after they agree.
4. Run `agents.sh send <name> "<one line>"`. It prints the bottom of the pane afterwards. Check that the message landed: it appears in the transcript, or a spinner starts. If the text is still in the input box, run `tmux send-keys -t %<id> Enter` once.
5. Between rounds, run `agents.sh watch` with `run_in_background`. You are re-invoked when an agent changes state. Do not poll in the foreground.
6. Update the plan doc's status table from `status` output, not from memory.

**Writing replies:**
- **One line.** The script prefixes it with `Orchestrator:`.
- **Start with the decision:** `Approved: ...`, `Change: ...` or `Hold: ...`.
- **If `send` refuses because the input line has text**, peek the pane. A grey suggestion (like "Check whether the orchestrator replied") is safe to type over: rerun with `send <name> --force "..."`. If it is the user's unsent draft, ask them first. `stop` applies the same check.

## Recovery

| Situation | Do |
|---|---|
| Agent exited or crashed | The pane stays (`dead`). Run `agents.sh restart <name>` to continue its conversation |
| Agent closed at the trust dialog before doing anything, pane shows `dead` | `agents.sh restart <name> --fresh`. A plain restart would `--continue` an unrelated older conversation |
| Pane gone entirely (started by hand before `init`, so no remain-on-exit) | `agents.sh spawn <name> <dir>`. Its worktree and branch keep earlier work; tell it to check them before redoing anything |
| Agent says SendMessage is not loaded | `send` it: `Load SendMessage with ToolSearch query select:SendMessage and report to <your name>`. If that fails too, keep using `peek` |
| Orchestrator was resumed | Redo "Start of every orchestrator session" |
| User ran the tmux commands in a plain terminal and sees nothing | The agents exist but are detached. Tell them `tmux attach -t <session>` |

## User cheat sheet

Give this to the user when they ask how to drive tmux:

- Start or reattach a session: `tmux-claude <session> <repo> ["first message"]`. Run it from any terminal, inside tmux or not.
- The prefix is Ctrl-b. Press Ctrl-b, let go, then press the next key. Don't hold them together.
- Ctrl-b then an arrow key moves between panes, or click a pane (mouse mode).
- Ctrl-b then `z` zooms the current pane to full screen. Press it again to go back.
- Ctrl-b then a number switches tab. Ctrl-b then `w` lists every tab.
- Ctrl-b then `d` detaches. Everything keeps running. Come back with `tmux new -A -s <session>`.
- Closing the laptop lid sleeps the Mac and pauses every agent. Nothing is lost; a request that was in flight may need a nudge.

## Shutdown

1. Run `agents.sh status`. Agents at prompts need the user first.
2. Run `agents.sh stop --all`. It skips agents that are working or at prompts, and reports which.
3. Once the user agrees, run `agents.sh kill <name>` for each dead pane.
4. Never run `tmux kill-server`, which ends every tmux session on the machine. The user closes the orchestrator with `/exit`.
5. Tell the user which worktrees and branches remain. Stopping agents does not remove them.

## Common mistakes

| Mistake | Fix |
|---|---|
| Reporting "agents haven't started" from memory while they were waiting on you | `status` first, every time |
| Launching agents without the SendMessage sentence, so every report needed a human relay | `spawn`, or keep that sentence in `--prompt` |
| Agents report to an old orchestrator name after a resume | `init <current name>` and update handover files |
| Typing into a pane at a permission or trust prompt, which answers it | `send` refuses at prompts. Tell the user, or `focus` the pane |
| Two Claude sessions both acting as orchestrator | `doctor`, then ask the user to pick one |
| `tmux new-window -d` run from a plain terminal, and the user sees nothing | They need `tmux attach -t <session>` |
| Foreground polling loops | `watch` with `run_in_background` |

## Limits

- **Hook state is the primary source** where the hooks are loaded. The hook script is tested by piping sample payloads; one live agent recorded `done` from a real Stop hook. The Notification payload's permission wording is matched case-insensitively on "permission", from memory of Claude Code 2.1, so if a pane never turns red at a permission prompt, check that first.
- **Without hook data, state comes from screen text.** It matches Claude Code 2.1 wording: "Do you want to proceed", the folder trust dialog, and the spinner line `… (Ns · tokens)`.
  - Verified against real Claude Code 2.1.323 panes for `idle`.
  - `working`, `permission`, `trust`, `dead` and `shell` were verified against simulated screens only.
  - When a state looks wrong, `peek` the pane.
- **Requirements:** macOS `/bin/bash` 3.2 or newer, and tmux 3.2 or newer (pane-level options arrived in 3.0, `pane-border-lines` in 3.2). Tested on tmux 3.8. Setup on a Mac: `README.md` in this folder.
