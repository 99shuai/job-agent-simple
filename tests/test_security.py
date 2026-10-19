"""本地接口安全边界测试，不连接招聘网站、不调用真实模型。"""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from job_agent import api
from job_agent.llm import analyze_jd

CONTENT = "负责 Python 开发和接口维护，需要理解 HTTP 与 JSON。"


class LocalSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app, base_url="http://127.0.0.1:8000")
        self.addCleanup(self.client.close)

    def test_untrusted_host_is_rejected(self):
        with patch("job_agent.api.check_boss_browser") as browser:
            response = self.client.get("/health", headers={"Host": "evil.example"})
        self.assertEqual(response.status_code, 400)
        browser.assert_not_called()

    def test_cross_origin_post_cannot_open_browser(self):
        with patch("job_agent.api.open_boss_page") as open_page:
            response = self.client.post("/browser/open", headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)
        open_page.assert_not_called()

    def test_cross_origin_stream_cannot_call_search(self):
        with patch("job_agent.api.search_jobs") as search:
            response = self.client.post("/jobs/search-analyze-stream", json={"city": "郑州", "keyword": "AI"},
                                        headers={"Origin": "http://127.0.0.1:9000"})
        self.assertEqual(response.status_code, 403)
        search.assert_not_called()

    def test_cross_site_get_cannot_spend_search_quota(self):
        with patch("job_agent.api.search_jobs") as search:
            response = self.client.get("/jobs", params={"city": "郑州", "keyword": "AI"},
                                       headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(response.status_code, 403)
        search.assert_not_called()

    def test_null_origin_is_rejected(self):
        with patch("job_agent.api.analyze_jd") as model:
            response = self.client.post("/jd", json={"title": "开发", "content": CONTENT}, headers={"Origin": "null"})
        self.assertEqual(response.status_code, 403)
        model.assert_not_called()

    def test_same_origin_and_cli_requests_work(self):
        with patch("job_agent.api.analyze_jd", return_value="模拟分析") as model:
            for headers in ({}, {"Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "same-origin"}):
                response = self.client.post("/jd", json={"title": "开发", "content": CONTENT}, headers=headers)
                self.assertEqual(response.status_code, 200)
        self.assertEqual(model.call_count, 2)

    def test_oversized_jd_and_title_stop_before_model(self):
        with patch("job_agent.api.analyze_jd") as model:
            for payload in ({"title": "x"*201, "content": CONTENT}, {"title": "开发", "content": "x"*30001}):
                self.assertEqual(self.client.post("/jd", json=payload).status_code, 422)
        model.assert_not_called()

    def test_llm_adapter_also_rejects_oversized_input(self):
        with patch("job_agent.llm.call_deepseek") as model:
            for title,content in (("x"*201, CONTENT), ("开发", "x"*30001)):
                with self.assertRaises(ValueError):
                    analyze_jd(title,content)
        model.assert_not_called()

    def test_home_has_security_headers_and_no_inline_script_permission(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        policy = response.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'",policy)
        self.assertNotIn("unsafe-inline",policy)
        self.assertIn("frame-ancestors 'none'",policy)

    def test_docs_remain_available(self):
        response = self.client.get("/docs")
        self.assertEqual(response.status_code,200)
        self.assertNotIn("Content-Security-Policy",response.headers)


if __name__ == "__main__":
    unittest.main()
