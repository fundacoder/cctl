# cctl — Claude Code ctl

**The missing Claude Code ctl that power users would love to see.**

> **Fun fact:** no prize for guessing — cctl was written by Claude Code.

A small command-line tool for [Claude Code](https://code.claude.com/docs/en/overview) power users: list every session you have across all folders, see their `/rename` names and which ones are open right now, resume, read or watch any of them from anywhere, and clean up the ones you no longer need.

> **Disclaimer:** Claude Code is a product of Anthropic. cctl is an unofficial utility for Claude Code users, not made by or affiliated with Anthropic. It is only a wrapper script that reads Claude Code's local session files and runs the `claude` CLI.

```
$ cctl ls -n
 #  ID        LAST ACTIVE        MSGS  STATE  SESSION                             FOLDER
1:  7f3c9a12  2026-11-18 23:39     12  open   fix-auth-timeouts                   ~/code/api
2:  d70d31e9  2026-11-18 23:27    802  -      q4-planning                         ~/docs
3:  a529f33b  2026-11-18 03:41    143  -      Refactor checkout form validation   ~/code/web

3 session(s), 1 open
```

## Why

You `/rename` a session `cctl-dev`, get pulled onto something else, and two weeks later you want it back. Which folder was it in? Where did you clone that repo? What was the session ID? With cctl, from any folder:

```sh
cctl resume cctl-dev
```

cctl finds the session, switches to its folder and resumes it. It's all terminal, so it works the same over SSH on a headless machine.

- **Find sessions in every folder at once.** `claude --resume` works per folder. cctl lists sessions from all of them, with the names you gave them via `/rename`.
- **Find them by what you remember.** Search names and the titles Claude gives sessions (`cctl ls -s "login bug"`), filter by folder, sort like `ls -ltr`.
- **Resume from anywhere.** `cctl resume q4-planning` switches to the session's original folder and starts `claude --resume` there.
- **Read any conversation.** `cctl log` prints a session as readable text, without opening it.
- **See what's running.** The STATE column shows `open` for sessions running in another terminal or headless, so you don't resume the same one twice, and `cctl watch` shows what they're doing, live.
- **One line per session.** Nothing is cut off; long lines just wrap in your terminal, so `cctl | grep …` always returns whole records.
- **Clean up safely.** Delete by name, ID or list number, or clear out every session under a scratch folder, with confirmations that are hard to get wrong.

## Install

cctl is a single Python file with no dependencies. It needs Python 3.8+ and Claude Code.

```sh
curl -fsSL https://raw.githubusercontent.com/fundacoder/cctl/main/cctl -o ~/.local/bin/cctl
chmod +x ~/.local/bin/cctl
```

Or clone the repo and put `cctl` anywhere on your `PATH`.

## Usage

With no command, `cctl` runs `cctl ls`. Run `cctl -h` (or `cctl help`) for the full reference, `cctl help <command>` for one command, and `cctl -v` for the version.

### List — `cctl ls`

```sh
cctl                      # all sessions, newest first
cctl ls -n                # numbered, for use with resume and rm
cctl ls -ltr              # long format, newest at the bottom (like ls -ltr)
cctl ls -S -m 5           # the 5 biggest sessions by message count
cctl ls -N -f api         # renamed sessions in folders matching "api"
cctl ls -s "login bug"    # search /rename names and AI titles
cctl ls -m 10 --json      # newest 10, as JSON
```

| Option | |
|---|---|
| `-n`, `--number` | number the list; the numbers work as TARGETs in the other commands |
| `-l`, `--long` | long format: full session IDs, plus PID and transcript path columns |
| `--json` | output JSON |

### Resume — `cctl resume`

```sh
cctl resume q4-planning           # by /rename name, from any folder
cctl resume "login bug"           # by the title Claude gave it, or part of it
cctl resume -f api                # pick from sessions in folders matching "api"
cctl resume -s "login bug"        # pick from sessions matching a search
cctl resume                       # pick from all sessions
cctl resume 3 -- --model opus     # by list number; args after -- go to claude
cctl resume q4-planning --dry-run # print the command instead of running it
```

If exactly one session matches, it resumes straight away. If several match, you pick one from a list. If the session is already open somewhere else, cctl warns you and asks first, because two copies of the same session would write over each other (`--force` skips the question).

### Delete — `cctl rm`

```sh
cctl rm old-experiment            # by name, AI title, ID (or prefix), or list number
cctl rm 2 5 old-experiment        # several at once
cctl rm -f /tmp/scratch --all     # every session under a folder, one confirmation
cctl rm -f /tmp/scratch --all --force   # the same, no questions asked (for scripts)
```

| Option | |
|---|---|
| `--all` | delete every session matched by `-f` (required), after one confirmation |
| `-y`, `--yes` | don't ask, for an exact, unique `/rename` name match only |
| `--force` | never ask (for scripts); also deletes open sessions. A TARGET that matches several sessions is still refused |

### Read — `cctl log`

```sh
cctl log cctl-dev                 # the whole conversation, in your pager
cctl log cctl-dev --tail 10       # only the last 10 turns
cctl log 3 --tools | grep error   # include tool output; piped output skips the pager
```

Prints a session's conversation as readable text: your messages, Claude's replies, and one line per tool call (`→ Bash: git status`). Tool output is hidden unless you pass `--tools`, which shows the first 5 lines of each result.

| Option | |
|---|---|
| `--tail N` | only the last N turns |
| `--tools` | also show tool output |
| `--no-pager` | print straight to the terminal instead of `$PAGER` (default `less`) |

### Watch — `cctl watch`

```sh
cctl watch                        # live: what every open session is doing
cctl watch cctl-dev               # follow one session
cctl watch -f api --verbose       # sessions in "api" folders, full replies and tool errors
cctl watch cctl-dev --once        # what it did recently, then exit
```

A live feed, one line per action, for keeping an eye on sessions, including headless `claude -p` runs you can't otherwise see:

```
== watching 2 open session(s): api-refactor, nightly-tests
22:16:50  nightly-tests  Bash     Run the integration suite
22:16:56  api-refactor   Edit     ~/code/api/auth/session.py
22:17:04  api-refactor   says     The token refresh now retries once before failing.
== nightly-tests closed
```

With no TARGET it follows every open session and picks up new ones as they start. Press Ctrl-C to stop.

| Option | |
|---|---|
| `--tail N` | first show the last N actions of each session (default 10; `0` for only new ones) |
| `--verbose` | full replies, and tool errors marked with `!` |
| `--once` | show what happened so far, then exit |

### Filters and order (every command)

| Option | |
|---|---|
| `-f`, `--folder TEXT` | only sessions whose folder contains TEXT |
| `-s`, `--session TEXT` | only sessions whose `/rename` name or AI title contains TEXT |
| `-N`, `--named` | only sessions renamed with `/rename` |
| `-o`, `--open` | only sessions that are open right now |
| `-m`, `--limit N` | at most N sessions, the first N in sort order |
| `-t`, `--time` | sort by last activity, newest first (the default) |
| `-S`, `--size` | sort by message count, most first |
| `-r`, `--reverse` | reverse the order |

Text filters ignore case. When you pick a session by its number from `cctl ls -n`, pass the same filters and order flags to `resume`, `rm`, `log` or `watch`, so the numbers line up.

## Choosing a session

`resume`, `rm`, `log` and `watch` accept any of these as a TARGET:

| TARGET | Matches |
|---|---|
| `q4-planning` | a `/rename` name; part of a name also works, after a check |
| `"login bug"` | an AI title (the name Claude gives a session), or part of it |
| `d70d31e9` | a session ID, or its first 4+ characters |
| `3` | a number from `cctl ls -n`; use the same filters in both commands |

## Safety

Deleting a session can't be undone, so cctl is careful about it:

- Only an exact `/rename` name that matches one session, and isn't part of any other name, can be deleted without a prompt (with `-y`).
- IDs, list numbers, AI titles, duplicate names and partial names always ask, even with `-y`.
- If a TARGET matches several sessions, you choose which ones from a numbered list.
- `rm --all` only works together with `-f`, refuses filters that would match everything (like `-f /`), shows the full list and asks once.
- Open sessions are never deleted without `--force`.
- Without a terminal (in scripts and pipes), anything that needs a confirmation is skipped.
- `--force` is for scripts: it never asks and includes open sessions, but it still refuses a TARGET that matches several sessions, so it never guesses.

`rm` removes the session's transcript, its subagent and file-history data, and its `session-env` folder. When a project's last session is removed, its folder under `~/.claude/projects` goes too, unless it holds anything else, such as project memory. It leaves your shared prompt history (`~/.claude/history.jsonl`) alone.

Claude Code also has a built-in `claude purge [path]`, which deletes all of one project's data. cctl works per session and across folder patterns, and shows you what it will delete first.

## How it works

cctl reads files that Claude Code keeps on your machine:

| Path | Used for |
|---|---|
| `~/.claude/projects/<project>/<session-id>.jsonl` | session transcripts: folder, `/rename` name, AI title, message count, and the conversation itself for `log` and `watch` |
| `~/.claude/sessions/<pid>.json` | sessions that are running, checked against live process IDs; the process list (`ps`) is checked too, for `claude` processes started with `--session-id` or `--resume` |
| `~/.claude/file-history/<session-id>/`, `~/.claude/session-env/<session-id>/` | removed together with a session by `rm` |

These are internal Claude Code files, not a supported interface, so a Claude Code update could change them. If something stops working, please open an issue.

## Environment

| Variable | |
|---|---|
| `CLAUDE_CONFIG_DIR` | Claude Code data folder (default `~/.claude`) |
| `CCTL_CLAUDE` | `claude` program used by `resume` (default: `claude` on your `PATH`) |
| `PAGER` | pager used by `log` (default `less -RFX`) |
| `NO_COLOR` | turn off colors |

## Testing

cctl reads Claude Code's internal files, so run the tests after every Claude Code update:

```sh
python3 -m unittest discover -s tests -v                 # about 10 seconds, no network
cd tests && CCTL_LIVE=1 python3 -m unittest -v test_cctl.LiveTest   # also a real claude -p run
```

| Layer | What it checks |
|---|---|
| Behaviour | every command on fake sessions in a throwaway folder: listing, sorting, filters, resume, all delete safety rules, log, watch, help |
| Real data format | your own Claude Code transcripts and session records still have the fields cctl reads. Read-only, checks structure only, never prints content. This is what fails first when a Claude Code update changes things. Skipped if there is no local data, or with `CCTL_SKIP_REAL=1` |
| Live (opt-in) | starts a tiny headless `claude -p` session, sees it open, watches it, reads it and deletes it. Uses a few tokens |

Standard library only; nothing to install.

## Upgrading from 0.2.0

0.3.0 changed several flags. Nobody should have scripts built on 0.2.0 yet, so the old ones were removed rather than kept as aliases:

| 0.2.0 | 0.3.0 |
|---|---|
| `-p`, `--project TEXT` | `-f`, `--folder TEXT` (`-p` is reserved for later) |
| `-l` to mark open sessions | gone: open sessions are always shown in the STATE column |
| `-v`, `--verbose` (full IDs, paths) | `-l`, `--long`; `cctl -v` now prints the version |
| `--named` | still works, now also `-N` |
| `cctl -d TARGET`, `cctl --delete-all -p X` | `cctl rm TARGET`, `cctl rm --all -f X` |
| two lines per session | one line per session, with a header |

## Compatibility

Developed and tested on macOS. It should also work on Linux (it uses `ps` to spot headless sessions); Windows is untested. Needs Python 3.8 or newer.

## Credits

`cctl watch` is adapted from the `watch` command of the author's own agent harness.

## License

[Apache License 2.0](LICENSE)
