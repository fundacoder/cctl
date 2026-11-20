# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 fundacoder
"""Tests for cctl. Standard library only.

    python3 -m unittest discover -s tests -v            # everything that is safe and fast
    CCTL_LIVE=1 python3 -m unittest discover -s tests   # also a real `claude -p` run (uses tokens)

Three layers:

1. Behaviour, on fake sessions in a throwaway Claude data folder. Catches cctl bugs.
2. Format checks on your real Claude Code data (read-only, structure only, never
   prints content). These fail first when a Claude Code update changes the files
   cctl reads. Skipped if there is no local data; CCTL_SKIP_REAL=1 skips them.
3. A live run of a real headless `claude -p` session (CCTL_LIVE=1): start it,
   see it open, watch it, read it, delete it.

Run this after every Claude Code update.
"""
import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CCTL = str(ROOT / "cctl")
REAL_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))


# ----------------------------------------------------------------- helpers

def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


class FakeClaude:
    """A throwaway Claude data folder with sessions in Claude Code's on-disk format."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cctl-test-"))
        self.dir = self.tmp / "claude"
        (self.dir / "projects").mkdir(parents=True)
        (self.dir / "sessions").mkdir()
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.procs = []
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        fake = self.bin / "claude"  # stands in for claude in `resume`
        fake.write_text('#!/bin/sh\nprintf "FAKE pwd=%s args=%s\\n" "$(pwd)" "$*"\n')
        fake.chmod(0o755)

    def cleanup(self):
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def folder(self, name):
        d = self.work / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def session(self, sid=None, folder="proj", title=None, ai=None, prompt="hello there",
                turns=(), age=0, project=None, extra=()):
        """Write a transcript. turns: list of entries for message.content after the prompt."""
        sid = sid or str(uuid.uuid4())
        cwd = str(self.folder(folder))
        pdir = self.dir / "projects" / (project or "-" + cwd.strip("/").replace("/", "-"))
        pdir.mkdir(parents=True, exist_ok=True)
        t = time.time() - age
        lines = [{"type": "permission-mode", "permissionMode": "default", "sessionId": sid},
                 {"type": "user", "cwd": cwd, "sessionId": sid, "timestamp": iso(t),
                  "isSidechain": False, "message": {"role": "user", "content": prompt}}]
        for i, (role, content) in enumerate(turns):
            lines.append({"type": role, "cwd": cwd, "sessionId": sid, "timestamp": iso(t + i + 1),
                          "isSidechain": False, "message": {"role": role, "content": content}})
        lines += list(extra)
        if ai:
            lines.append({"type": "ai-title", "aiTitle": ai, "sessionId": sid})
        if title:
            lines.append({"type": "custom-title", "customTitle": title, "sessionId": sid})
        path = pdir / (sid + ".jsonl")
        path.write_text("".join(json.dumps(x) + "\n" for x in lines))
        os.utime(path, (t, t))
        return sid, path

    def side_data(self, sid, path):
        """The extra per-session data that rm must remove too."""
        (path.with_suffix("") / "subagents").mkdir(parents=True)
        (self.dir / "file-history" / sid).mkdir(parents=True)
        (self.dir / "session-env" / sid).mkdir(parents=True)

    def mark_open(self, sid):
        """Register a session as running, with a real live process behind it."""
        p = subprocess.Popen(["sleep", "120"], start_new_session=True)
        self.procs.append(p)
        (self.dir / "sessions" / f"{p.pid}.json").write_text(json.dumps(
            {"pid": p.pid, "sessionId": sid, "cwd": str(self.work), "kind": "interactive",
             "status": "busy", "startedAt": int(time.time() * 1000)}))
        return p

    def env(self, **extra):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.dir), NO_COLOR="1", COLUMNS="80",
                   CCTL_CLAUDE=str(self.bin / "claude"), PAGER="cat")
        env.update(extra)
        return env

    def run(self, *args, stdin=subprocess.DEVNULL, **env):
        p = subprocess.run([CCTL, *args], stdin=stdin, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True,
                           env=self.env(**env), timeout=30)
        return p.returncode, p.stdout

    def run_tty(self, *args, answers=()):
        """Run in a pseudo-terminal, answering each prompt that ends in '] '."""
        answers = list(answers)
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(CCTL, ["cctl", *args], self.env())
        out = b""
        deadline = time.time() + 20
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 3)
            if not r:
                break
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if answers and out.endswith(b"] "):
                os.write(fd, answers.pop(0))
        done, status = os.waitpid(pid, os.WNOHANG)
        if done == 0:  # still running: it is waiting for input we did not expect
            os.kill(pid, signal.SIGKILL)
            _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") \
            else status >> 8, out.decode("utf-8", "replace").replace("\r", "")


class FakeTest(unittest.TestCase):
    def setUp(self):
        self.c = FakeClaude()
        self.addCleanup(self.c.cleanup)

    def ids_in(self, out):
        return re.findall(r"^\s*(?:\d+:\s+)?([0-9a-f]{8})\s", out, re.M)


# ----------------------------------------------------------------- 1. behaviour

class ListTest(FakeTest):
    def test_newest_first_one_line_each_with_header(self):
        a, _ = self.c.session(title="alpha", age=300)
        b, _ = self.c.session(title="beta", age=100)
        rc, out = self.c.run("ls")
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        self.assertRegex(lines[0], r"^ID\s+LAST ACTIVE\s+MSGS\s+STATE\s+SESSION\s+FOLDER")
        self.assertEqual(self.ids_in(out), [b[:8], a[:8]])
        self.assertIn("2 session(s), 0 open", out)

    def test_session_column_falls_back_to_ai_title_then_first_message(self):
        self.c.session(title="my-name", ai="Ignored AI title")
        self.c.session(ai="Fix login redirect bug")
        self.c.session(prompt="just a first message")
        rc, out = self.c.run("ls")
        self.assertIn("my-name", out)
        self.assertNotIn("Ignored AI title", out)
        self.assertIn("Fix login redirect bug", out)
        self.assertIn("just a first message", out)

    def test_bare_cctl_is_ls(self):
        self.c.session(title="alpha")
        self.assertEqual(self.c.run()[1], self.c.run("ls")[1])

    def test_sorting_reverse_and_limit(self):
        small, _ = self.c.session(title="small", age=10)
        big, _ = self.c.session(title="big", age=500,
                                turns=[("assistant", [{"type": "text", "text": "x"}])] * 5)
        self.assertEqual(self.ids_in(self.c.run("ls", "-t")[1]), [small[:8], big[:8]])
        self.assertEqual(self.ids_in(self.c.run("ls", "-r")[1]), [big[:8], small[:8]])
        self.assertEqual(self.ids_in(self.c.run("ls", "-S")[1]), [big[:8], small[:8]])
        self.assertEqual(self.ids_in(self.c.run("ls", "-m", "1")[1]), [small[:8]])
        out = self.c.run("ls", "-ltr")[1]  # long format: full IDs, oldest first
        self.assertTrue(out.splitlines()[1].startswith(big))

    def test_filters(self):
        self.c.session(title="api-auth", folder="code/api")
        self.c.session(ai="Webhook retries", folder="code/web")
        self.c.session(prompt="a brief that mentions webhook deep inside", folder="code/web")
        self.c.session(title="docs-only", folder="docs")
        out = self.c.run("ls", "-f", "CODE/")[1]
        self.assertIn("api-auth", out)
        self.assertNotIn("docs-only", out)
        out = self.c.run("ls", "-s", "webhook")[1]
        self.assertIn("Webhook retries", out)
        self.assertNotIn("api-auth", out)
        out = self.c.run("ls", "-N")[1]
        self.assertIn("2 session(s)", out)
        self.assertNotIn("Webhook retries", out)
        rc, out = self.c.run("ls", "-f", "nope")
        self.assertIn("No sessions match -f 'nope'.", out)

    def test_search_ignores_deep_first_message_text(self):
        prompt = "Design brief. " + "filler " * 20 + "the harness does X"
        self.c.session(prompt=prompt)
        self.assertIn("No sessions match", self.c.run("ls", "-s", "harness")[1])

    def test_numbering(self):
        self.c.session(title="one", age=20)
        self.c.session(title="two", age=10)
        out = self.c.run("ls", "-n")[1]
        self.assertRegex(out, r"(?m)^\s*1:\s+\w{8}.*two")
        self.assertRegex(out, r"(?m)^\s*2:\s+\w{8}.*one")

    def test_open_state_and_filter(self):
        sid, _ = self.c.session(title="running")
        self.c.session(title="idle-one")
        self.c.mark_open(sid)
        out = self.c.run("ls")[1]
        self.assertRegex(out, r"(?m)^\w{8}.*\bopen\s+running")
        self.assertIn("1 open", out)
        out = self.c.run("ls", "-o")[1]
        self.assertIn("running", out)
        self.assertNotIn("idle-one", out)

    def test_dead_process_is_not_open(self):
        sid, _ = self.c.session(title="stale")
        (self.c.dir / "sessions" / "999999.json").write_text(
            json.dumps({"pid": 999999, "sessionId": sid}))
        self.assertIn("0 open", self.c.run("ls")[1])

    def test_headless_process_detected_from_ps(self):
        sid, _ = self.c.session(title="headless")
        sleeper = self.c.bin / "claude"
        sleeper.write_text("#!/bin/sh\nsleep 120\n")
        sleeper.chmod(0o755)
        p = subprocess.Popen([str(sleeper), "-p", "--session-id", sid], start_new_session=True)
        self.c.procs.append(p)
        time.sleep(0.3)
        self.assertRegex(self.c.run("ls")[1], r"open\s+headless")

    def test_ps_only_session_from_another_data_folder_is_not_listed(self):
        sleeper = self.c.bin / "claude"
        sleeper.write_text("#!/bin/sh\nsleep 120\n")
        sleeper.chmod(0o755)
        p = subprocess.Popen([str(sleeper), "--resume", str(uuid.uuid4())], start_new_session=True)
        self.c.procs.append(p)
        time.sleep(0.3)
        self.assertEqual(self.c.run("ls")[1].strip(), "No sessions found.")

    def test_registered_session_without_transcript_is_listed(self):
        sid = str(uuid.uuid4())
        self.c.mark_open(sid)
        out = self.c.run("ls")[1]
        self.assertIn(sid[:8], out)
        self.assertNotIn("1969", out)

    def test_json(self):
        sid, path = self.c.session(title="j", ai="A")
        data = json.loads(self.c.run("ls", "--json")[1])
        self.assertEqual(data[0]["session_id"], sid)
        self.assertEqual(data[0]["custom_title"], "j")
        self.assertEqual(data[0]["ai_title"], "A")
        self.assertEqual(data[0]["file"], str(path))
        self.assertIn("open", data[0])


class ResumeTest(FakeTest):
    def test_by_name_runs_claude_in_the_session_folder(self):
        sid, _ = self.c.session(title="api-auth", folder="code/api")
        rc, out = self.c.run("resume", "api-auth", "--", "--model", "opus")
        self.assertEqual(rc, 0)
        self.assertIn(f"pwd={self.c.work / 'code/api'}", out.replace("/private", ""))
        self.assertIn(f"args=--resume {sid} --model opus", out)

    def test_by_ai_title_id_prefix_and_number(self):
        a, _ = self.c.session(ai="Fix login redirect bug", age=20)
        b, _ = self.c.session(title="other", age=10)
        self.assertIn(f"--resume {a}", self.c.run("resume", "redirect")[1])
        self.assertIn(f"--resume {a}", self.c.run("resume", a[:6])[1])
        self.assertIn(f"--resume {b}", self.c.run("resume", "1")[1])
        self.assertIn(f"--resume {a}", self.c.run("resume", "1", "-r")[1])

    def test_dry_run(self):
        sid, _ = self.c.session(title="x", folder="f")
        rc, out = self.c.run("resume", "x", "--dry-run")
        self.assertRegex(out, rf"^cd .*/f && .*claude --resume {sid}$")

    def test_missing_folder(self):
        sid, _ = self.c.session(title="gone", folder="gone")
        shutil.rmtree(self.c.work / "gone")
        rc, out = self.c.run("resume", "gone")
        self.assertEqual(rc, 1)
        self.assertIn("folder no longer exists", out)

    def test_open_session_is_protected(self):
        sid, _ = self.c.session(title="busy")
        self.c.mark_open(sid)
        rc, out = self.c.run("resume", "busy")
        self.assertEqual(rc, 1)
        self.assertIn("already open", out)
        self.assertIn(f"--resume {sid}", self.c.run("resume", "busy", "--force")[1])

    def test_ambiguous_needs_a_terminal_and_picker_works(self):
        self.c.session(title="deploy", age=20)
        b, _ = self.c.session(title="deploy-old", age=10)
        rc, out = self.c.run("resume", "deploy")
        self.assertEqual(rc, 1)
        self.assertIn("several sessions match", out)
        # exact name matches are listed before partial ones, so deploy-old is 2
        rc, out = self.c.run_tty("resume", "deploy", answers=[b"2\n"])
        self.assertIn(f"--resume {b}", out)
        rc, out = self.c.run_tty("resume", "deploy", answers=[b"\n"])
        self.assertIn("nothing selected", out)

    def test_no_match(self):
        self.assertEqual(self.c.run("resume", "nothing-here")[0], 1)


class RmTest(FakeTest):
    def exists(self, sid):
        return any(self.c.dir.glob(f"projects/*/{sid}.jsonl"))

    def test_exact_name_with_y_removes_everything(self):
        sid, path = self.c.session(title="old")
        self.c.side_data(sid, path)
        rc, out = self.c.run("rm", "old", "-y")
        self.assertEqual(rc, 0, out)
        self.assertFalse(self.exists(sid))
        self.assertFalse(path.with_suffix("").exists())
        self.assertFalse((self.c.dir / "file-history" / sid).exists())
        self.assertFalse((self.c.dir / "session-env" / sid).exists())

    def test_without_terminal_nothing_is_deleted_unasked(self):
        sid, _ = self.c.session(title="old")
        self.assertEqual(self.c.run("rm", "old")[0], 1)
        self.assertTrue(self.exists(sid))

    def test_risky_matches_always_ask_even_with_y(self):
        sid, _ = self.c.session(title="deploy-old", ai="Ship the thing")
        for target in ("old", sid[:6], "1", "ship"):
            rc, out = self.c.run("rm", target, "-y")
            self.assertEqual(rc, 1, target)
            self.assertIn("confirm needed", out, target)
            self.assertTrue(self.exists(sid), target)

    def test_force_never_asks_but_never_guesses(self):
        a, _ = self.c.session(ai="Login page redesign")
        b, _ = self.c.session(ai="Fix login redirect")
        rc, out = self.c.run("rm", "login", "--force")
        self.assertEqual(rc, 1)
        self.assertTrue(self.exists(a) and self.exists(b))
        self.assertEqual(self.c.run("rm", "redirect", "--force")[0], 0)
        self.assertFalse(self.exists(b))

    def test_open_sessions_need_force(self):
        sid, _ = self.c.session(title="busy")
        self.c.mark_open(sid)
        rc, out = self.c.run("rm", "busy", "-y")
        self.assertIn("session is open", out)
        self.assertTrue(self.exists(sid))
        self.c.run("rm", "busy", "--force")
        self.assertFalse(self.exists(sid))

    def test_prompts(self):
        sid, _ = self.c.session(title="keep")
        for answer in (b"n\n", b"\x04"):
            self.c.run_tty("rm", "keep", answers=[answer])
            self.assertTrue(self.exists(sid))
        self.c.run_tty("rm", "keep", answers=[b"y\n"])
        self.assertFalse(self.exists(sid))

    def test_picker_all(self):
        a, _ = self.c.session(title="dup")
        b, _ = self.c.session(title="dup")
        rc, out = self.c.run_tty("rm", "dup", answers=[b"all\n"])
        self.assertIn("duplicate name", out)
        self.assertFalse(self.exists(a) or self.exists(b))

    def test_all_guards(self):
        self.c.session(title="t1", folder="scratch/a")
        self.c.session(title="t2", folder="scratch/b")
        keep, _ = self.c.session(title="keep", folder="real")
        self.assertIn("only works together with -f", self.c.run("rm", "--all")[1])
        self.assertIn("real folder", self.c.run("rm", "--all", "-f", "/")[1])
        rc, out = self.c.run("rm", "--all", "-f", "scratch")
        self.assertIn("must be confirmed in a terminal", out)
        self.assertIn("2 session(s)", self.c.run("ls", "-f", "scratch")[1])
        rc, out = self.c.run("rm", "--all", "-f", "scratch", "--force")
        self.assertEqual(rc, 0, out)
        self.assertIn("Deleted 2 of 2", out)
        self.assertTrue(self.exists(keep))

    def test_project_folder_cleanup(self):
        _, p1 = self.c.session(title="only", project="-only")
        (p1.parent / "memory").mkdir()
        _, p2 = self.c.session(title="mem", project="-mem")
        (p2.parent / "memory").mkdir()
        (p2.parent / "memory" / "note.md").write_text("keep me")
        self.c.session(title="a1", project="-shared")
        self.c.session(title="a2", project="-shared")
        for name in ("only", "mem", "a1"):
            self.c.run("rm", name, "-y")
        projects = {p.name for p in (self.c.dir / "projects").iterdir()}
        self.assertNotIn("-only", projects)
        self.assertIn("-mem", projects)
        self.assertTrue((self.c.dir / "projects" / "-mem" / "memory" / "note.md").exists())
        self.assertIn("-shared", projects)


CONVERSATION = [
    ("assistant", [{"type": "thinking", "thinking": "secret reasoning"},
                   {"type": "text", "text": "Let me check.\nSecond line."},
                   {"type": "tool_use", "id": "t1", "name": "Bash",
                    "input": {"command": "git status", "description": "Show status"}}]),
    ("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "On branch main\nclean"}]),
    ("assistant", [{"type": "tool_use", "id": "t2", "name": "Read",
                    "input": {"file_path": "/x/y.py"}}]),
    ("user", [{"type": "tool_result", "tool_use_id": "t2", "is_error": True,
               "content": "File does not exist."}]),
    ("user", "<command-name>/rename</command-name>\n<command-args>new-name</command-args>"),
    ("user", "<system-reminder>internal note</system-reminder>"),
    ("assistant", [{"type": "text", "text": "All done."}]),
]


class LogTest(FakeTest):
    def test_readable_conversation(self):
        self.c.session(title="conv", prompt="please check git", turns=CONVERSATION)
        rc, out = self.c.run("log", "conv")
        self.assertEqual(rc, 0)
        self.assertIn("── you", out)
        self.assertIn("please check git", out)
        self.assertIn("── claude", out)
        self.assertIn("→ Bash: git status", out)
        self.assertIn("→ Read: /x/y.py", out)
        self.assertIn("/rename new-name", out)
        self.assertIn("All done.", out)
        for hidden in ("secret reasoning", "internal note", "On branch main"):
            self.assertNotIn(hidden, out)

    def test_tools_and_tail(self):
        self.c.session(title="conv", turns=CONVERSATION)
        self.assertIn("← On branch main", self.c.run("log", "conv", "--tools")[1])
        out = self.c.run("log", "conv", "--tail", "1")[1]
        self.assertIn("All done.", out)
        self.assertNotIn("git status", out)


class WatchTest(FakeTest):
    def test_once(self):
        self.c.session(title="w", turns=CONVERSATION)
        rc, out = self.c.run("watch", "w", "--once")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"(?m)^\d\d:\d\d:\d\d  Bash\s+Show status$")
        self.assertRegex(out, r"(?m)^\d\d:\d\d:\d\d  says\s+Let me check\. …$")
        self.assertNotIn("does not exist", out)
        out = self.c.run("watch", "w", "--once", "--verbose")[1]
        self.assertIn("Second line.", out)
        self.assertRegex(out, r"(?m)^\d\d:\d\d:\d\d  !\s+File does not exist\.")

    def test_follows_open_sessions_live(self):
        sid, path = self.c.session(title="live-one")
        self.c.mark_open(sid)
        p = subprocess.Popen([CCTL, "watch", "--tail", "0"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, universal_newlines=True, env=self.c.env())
        try:
            time.sleep(2)
            with open(path, "a") as fh:
                fh.write(json.dumps({"type": "assistant", "timestamp": iso(time.time()),
                                     "message": {"content": [{"type": "tool_use", "name": "Edit",
                                                              "input": {"file_path": "/a/b.py"}}]}}) + "\n")
            time.sleep(2.5)
        finally:
            p.send_signal(signal.SIGINT)
            out, _ = p.communicate(timeout=10)
        self.assertIn("watching 1 open session(s): live-one", out)
        self.assertRegex(out, r"live-one\s+Edit\s+/a/b\.py")


class HelpTest(FakeTest):
    def test_overview_fits_80_columns(self):
        out = self.c.run("-h")[1]
        self.assertIn("Commands:", out)
        for line in out.splitlines():
            self.assertLessEqual(len(line), 80, line)

    def test_help_command_matches_dash_h(self):
        self.assertEqual(self.c.run("help")[1], self.c.run("-h")[1])
        for cmd in ("ls", "resume", "rm", "log", "watch"):
            self.assertEqual(self.c.run("help", cmd)[1], self.c.run(cmd, "-h")[1], cmd)

    def test_errors_and_version(self):
        rc, out = self.c.run("bogus")
        self.assertEqual(rc, 2)
        self.assertIn("unknown command 'bogus'", out)
        rc, out = self.c.run("rm", "--bogus")
        self.assertIn("usage: cctl rm", out)
        rc, out = self.c.run("-v")
        self.assertRegex(out, r"^cctl \d+\.\d+\.\d+")
        self.assertIn("product of Anthropic", out)


# ----------------------------------------------------------------- 2. real data format

@unittest.skipIf(os.environ.get("CCTL_SKIP_REAL") or not (REAL_DIR / "projects").is_dir(),
                 "no local Claude Code data (or CCTL_SKIP_REAL set)")
class RealFormatTest(unittest.TestCase):
    """Claude Code's own files still look the way cctl expects. Structure only."""

    @classmethod
    def setUpClass(cls):
        files = sorted((REAL_DIR / "projects").glob("*/*.jsonl"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        cls.files = files[:25]
        cls.entries = []
        for f in cls.files:
            with open(f, encoding="utf-8", errors="replace") as fh:
                cls.entries += [json.loads(line) for line in fh if line.strip()]

    def test_transcripts_are_where_cctl_looks(self):
        self.assertTrue(self.files, "no transcripts under projects/*/*.jsonl")

    def test_messages_have_the_fields_cctl_reads(self):
        msgs = [e for e in self.entries if e.get("type") in ("user", "assistant")]
        self.assertTrue(msgs, "no user/assistant entries")
        for e in msgs:
            self.assertIn("message", e)
            self.assertIsInstance(e["message"].get("content"), (str, list))
            self.assertRegex(e.get("timestamp", ""), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        self.assertTrue(any(e.get("cwd") for e in msgs), "no entry carries cwd")
        blocks = [b for e in msgs if isinstance(e["message"]["content"], list)
                  for b in e["message"]["content"] if isinstance(b, dict)]
        tool_uses = [b for b in blocks if b.get("type") == "tool_use"]
        for b in tool_uses:
            self.assertIn("name", b)
            self.assertIsInstance(b.get("input"), dict)

    def test_title_entries(self):
        for e in self.entries:
            if e.get("type") == "custom-title":
                self.assertIsInstance(e.get("customTitle"), str)
            if e.get("type") == "ai-title":
                self.assertIsInstance(e.get("aiTitle"), str)

    def test_running_session_records(self):
        recs = list((REAL_DIR / "sessions").glob("*.json"))
        if not recs:
            self.skipTest("no session records right now")
        for f in recs:
            rec = json.loads(f.read_text())
            self.assertIsInstance(rec.get("pid"), int)
            self.assertRegex(rec.get("sessionId", ""), r"^[0-9a-f-]{36}$")

    def test_cctl_reads_real_data(self):
        out = subprocess.run([CCTL, "ls", "--json"], stdout=subprocess.PIPE, universal_newlines=True,
                             timeout=60, check=True).stdout
        rows = json.loads(out)
        self.assertTrue(rows)
        self.assertTrue(all(r["session_id"] and "open" in r for r in rows))
        self.assertTrue(any(r["cwd"] for r in rows))


# ----------------------------------------------------------------- 3. live claude -p

@unittest.skipUnless(os.environ.get("CCTL_LIVE") and shutil.which("claude"),
                     "set CCTL_LIVE=1 (needs claude; uses a few tokens)")
class LiveTest(unittest.TestCase):
    def test_headless_session_end_to_end(self):
        work = Path(tempfile.mkdtemp(prefix="cctl-live-"))
        sid = str(uuid.uuid4())
        env = dict(os.environ, NO_COLOR="1")
        claude = subprocess.Popen(
            ["claude", "-p", "Use the Bash tool to run `sleep 3`, then `echo cctl-live-test`. "
             "Then reply with the single word: done",
             "--session-id", sid, "--allowedTools", "Bash", "--output-format", "text"],
            cwd=work, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        run = lambda *a: subprocess.run([CCTL, *a], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        universal_newlines=True, env=env, timeout=60).stdout
        try:
            seen_open = False
            for _ in range(30):
                time.sleep(1)
                if re.search(rf"(?m)^{sid[:8]}\s.*\bopen\b", run("ls", "-o")):
                    seen_open = True
                    break
            self.assertTrue(seen_open, "headless session never showed as open")
            claude.wait(timeout=120)
            watch = run("watch", sid, "--once", "--tail", "20")
            self.assertRegex(watch, r"Bash\s+")
            self.assertIn("→ Bash:", run("log", sid))
        finally:
            if claude.poll() is None:
                claude.kill()
            out = run("rm", sid, "--force")
            shutil.rmtree(work, ignore_errors=True)
        self.assertIn("deleted", out)
        self.assertNotIn(sid[:8], run("ls"))


if __name__ == "__main__":
    unittest.main()
