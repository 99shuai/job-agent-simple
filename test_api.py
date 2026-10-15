"""FastAPI 离线测试：替代真实搜索，不消耗 API 额度。"""

import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from api_demo import app


class SearchAPITests(unittest.TestCase):
    def setUp(self):
        self.result = {"title": "测试岗位", "url": "https://example.com/job/1", "snippet": "Python"}
        mock = patch("api_demo.search_jobs", return_value=[self.result])
        self.search = mock.start()
        self.addCleanup(mock.stop)
        self.client = TestClient(app)
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
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/jobs", params={"city": "郑州", "keyword": "Python"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private-test-key", response.text)
        self.assertEqual(self.search.call_count, 1)


if __name__ == "__main__":
    unittest.main()
