"""FastAPI 离线测试：替代真实搜索，不消耗 API 额度。"""

import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from job_agent.api import app


class SearchAPITests(unittest.TestCase):
    def setUp(self):
        self.result = {"title": "测试 AI Agent 岗位", "url": "https://example.com/job/1", "snippet": "Python"}
        mock = patch("job_agent.api.search_jobs", return_value=[self.result])
        self.search = mock.start()
        self.addCleanup(mock.stop)
        self.client = TestClient(app, base_url="http://127.0.0.1")
        self.addCleanup(self.client.close)

    def test_success_trims_inputs_and_uses_default_limit(self):
        response = self.client.get("/jobs", params={"city": " 郑州 ", "keyword": " AI Agent "})
        self.assertEqual(response.status_code, 200)
        self.search.assert_called_once_with("郑州", "AI Agent", 3)
        self.assertEqual(response.json(), {
            "city": "郑州", "keyword": "AI Agent", "count": 1, "results": [self.result],
        })

    def test_valid_quantity_boundaries(self):
        for quantity in (1, 20):
            with self.subTest(quantity=quantity):
                self.search.reset_mock()
                response = self.client.get("/jobs", params={"city": "郑州", "keyword": "Python", "max_results": quantity})
                self.assertEqual(response.status_code, 200)
                self.search.assert_called_once_with("郑州", "Python", quantity)

    def test_invalid_inputs_never_call_search(self):
        cases = [
            {}, {"city": "郑州"}, {"keyword": "Python"},
            {"city": "", "keyword": "Python"},
            {"city": "郑州", "keyword": ""},
            {"city": "   ", "keyword": "Python"},
            {"city": "郑州", "keyword": " \t "},
            {"city": "郑" * 31, "keyword": "Python"},
            {"city": "郑州", "keyword": "a" * 101},
        ]
        cases += [{"city": "郑州", "keyword": "Python", "max_results": value}
                  for value in (0, -1, 21, "abc", "1.5")]
        for params in cases:
            with self.subTest(params=params):
                self.search.reset_mock()
                response = self.client.get("/jobs", params=params)
                self.assertEqual(response.status_code, 422)
                self.assertIn("detail", response.json())
                self.search.assert_not_called()

    def test_empty_results_are_successful(self):
        self.search.return_value = []
        response = self.client.get("/jobs", params={"city": "郑州", "keyword": "Python"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)
        self.assertEqual(response.json()["results"], [])
        self.assertEqual(self.search.call_count, 1)

    def test_upstream_error_is_503_without_exposing_details(self):
        self.search.side_effect = RuntimeError("private-test-key / raw upstream error")
        response = self.client.get("/jobs", params={"city": "郑州", "keyword": "Python"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("SERPAPI_API_KEY", response.json()["detail"])
        self.assertNotIn("private-test-key", response.text)
        self.assertNotIn("raw upstream error", response.text)
        self.assertEqual(self.search.call_count, 1)

    def test_search_parameter_error_is_400(self):
        self.search.side_effect = ValueError("internal detail")
        response = self.client.get("/jobs", params={"city": "郑州", "keyword": "Python"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("internal detail", response.text)
        self.assertEqual(self.search.call_count, 1)

    def test_unexpected_error_is_500_without_exposing_details(self):
        self.search.side_effect = Exception("private-test-key")
        with TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False) as client:
            response = client.get("/jobs", params={"city": "郑州", "keyword": "Python"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private-test-key", response.text)
        self.assertEqual(self.search.call_count, 1)


    def test_filter_keeps_title_or_snippet_matches_and_updates_count(self):
        title_match = {"title": "PYTHON intern", "url": "https://example.com/1", "snippet": "API"}
        snippet_match = {"title": "Backend intern", "url": "https://example.com/2", "snippet": "Use Python"}
        unrelated = {"title": "Java intern", "url": "https://example.com/3", "snippet": "Spring"}
        self.search.return_value = [title_match, snippet_match, unrelated]
        response = self.client.get("/jobs", params={"city": "test-city", "keyword": "python"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [title_match, snippet_match])
        self.assertEqual(response.json()["count"], 2)
        self.search.assert_called_once()

    def test_filter_can_remove_all_results_without_another_search(self):
        self.search.return_value = [{"title": "Java intern", "url": "https://example.com/java", "snippet": "Spring"}]
        response = self.client.get("/jobs", params={"city": "test-city", "keyword": "Python"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])
        self.assertEqual(response.json()["count"], 0)
        self.search.assert_called_once()


class JobAnalysisAPITests(unittest.TestCase):
    def setUp(self):
        reader = patch("job_agent.api.read_boss_jd", return_value={
            "title": "Mock job",
            "url": "https://www.zhipin.com/job_detail/example123.html",
            "content": "Mock Python API development requirements.",
        })
        self.reader = reader.start()
        self.addCleanup(reader.stop)
        model = patch("job_agent.api.analyze_jd", return_value="Mock analysis")
        self.model = model.start()
        self.addCleanup(model.stop)
        prompt = patch("builtins.input", side_effect=AssertionError("API must not wait for terminal input"))
        self.prompt = prompt.start()
        self.addCleanup(prompt.stop)
        launch = patch("subprocess.Popen", side_effect=AssertionError("API must not launch a browser"))
        launch.start()
        self.addCleanup(launch.stop)
        self.client = TestClient(app, base_url="http://127.0.0.1")
        self.addCleanup(self.client.close)
        self.payload = {"url": "https://www.zhipin.com/job_detail/example123.html"}

    def test_reads_then_analyzes_once_and_preserves_link(self):
        response = self.client.post("/jobs/analyze", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "title": "Mock job", "url": self.payload["url"], "analysis": "Mock analysis",
        })
        self.reader.assert_called_once_with(self.payload["url"])
        self.model.assert_called_once_with("Mock job", "Mock Python API development requirements.")
        self.prompt.assert_not_called()

    def test_invalid_request_body_never_reads_or_calls_model(self):
        for payload in ({}, {"url": None}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/jobs/analyze", json=payload).status_code, 422)
        self.reader.assert_not_called()
        self.model.assert_not_called()

    def test_unsupported_link_is_422_without_model_call(self):
        self.reader.side_effect = ValueError("Unsupported job link")
        response = self.client.post("/jobs/analyze", json=self.payload)
        self.assertEqual(response.status_code, 422)
        self.reader.assert_called_once()
        self.model.assert_not_called()

    def test_browser_failure_is_503_and_stops_before_model(self):
        self.reader.side_effect = RuntimeError("Browser not ready")
        response = self.client.post("/jobs/analyze", json=self.payload)
        self.assertEqual(response.status_code, 503)
        self.reader.assert_called_once()
        self.model.assert_not_called()

    def test_incomplete_jd_is_409_without_model_call(self):
        for title, content in (("", "Full mock job content."), ("Mock job", "short")):
            with self.subTest(title=title, content=content):
                self.reader.return_value = {"title": title, "content": content, "url": self.payload["url"]}
                response = self.client.post("/jobs/analyze", json=self.payload)
                self.assertEqual(response.status_code, 409)
        self.model.assert_not_called()

    def test_model_failure_is_503_without_retry(self):
        self.model.side_effect = RuntimeError("Mock model failure")
        response = self.client.post("/jobs/analyze", json=self.payload)
        self.assertEqual(response.status_code, 503)
        self.reader.assert_called_once()
        self.model.assert_called_once()


if __name__ == "__main__":
    unittest.main()
