# cctl — Claude Code ctl

**The missing Claude Code ctl that power users would love to see.**

A small command-line tool for [Claude Code](https://code.claude.com/docs/en/overview) power users: list every session you have across all folders, see their `/rename` names and which ones are open right now, resume any of them from anywhere, and clean up the ones you no longer need.

> **Disclaimer:** Claude Code is a product of Anthropic. cctl is an unofficial utility for Claude Code users, not made by or affiliated with Anthropic. It is only a wrapper script that reads Claude Code's local session files and runs the `claude` CLI.

```
$ cctl ls -n -l
1: 7f3c9a12  2026-11-18 23:39     12 msgs  ~/code/api
       fix-auth-timeouts (open, busy, pid 21307)
2: d70d31e9  2026-11-18 23:27    802 msgs  ~/docs
       q4-planning
3: a529f33b  2026-11-18 03:41    143 msgs  ~/code/web
       (unnamed) Refactor checkout form validation

3 session(s), 1 open
```

## Why

- **Find sessions in every folder at once.** `claude --resume` works per folder. cctl lists sessions from all of them, with the names you gave them via `/rename`.
- **Resume from anywhere.** `cctl resume q4-planning` switches to the session's original folder and starts `claude --resume` there.
- **See what's running.** `-l` marks sessions that are open in another terminal, so you don't resume the same one twice.
- **Clean up safely.** Delete by name, ID or list number, or clear out every session under a scratch folder, with confirmations that are hard to get wrong.

## Install

cctl is a single Python file with no dependencies. It needs Python 3.8+ and Claude Code.

```sh
curl -fsSL https://raw.githubusercontent.com/fundacoder/cctl/main/cctl -o ~/.local/bin/cctl
chmod +x ~/.local/bin/cctl
```

Or clone the repo and put `cctl` anywhere on your `PATH`.

## Usage

With no command, `cctl` runs `cctl ls`. Run `cctl -h` for the full reference.

### List — `cctl ls`

```sh
cctl                      # all sessions, newest first
cctl ls -n -l             # numbered, open sessions marked (open)
cctl ls -v                # full session IDs and transcript paths
cctl ls --named -p api    # renamed sessions in folders matching "api"
cctl ls -m 10 --json      # newest 10, as JSON
```

| Option | |
|---|---|
| `-l`, `--list` | list which sessions are open, e.g. `(open, busy, pid 123)` |
| `-n`, `--number` | number the list; numbers work with `resume` and `rm` |
| `-v`, `--verbose` | show full session IDs and transcript paths |
| `--json` | output JSON |

### Resume — `cctl resume`

```sh
cctl resume q4-planning           # by /rename name, from any folder
cctl resume -p api                # pick from sessions in folders matching "api"
cctl resume                       # pick from all sessions
cctl resume 3 -- --model opus     # by list number; args after -- go to claude
cctl resume q4-planning --dry-run # print the command instead of running it
```

If exactly one session matches, it resumes straight away. If several match, you pick one from a list. If the session is already open somewhere else, cctl warns you and asks first, because two copies of the same session would write over each other (`--force` skips the question).

### Delete — `cctl rm`

```sh
cctl rm old-experiment            # by name, ID (or prefix), or list number
cctl rm 2 5 old-experiment        # several at once
cctl rm -p /tmp/scratch --all     # every session under a folder, one confirmation
```

| Option | |
|---|---|
| `--all` | delete every session matched by `-p` (required), after one confirmation |
| `-y`, `--yes` | don't ask, for an exact, unique `/rename` name match only |
| `--force` | also delete sessions that are open |

### Filters (every command)

| Option | |
|---|---|
| `-p`, `--project TEXT` | only sessions whose folder contains TEXT (case-insensitive) |
| `--named` | only sessions renamed with `/rename` |
| `-o`, `--open` | only sessions that are open right now |
| `-m`, `--limit N` | only the N newest sessions |

## Choosing a session

`resume` and `rm` accept any of these as a TARGET:

| TARGET | Matches |
|---|---|
| `q4-planning` | a `/rename` name; part of a name also works, after a check |
| `d70d31e9` | a session ID, or its first 4+ characters |
| `3` | a number from `cctl ls -n`; use the same filters in both commands |

## Safety

Deleting a session can't be undone, so cctl is careful about it:

- Only an exact `/rename` name that matches one session, and isn't part of any other name, can be deleted without a prompt (with `-y`).
- IDs, list numbers, duplicate names and partial names always ask, even with `-y`.
- If a TARGET matches several sessions, you choose which ones from a numbered list.
- `rm --all` only works together with `-p`, refuses filters that would match everything (like `-p /`), shows the full list and asks once.
- Open sessions are never deleted without `--force`.
- Without a terminal (in scripts and pipes), anything that needs a confirmation is skipped.

`rm` removes the session's transcript, its subagent and file-history data, and its `session-env` folder. It leaves your shared prompt history (`~/.claude/history.jsonl`) alone.

Claude Code also has a built-in `claude purge [path]`, which deletes all of one project's data. cctl works per session and across folder patterns, and shows you what it will delete first.

## How it works

cctl reads files that Claude Code keeps on your machine:

| Path | Used for |
|---|---|
| `~/.claude/projects/<project>/<session-id>.jsonl` | session transcripts: folder, `/rename` name, auto title, message count |
| `~/.claude/sessions/<pid>.json` | sessions that are running, checked against live process IDs |
| `~/.claude/file-history/<session-id>/`, `~/.claude/session-env/<session-id>/` | removed together with a session by `rm` |

These are internal Claude Code files, not a supported interface, so a Claude Code update could change them. If something stops working, please open an issue.

## Environment

| Variable | |
|---|---|
| `CLAUDE_CONFIG_DIR` | Claude Code data folder (default `~/.claude`) |
| `CCTL_CLAUDE` | `claude` program used by `resume` (default: `claude` on your `PATH`) |
| `NO_COLOR` | turn off colors |

## Compatibility

Developed and tested on macOS. It should also work on Linux; Windows is untested.

## License

[Apache License 2.0](LICENSE)
