# tmux-orchestrator

One Claude Code session, the orchestrator, runs other Claude Code sessions, the agents, as panes
in the same tmux session: one agent per repo, ticket or PR. The orchestrator reads each agent's
screen and types replies into its prompt through tmux. Agents report back with SendMessage when
they have it loaded. Pane borders and the status bar show which agent is working, done, or
waiting on you.

```
┌──────────────────────────────┬─────────────────────────────────────────────┐
│                              │ ● aurora · working for orchestrator · 09:14 │
│                              │                                             │
│  orchestrator (Claude Code)  ├─────────────────────────────────────────────┤
│                              │ ! app-iam · needs you · 09:15               │
│                              │                                             │
│                              ├─────────────────────────────────────────────┤
│                              │ ✓ workflows · done · 09:12                  │
│                              │                                             │
└──────────────────────────────┴─────────────────────────────────────────────┘
 [demo] 0:claude*                                          agents ● ! ✓  09:16
```

Yellow `●` is working, red `!` needs you (a permission or trust prompt), green `✓` is done and
waiting at its prompt.

## What is in this folder

| File | Purpose |
|---|---|
| `SKILL.md` | What Claude follows when it acts as the orchestrator |
| `scripts/agents.sh` | `spawn`, `status`, `peek`, `send`, `watch`, `restart`, `stop` and the rest. Run `bash scripts/agents.sh help` |
| `scripts/agent-state-hook.sh` | Claude Code hook that records each session's state on its tmux pane, for the borders and status bar |
| `scripts/tmux-claude.sh` | The `tmux-claude` shell function that starts the orchestrator inside tmux |

This is a plain skill folder, not a marketplace plugin. `SKILL.md`, the hooks and the shell
function all call the scripts at the fixed path `~/.claude/skills/tmux-orchestrator/scripts/`,
and a plugin install lands under a versioned cache path instead.

## Requirements

| | Minimum | Tested |
|---|---|---|
| macOS | untested on older releases | 27.0.1 |
| bash | 3.2, the stock `/bin/bash` | 3.2.57 |
| tmux | 3.2 (`pane-border-lines`, used by `agents.sh layout`, arrived in 3.2) | 3.8 |
| jq | any 1.x | 1.8.1 |
| Claude Code | 2.1 (screen matching uses 2.1 wording) | 2.1.323, 2.1.326 |
| Terminal | UTF-8 and 256 colors | Ghostty |

## Setup on a Mac

### 1. Install tmux and jq

```bash
brew install tmux jq
tmux -V          # tmux 3.2 or newer
jq --version
```

No Homebrew yet: install it from https://brew.sh first. jq is needed by the state hook to read
the JSON Claude Code passes it.

### 2. Configure tmux (recommended)

Add to `~/.tmux.conf`:

```tmux
set -g mouse on                  # click a pane to focus it, scroll its history with the wheel
set -g history-limit 100000      # long Claude transcripts stay scrollable
set -s escape-time 10            # Esc reaches Claude at once; the 500ms default makes interrupts lag
set -g focus-events on

# Shift+Enter inserts a newline in Claude Code instead of submitting
set -g extended-keys on

# truecolor and extended keys for Ghostty; replace xterm-ghostty with what `echo $TERM` prints outside tmux
set -g default-terminal "tmux-256color"
set -as terminal-features ",xterm-ghostty:RGB"
set -as terminal-features ",xterm-ghostty:extkeys"

# flag windows where Claude rang the bell (it needs input)
set -g monitor-bell on
set -g bell-action any
```

If a tmux server is already running, load it with `tmux source-file ~/.tmux.conf`.

### 3. Put the skill where Claude Code finds it

```bash
git clone https://github.com/arigsela/claude-agents.git ~/git/claude-agents   # skip if already cloned
mkdir -p ~/.claude/skills
ln -s ~/git/claude-agents/skills/tmux-orchestrator ~/.claude/skills/tmux-orchestrator
ls ~/.claude/skills/tmux-orchestrator/scripts   # agent-state-hook.sh  agents.sh  tmux-claude.sh
```

The symlink means `git pull` updates the skill. If `~/.claude/skills/tmux-orchestrator` already
exists as a copied folder, move it aside before running `ln -s`, or the link is created inside it.

### 4. Add the `tmux-claude` shell function

```bash
cat >> ~/.zshrc <<'EOF'

# tmux-claude <session> [repo] [prompt]: start or reattach a tmux session running Claude Code
[ -f "$HOME/.claude/skills/tmux-orchestrator/scripts/tmux-claude.sh" ] && source "$HOME/.claude/skills/tmux-orchestrator/scripts/tmux-claude.sh"
EOF
source ~/.zshrc
tmux-claude --help
```

Usage: `tmux-claude <session> [repo] [prompt]`. `repo` is a path, or a folder name under `~/git`.
If your repos live elsewhere, pass the full path. An existing session is reattached as-is. When
Claude exits, the pane drops to a shell instead of closing the session. The function also works
when sourced from `~/.bashrc`.

### 5. Add the state hooks to `~/.claude/settings.json`

Four user-level hooks (UserPromptSubmit, Notification, Stop, PostToolUse) call
`agent-state-hook.sh`. It records `working`, `needs-you` or `done` on the session's tmux pane.
Outside tmux it exits at once, it never prints anything, and it always exits 0, so it is safe in
every Claude session.

This appends the hooks next to any you already have, and does nothing for an event that already
has them:

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak 2>/dev/null || echo '{}' > ~/.claude/settings.json.bak
hook='bash "$HOME/.claude/skills/tmux-orchestrator/scripts/agent-state-hook.sh"'
jq --arg hook "$hook" '
  def add_hook($event; $arg; $extra):
    if any(.hooks[$event][]?.hooks[]?; .command | contains("agent-state-hook.sh")) then .
    else .hooks[$event] = ((.hooks[$event] // []) + [{hooks: [({type: "command", command: "\($hook) \($arg) 2>/dev/null; exit 0", timeout: 5} + $extra)]}])
    end;
  add_hook("UserPromptSubmit"; "prompt"; {})
  | add_hook("Notification"; "notify"; {})
  | add_hook("Stop"; "stop"; {})
  | add_hook("PostToolUse"; "tool"; {async: true})
' ~/.claude/settings.json.bak > ~/.claude/settings.json
```

<details>
<summary>The entries it adds, to edit by hand instead</summary>

Append each object to the existing array for that event under `"hooks"`, or create the array:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "bash \"$HOME/.claude/skills/tmux-orchestrator/scripts/agent-state-hook.sh\" prompt 2>/dev/null; exit 0", "timeout": 5 } ] }
    ],
    "Notification": [
      { "hooks": [ { "type": "command", "command": "bash \"$HOME/.claude/skills/tmux-orchestrator/scripts/agent-state-hook.sh\" notify 2>/dev/null; exit 0", "timeout": 5 } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command", "command": "bash \"$HOME/.claude/skills/tmux-orchestrator/scripts/agent-state-hook.sh\" stop 2>/dev/null; exit 0", "timeout": 5 } ] }
    ],
    "PostToolUse": [
      { "hooks": [ { "type": "command", "command": "bash \"$HOME/.claude/skills/tmux-orchestrator/scripts/agent-state-hook.sh\" tool 2>/dev/null; exit 0", "timeout": 5, "async": true } ] }
    ]
  }
}
```

</details>

Without the hooks everything still works: state then comes from the screen text alone, and
borders stay grey.

### 6. Check it works

1. Start an orchestrator in a scratch session:

   ```bash
   tmux-claude demo ~/git/claude-agents
   ```

   Claude Code opens inside a tmux session named `demo`. A folder Claude has not opened before
   starts on the trust dialog; pick "Yes, I trust this folder".

2. Send that Claude any prompt, such as `say hi`, and wait for the answer. From a second terminal
   window (not inside tmux), check the hook state:

   ```bash
   tmux list-panes -a -F '#{session_name} #{pane_id} #{@state} #{@since}'
   # demo %0 done 09:14
   ```

   An empty state column means the hooks did not run: recheck step 5 and `command -v jq`.

3. In the orchestrator, ask:

   > Use tmux-orchestrator to spawn an agent named scratch in ~/git/claude-agents with the prompt "List the top-level folders, then wait at your prompt"

   A pane opens on the right with `scratch` on its border, yellow while it works and green when
   it is done. Ask "what is scratch doing?" and the orchestrator peeks at its screen.

4. Ask "stop all agents and close their panes", then exit the orchestrator with `/exit` and type
   `exit` at the shell that remains.

## Daily use

1. Write a `HANDOVER.md` in each directory an agent will work in: the task, the plan or ticket,
   and when to stop at a checkpoint. The default `spawn` prompt tells each agent to read and
   follow it, report to the orchestrator at every checkpoint, and never answer permission prompts.
2. Start the orchestrator from any terminal, inside tmux or not, with your request as the first
   message:

   ```bash
   tmux-claude handovers claude-agents "Use tmux-orchestrator to spin up agents for the handovers in ~/git/repo-a and ~/git/repo-b"
   ```

3. The orchestrator records its SendMessage name, spawns one pane per agent, and watches them in
   the background. It brings you each agent's checkpoint with a proposed reply, and sends it once
   you agree, or on its own where the plan already decides it.
4. Trust and permission prompts in agent panes are yours. The orchestrator tells you which pane;
   click it, or ask the orchestrator to `focus` it.

### tmux keys

- The prefix is Ctrl-b. Press Ctrl-b, let go, then press the next key.
- Ctrl-b then an arrow key moves between panes. With `mouse on`, clicking works too.
- Ctrl-b then `z` zooms the current pane to full screen. Press it again to go back.
- Ctrl-b then a number switches tab. Ctrl-b then `w` lists every tab.
- Ctrl-b then `d` detaches. Everything keeps running. Come back with `tmux-claude <session>` or
  `tmux attach -t <session>`.

## Mac notes

- Closing the lid sleeps the Mac and pauses every agent. Nothing is lost; a request that was in
  flight may need a nudge. To stop idle sleep while the lid is open, run `caffeinate -i` in a
  spare terminal tab.
- The scripts are written for the stock `/bin/bash` 3.2 (no associative arrays), so Homebrew bash
  is not needed. They also run under bash 5.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `tmux-claude: command not found` | Step 4, then open a new terminal or `source ~/.zshrc` |
| `agents.sh: not inside tmux and ORCH_PANE is unset` | The orchestrator is not in tmux. Start it with `tmux-claude`. From a Claude session outside tmux, prefix commands with `ORCH_PANE=%<id>` (find it with `tmux list-panes -a -F '#{pane_id} #{session_name} #{b:pane_current_path}'`) |
| `agents.sh layout` fails with `invalid option: pane-border-lines` | tmux is older than 3.2. `brew upgrade tmux`, then end the old sessions so the old tmux server exits and the next one starts on the new version |
| Borders stay grey, `status` shows `no hooks` | Step 5 not applied, or jq not on `PATH` for Claude. Claude Code picks up settings changes on a running session's next prompt (seen on 2026-11-13, not guaranteed); restart the agent if not |
| A pane never turns red at a permission prompt | The hook matches "permission" in the Notification payload. Check the `Limits` section of `SKILL.md` |
| An agent pane shows `dead` | Ask the orchestrator to restart it (`agents.sh restart <name>`, or `--fresh` if it closed at the trust dialog) |
| You ran tmux commands in a plain terminal and see nothing | The session is detached: `tmux attach -t <session>` |

Never run `tmux kill-server` to clean up: it ends every tmux session on the machine. Stop agents
with the orchestrator's `stop` and `kill`, then `/exit` the orchestrator.

## Uninstall

```bash
rm ~/.claude/skills/tmux-orchestrator      # removes the symlink only
cp ~/.claude/settings.json ~/.claude/settings.json.bak
jq 'if .hooks then .hooks |= (with_entries(.value |= map(select(any(.hooks[]?; .command | contains("agent-state-hook.sh")) | not))) | with_entries(select(.value | length > 0))) else . end' \
  ~/.claude/settings.json.bak > ~/.claude/settings.json
```

Then delete the two `tmux-claude` lines from `~/.zshrc`.

## Limits

State detection, what was verified against live panes and what only against simulated screens,
is listed under `Limits` in [`SKILL.md`](./SKILL.md).
