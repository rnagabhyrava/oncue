from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from codex_local_scheduler.cron import fields_for, matches
from codex_local_scheduler.runner import invocation
from codex_local_scheduler.runner import run_job, run_queued_job
from codex_local_scheduler.store import Store


class CronTests(unittest.TestCase):
    def test_matches_common_cron_forms(self):
        monday_at_four = datetime(2026, 9, 7, 16, 0)
        self.assertTrue(matches("0 16 * * 1", monday_at_four))
        self.assertTrue(matches("*/15 16 * * 1-5", monday_at_four))
        self.assertFalse(matches("1 16 * * 1", monday_at_four))
        self.assertFalse(matches("0 16 * * 0", monday_at_four))

    def test_builds_a_model_specific_codex_invocation(self):
        command, uses_shell = invocation({
            "runner": "codex", "model": "gpt-5.6-terra", "reasoning_effort": "medium",
            "command": "Write the weekly report.", "sandbox": "workspace-write", "auto_approve": 1,
        })
        self.assertFalse(uses_shell)
        self.assertEqual(command[0:4], ["codex", "exec", "--model", "gpt-5.6-terra"])
        self.assertIn("workspace-write", command)
        self.assertIn("--approve-for-me", command)
        self.assertIn('model_reasoning_effort="medium"', command)

    def test_day_of_month_and_day_of_week_use_cron_or_semantics(self):
        monday = datetime(2026, 9, 7, 16, 0)
        tuesday_the_first = datetime(2026, 9, 1, 16, 0)
        self.assertTrue(matches("0 16 1 * 1", monday))
        self.assertTrue(matches("0 16 1 * 1", tuesday_the_first))
        self.assertTrue(matches("0 16 * * 7", datetime(2026, 9, 6, 16, 0)))

    def test_validates_every_cron_field_before_matching(self):
        with self.assertRaisesRegex(ValueError, "outside 0-23"):
            fields_for("1 99 * * *")
        with self.assertRaisesRegex(ValueError, "outside 0-59"):
            matches("0,99 * * * *", datetime(2026, 9, 8, 0, 0))

    def test_timeout_marks_run_complete_and_writes_log(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            store = Store(root / "scheduler.sqlite3")
            store.initialize()
            store.add_project("demo", project)
            store.add_job("slow-job", "demo", "* * * * *", "printf started; sleep 2", None,
                          1, "command", None, None, "America/Chicago", "read-only", False)
            job = store.job("slow-job")
            result = run_job(store, job, root, datetime.now(timezone.utc))
            history = store.history("slow-job")
            store.close()
            self.assertEqual(result, "timed_out")
            self.assertEqual(history[0]["status"], "timed_out")
            self.assertIsNotNone(history[0]["finished_at"])
            self.assertIn("Timed out", Path(history[0]["output_path"]).read_text())

    def test_timeout_kills_a_child_that_ignores_sigterm(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            pid_file = root / "child.pid"
            child = (
                f"{sys.executable} -c \"import os,signal,time; "
                f"signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"open('{pid_file}', 'w').write(str(os.getpid())); time.sleep(30)\" & wait"
            )
            store = Store(root / "scheduler.sqlite3")
            store.initialize()
            store.add_project("demo", project)
            store.add_job("slow-child", "demo", "* * * * *", child, None, 1, "command", None,
                          None, "America/Chicago", "read-only", False)
            self.assertEqual(run_job(store, store.job("slow-child"), root, datetime.now(timezone.utc)), "timed_out")
            child_pid = int(pid_file.read_text())
            for _ in range(20):
                state = Path(f"/proc/{child_pid}/stat")
                if not state.exists() or state.read_text().split()[2] == "Z":
                    break
                time.sleep(0.05)
            else:
                os.kill(child_pid, signal.SIGKILL)
                self.fail("child process survived timeout cleanup")
            store.close()

    def test_recovery_closes_interrupted_runs(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            store = Store(root / "scheduler.sqlite3")
            store.initialize()
            store.add_project("demo", project)
            store.add_job("job", "demo", "* * * * *", "true", None, 10, "command", None,
                          None, "America/Chicago", "read-only", False)
            run_id = store.start_run(store.job("job")["id"], "2026-01-01T00:00:00+00:00")
            self.assertIsNotNone(run_id)
            self.assertEqual(store.recover_interrupted_runs(), 1)
            self.assertEqual(store.history("job")[0]["status"], "failed")
            store.close()

    def test_archiving_preserves_history_and_hides_job(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("project").mkdir()
            store = Store(root / "private" / "scheduler.sqlite3")
            store.initialize()
            store.add_project("demo", root / "project")
            store.add_job("job", "demo", "* * * * *", "true", None, 10, "command", None,
                          None, "America/Chicago", "read-only", False)
            store.start_run(store.job("job")["id"], "2026-01-01T00:00:00+00:00")
            self.assertTrue(store.archive_job("job"))
            self.assertIsNone(store.job("job"))
            self.assertEqual(store.history("job")[0]["status"], "running")
            self.assertEqual(len(store.jobs()), 0)
            self.assertEqual(len(store.jobs(include_archived=True)), 1)
            self.assertEqual((root / "private" / "scheduler.sqlite3").stat().st_mode & 0o777, 0o600)
            store.close()

    def test_pausing_or_archiving_skips_queued_runs(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("project").mkdir()
            store = Store(root / "scheduler.sqlite3")
            store.initialize()
            store.add_project("demo", root / "project")
            store.add_job("job", "demo", "* * * * *", "true", None, 10, "command", None,
                          None, "America/Chicago", "read-only", False)
            job_id = store.job("job")["id"]
            paused_run = store.queue_run(job_id, "2026-01-01T00:00:00+00:00")
            self.assertTrue(store.set_job_enabled("job", False))
            self.assertEqual(store.history("job")[0]["status"], "skipped")
            self.assertEqual(run_queued_job(store, paused_run, root), "already-claimed")
            self.assertTrue(store.set_job_enabled("job", True))
            archived_run = store.queue_run(job_id, "2026-01-02T00:00:00+00:00")
            self.assertTrue(store.archive_job("job"))
            self.assertEqual(store.history("job")[0]["status"], "skipped")
            self.assertEqual(run_queued_job(store, archived_run, root), "already-claimed")
            store.close()

    def test_auto_approval_requires_workspace_write(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("project").mkdir()
            store = Store(root / "scheduler.sqlite3")
            store.initialize()
            store.add_project("demo", root / "project")
            with self.assertRaisesRegex(ValueError, "workspace-write"):
                store.add_job("codex-job", "demo", "* * * * *", "do it", None, 10, "codex",
                              "gpt-5.6-terra", None, "America/Chicago", "read-only", True)
            with self.assertRaisesRegex(ValueError, "only to Codex"):
                store.add_job("command-job", "demo", "* * * * *", "true", None, 10, "command",
                              None, None, "America/Chicago", "workspace-write", False)
            store.close()

    def test_manual_run_leaves_overlapping_due_work_queued(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            data_dir = root / "data"
            store = Store(data_dir / "scheduler.sqlite3")
            store.initialize()
            store.add_project("demo", project)
            store.add_job("slow-job", "demo", "* * * * *", "sleep 2", None, 10, "command", None,
                          None, "America/Chicago", "read-only", False)
            store.close()
            command = [sys.executable, "-m", "codex_local_scheduler", "--data-dir", str(data_dir)]
            manual = subprocess.Popen(command + ["job", "run", "slow-job"], stdout=subprocess.PIPE, text=True)
            for _ in range(100):
                store = Store(data_dir / "scheduler.sqlite3")
                store.initialize()
                history = store.history("slow-job")
                store.close()
                if history:
                    break
                time.sleep(0.02)
            tick = subprocess.run(command + ["run-due"], capture_output=True, text=True, check=False)
            self.assertEqual(tick.returncode, 0)
            self.assertIn("queued-project-busy", tick.stdout)
            output, _ = manual.communicate(timeout=10)
            self.assertEqual(manual.returncode, 0, output)
            second_tick = subprocess.run(command + ["run-due"], capture_output=True, text=True, check=False)
            self.assertEqual(second_tick.returncode, 0)
            self.assertIn("succeeded", second_tick.stdout)
            store = Store(data_dir / "scheduler.sqlite3")
            self.assertEqual([row["status"] for row in store.history("slow-job")], ["succeeded", "succeeded"])
            store.close()

    def test_migrates_existing_run_history_to_queue_status_schema(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "scheduler.sqlite3"
            legacy = sqlite3.connect(database)
            legacy.executescript(
                """
                CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, path TEXT UNIQUE NOT NULL);
                CREATE TABLE jobs (id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, project_id INTEGER NOT NULL,
                    schedule TEXT NOT NULL, command TEXT NOT NULL, runner TEXT NOT NULL DEFAULT 'command', model TEXT,
                    reasoning_effort TEXT, timezone TEXT NOT NULL DEFAULT 'America/Chicago',
                    sandbox TEXT NOT NULL DEFAULT 'read-only', auto_approve INTEGER NOT NULL DEFAULT 0,
                    connection_id INTEGER, enabled INTEGER NOT NULL DEFAULT 1, archived INTEGER NOT NULL DEFAULT 0,
                    timeout_seconds INTEGER NOT NULL DEFAULT 1800, last_scheduled_at TEXT);
                CREATE TABLE runs (id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, scheduled_for TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT,
                    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed', 'timed_out', 'skipped')),
                    exit_code INTEGER, output_path TEXT, error TEXT, UNIQUE(job_id, scheduled_for));
                INSERT INTO projects(id, slug, path) VALUES (1, 'demo', '/tmp');
                INSERT INTO jobs(id, slug, project_id, schedule, command) VALUES (1, 'legacy', 1, '* * * * *', 'true');
                INSERT INTO runs(id, job_id, scheduled_for, status) VALUES (1, 1, '2026-01-01T00:00:00+00:00', 'succeeded');
                """
            )
            legacy.commit()
            legacy.close()
            store = Store(database)
            store.initialize()
            self.assertEqual(store.history("legacy")[0]["status"], "succeeded")
            self.assertIsNotNone(store.queue_run(1, "2026-01-02T00:00:00+00:00"))
            self.assertEqual(store.queued_runs()[0]["id"], 2)
            store.close()
