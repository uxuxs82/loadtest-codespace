import importlib
import os
import tempfile
import time
import unittest


class AppTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["LOADTEST_DATA_DIR"] = self.temp.name
        os.environ["K6_BIN"] = "/bin/echo"
        import app as app_module
        self.module = importlib.reload(app_module)
        self.client = self.module.app.test_client()

    def tearDown(self):
        self.temp.cleanup()
        os.environ.pop("LOADTEST_DATA_DIR", None)
        os.environ.pop("K6_BIN", None)

    def wait_for(self, status, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self.client.get("/status").get_json()
            if data["status"] == status:
                return data
            time.sleep(0.02)
        self.fail(f"status {status} not reached")

    def test_health(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["k6"])

    def test_rejects_bad_target(self):
        response = self.client.post(
            "/start",
            json={"target": "ftp://example.com", "vus": 1, "duration_minutes": 1},
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_private_target(self):
        response = self.client.post(
            "/start",
            json={"target": "http://127.0.0.1/", "vus": 1, "duration_minutes": 1},
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_long_single_run(self):
        response = self.client.post(
            "/start",
            json={"target": "https://example.com/", "vus": 1, "duration_minutes": 601},
        )
        self.assertEqual(response.status_code, 400)

    def test_single_run(self):
        response = self.client.post(
            "/start",
            json={
                "target": "https://example.com/",
                "vus": 1,
                "duration_minutes": 1,
                "ramp_up_seconds": 0,
                "think_time_seconds": 0,
            },
        )
        self.assertEqual(response.status_code, 202)
        data = self.wait_for("completed")
        self.assertEqual(data["exit_code"], 0)

    def test_campaign(self):
        response = self.client.post(
            "/start-campaign",
            json={
                "target": "https://example.com/",
                "vus": 1,
                "duration_minutes": 1000,
                "total_minutes": 2,
                "chunk_minutes": 1,
                "ramp_up_seconds": 0,
                "think_time_seconds": 0,
            },
        )
        self.assertEqual(response.status_code, 202)
        data = self.wait_for("completed")
        self.assertEqual(data["campaign"]["completed_minutes"], 1)
        self.assertEqual(data["campaign"]["status"], "paused")
        response = self.client.post("/continue")
        self.assertEqual(response.status_code, 202)
        data = self.wait_for("completed")
        self.assertEqual(data["campaign"]["completed_minutes"], 2)
        self.assertEqual(data["campaign"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
