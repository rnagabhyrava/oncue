import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from cloud_service.app import create_app
    CLOUD_AVAILABLE = True
except ImportError:
    CLOUD_AVAILABLE = False


@unittest.skipUnless(CLOUD_AVAILABLE, "cloud service dependencies are optional")
class CloudServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        database = Path(self.temporary.name) / "cloud.sqlite3"

        def verify(token):
            if token == "owner-a":
                return {"iss": "https://issuer/", "sub": "google-oauth2|a", "email": "a@example.test"}
            if token == "owner-b":
                return {"iss": "https://issuer/", "sub": "google-oauth2|b", "email": "b@example.test"}
            raise ValueError("bad token")

        self.client = TestClient(create_app(f"sqlite:///{database}", verify))
        self.owner = {"Authorization": "Bearer owner-a"}
        enrolled = self.client.post("/v1/computers/enroll", headers=self.owner,
            json={"installation_id": "00000000-0000-0000-0000-000000000001", "name": "Laptop"})
        self.assertEqual(enrolled.status_code, 201)
        self.computer_id = enrolled.json()["computer_id"]
        self.agent = {"Authorization": "Bearer " + enrolled.json()["credential"]}

    def tearDown(self):
        self.temporary.cleanup()

    def test_account_ownership_and_synced_history(self):
        body = {"computer_id": self.computer_id, "sequence": 1,
                "snapshot": {"jobs": [{"slug": "daily", "title": "Daily"}], "runs": [], "messages": []}}
        self.assertEqual(self.client.post("/v1/agent/sync", headers=self.agent, json=body).status_code, 200)
        self.assertEqual(self.client.get("/v1/history", headers=self.owner).json()["computers"][0]["snapshot"]["jobs"][0]["slug"], "daily")
        self.assertEqual(self.client.get("/v1/history", headers={"Authorization": "Bearer owner-b"}).json()["computers"], [])
        denied = self.client.post("/v1/commands", headers={"Authorization": "Bearer owner-b"},
                                  json={"computer_id": self.computer_id, "action": "run", "task_slug": "daily"})
        self.assertEqual(denied.status_code, 404)

    def test_command_delivery_ack_and_revocation(self):
        command = self.client.post("/v1/commands", headers=self.owner,
            json={"computer_id": self.computer_id, "action": "run", "task_slug": "daily"})
        self.assertEqual(command.status_code, 202)
        command_id = command.json()["id"]
        polled = self.client.post("/v1/agent/sync", headers=self.agent,
                                  json={"computer_id": self.computer_id, "sequence": 0}).json()
        self.assertEqual(polled["commands"][0]["id"], command_id)
        self.assertEqual(self.client.post(f"/v1/agent/commands/{command_id}/ack", headers=self.agent,
                                          json={"status": "applied", "result": {"run_id": 7}}).status_code, 200)
        self.assertEqual(self.client.delete(f"/v1/computers/{self.computer_id}", headers=self.owner).status_code, 200)
        self.assertEqual(self.client.post("/v1/agent/sync", headers=self.agent,
                                          json={"computer_id": self.computer_id, "sequence": 0}).status_code, 401)

    def test_expired_and_invalid_credentials_are_rejected(self):
        self.assertEqual(self.client.get("/v1/account").status_code, 401)
        self.assertEqual(self.client.get("/v1/account", headers={"Authorization": "Bearer expired"}).status_code, 401)

    def test_same_sequence_cannot_replace_history(self):
        first = {"computer_id": self.computer_id, "sequence": 1, "snapshot": {"jobs": []}}
        self.assertEqual(self.client.post("/v1/agent/sync", headers=self.agent, json=first).status_code, 200)
        changed = {"computer_id": self.computer_id, "sequence": 1, "snapshot": {"jobs": [{"slug": "other"}]}}
        self.assertEqual(self.client.post("/v1/agent/sync", headers=self.agent, json=changed).status_code, 409)


if __name__ == "__main__":
    unittest.main()
