import json
import re
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from oncue.dashboard import _handler
from oncue.remote import ACCOUNT_FILE, OUTBOX_FILE, _snapshot, sync_once
from oncue.store import Store
from oncue.tasks import save_task


class RemoteSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.database = self.data_dir / "scheduler.sqlite3"
        self.store = Store(self.database)
        self.store.initialize()
        self.slug = save_task(self.store, {
            "title": "Remote test", "instructions": "Summarize the day",
            "schedule": "0 9 * * *", "timezone": "UTC", "runner": "codex",
            "provider": "codex", "model": "test-model", "enabled": True,
        })
        (self.data_dir / ACCOUNT_FILE).write_text(json.dumps({
            "computer_id": "computer-1", "credential": "device-secret",
            "account_subject": "issuer\nsubject",
        }))

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_snapshot_excludes_local_paths_and_diagnostics(self):
        payload = _snapshot(self.store)
        self.assertEqual(payload["jobs"][0]["instructions"], "Summarize the day")
        encoded = json.dumps(payload)
        self.assertNotIn(str(self.data_dir), encoded)
        self.assertNotIn("config_snapshot", encoded)
        self.assertNotIn("output_path", encoded)

    def test_replayed_remote_run_is_applied_once(self):
        command = {"id": "command-1", "task_slug": self.slug, "action": "run",
                   "payload": {}, "expected_revision": 0}
        acknowledgements = []

        def remote_call(data_dir, path, **kwargs):
            if path == "/v1/agent/sync":
                return {"server_time": "2026-09-09T12:00:00+00:00", "commands": [command]}
            acknowledgements.append(kwargs["payload"])
            return {"ok": True}

        self.store.close()
        with patch("oncue.remote._request", side_effect=remote_call):
            self.assertTrue(sync_once(self.database))
            self.assertTrue(sync_once(self.database))
        self.store = Store(self.database)
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
        self.assertEqual([value["status"] for value in acknowledgements], ["applied", "applied"])
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM remote_commands").fetchone()[0], 1)

    def test_remote_message_creates_the_server_assigned_task(self):
        command = {"id": "command-create", "task_slug": "remote-draft-1234", "action": "message",
                   "payload": {"text": "Every day at 9 summarize the news", "options": {}},
                   "expected_revision": None}

        def remote_call(data_dir, path, **kwargs):
            if path == "/v1/agent/sync":
                return {"server_time": "2026-09-09T12:00:00+00:00", "commands": [command]}
            return {"ok": True}

        self.store.close()
        with patch("oncue.remote._request", side_effect=remote_call):
            self.assertTrue(sync_once(self.database))
        self.store = Store(self.database)
        self.assertIsNotNone(self.store.job("remote-draft-1234"))
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM runs WHERE scheduled_for='remote:command-create'").fetchone()[0], 1)

    def test_stale_remote_edit_is_rejected_without_mutation(self):
        self.store.set_job_enabled(self.slug, False)
        command = {"id": "command-stale", "task_slug": self.slug, "action": "resume",
                   "payload": {}, "expected_revision": 0}
        acknowledgements = []

        def remote_call(data_dir, path, **kwargs):
            if path == "/v1/agent/sync":
                return {"server_time": "2026-09-09T12:00:00+00:00", "commands": [command]}
            acknowledgements.append(kwargs["payload"]); return {"ok": True}

        self.store.close()
        with patch("oncue.remote._request", side_effect=remote_call):
            self.assertTrue(sync_once(self.database))
        self.store = Store(self.database)
        self.assertFalse(self.store.job(self.slug)["enabled"])
        self.assertEqual(acknowledgements[0]["status"], "rejected")

    def test_unacknowledged_snapshot_reuses_durable_sequence(self):
        sent = []

        def remote_call(data_dir, path, **kwargs):
            sent.append(kwargs["payload"])
            if len(sent) == 1:
                raise ValueError("offline")
            return {"server_time": "2026-09-09T12:00:00+00:00",
                    "acknowledged_sequence": kwargs["payload"]["sequence"], "commands": []}

        self.store.close()
        with patch("oncue.remote._request", side_effect=remote_call):
            self.assertFalse(sync_once(self.database))
            outbox = json.loads((self.data_dir / OUTBOX_FILE).read_text())
            self.assertTrue(sync_once(self.database))
        self.assertEqual(sent[0]["sequence"], sent[1]["sequence"])
        self.assertEqual(sent[1]["snapshot"], outbox["snapshot"])
        self.assertFalse((self.data_dir / OUTBOX_FILE).exists())
        self.store = Store(self.database)

    def test_local_dashboard_requires_a_verified_browser_account(self):
        environment = {
            "ONCUE_CLOUD_URL": "https://cloud.example.test",
            "ONCUE_AUTH0_DOMAIN": "login.example.test",
            "ONCUE_AUTH0_CLIENT_ID": "client",
            "ONCUE_AUTH0_AUDIENCE": "https://api.example.test",
        }
        with patch.dict("os.environ", environment), \
             patch("oncue.remote.verify_session", return_value={"claimed": True}), \
             patch("oncue.remote.account_state", return_value={"claimed": True, "configured": True}):
            server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self.database))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/") as response:
                    csrf = re.search('name="csrf-token" content="([^"]+)"', response.read().decode())[1]
                with self.assertRaises(HTTPError) as denied:
                    urlopen(Request(base + "/api/tasks", headers={"X-CSRF-Token": csrf}))
                self.assertEqual(denied.exception.code, 401)
                denied.exception.close()
                session = Request(base + "/api/account/session", data=b"{}", method="POST", headers={
                    "Content-Type": "application/json", "X-CSRF-Token": csrf,
                    "Authorization": "Bearer header.payload.signature", "Origin": base,
                })
                with urlopen(session) as response: self.assertEqual(response.status, 200)
                with urlopen(Request(base + "/api/tasks", headers={
                    "X-CSRF-Token": csrf, "Authorization": "Bearer header.payload.signature"})) as response:
                    self.assertEqual(response.status, 200)
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
