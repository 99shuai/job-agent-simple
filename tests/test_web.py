"""网页、准备动作与进度接口测试，全部模拟外部服务。"""
import json
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from job_agent import api

URL = "https://www.zhipin.com/job_detail/example123.html"
CONTENT = "负责 Python 大模型应用开发，使用 FastAPI 提供 HTTP 接口。"


class WebTests(unittest.TestCase):
    def setUp(self):
        guards = {
            "search_jobs": [{"title": "AI 开发", "url": URL, "snippet": ""}],
            "check_boss_browser": None,
            "open_boss_page": None,
            "read_boss_job_links": [],
            "open_boss_job": None,
            "read_boss_jd": {"title": "AI 开发", "url": URL, "content": CONTENT},
            "analyze_jd": "### 技术要求\n- **明确要求**：Python\n- 薪资待核实",
        }
        guard = patch.dict(os.environ, {"SERPAPI_API_KEY": "offline-search-secret", "DEEPSEEK_API_KEY": "offline-model-secret"})
        guard.start()
        self.addCleanup(guard.stop)
        for name, value in guards.items():
            guard = patch("job_agent.api." + name, return_value=value)
            setattr(self, name, guard.start())
            self.addCleanup(guard.stop)
        self.client = TestClient(api.app, base_url="http://127.0.0.1")
        self.addCleanup(self.client.close)
        self.query = {"city": "郑州", "keyword": "AI", "max_results": 2}

    def events(self):
        response = self.client.post("/jobs/search-analyze-stream", json=self.query)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/x-ndjson", response.headers["content-type"])
        return [json.loads(line) for line in response.text.splitlines() if line.strip()]

    def test_home_and_assets_work_without_api_calls(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("search-form", response.text)
        self.assertIn("jd-form", response.text)
        for name in ("app.js", "style.css", "icon.svg"):
            self.assertEqual(self.client.get("/static/" + name).status_code, 200)
        self.search_jobs.assert_not_called()
        self.analyze_jd.assert_not_called()
        self.open_boss_page.assert_not_called()

    def test_health_reveals_flags_but_never_keys(self):
        response = self.client.get("/health")
        self.assertEqual(response.json(), {
            "app": api.APP_ID, "serpapi_configured": True, "deepseek_configured": True, "browser_ready": True,
        })
        self.assertNotIn("offline-search-secret", response.text)
        self.assertNotIn("offline-model-secret", response.text)
        self.search_jobs.assert_not_called()
        self.analyze_jd.assert_not_called()

    def test_health_handles_missing_browser_and_keys(self):
        self.check_boss_browser.side_effect = RuntimeError("未启动")
        with patch.dict(os.environ, {"SERPAPI_API_KEY": "", "DEEPSEEK_API_KEY": ""}):
            result = self.client.get("/health").json()
        self.assertFalse(result["serpapi_configured"])
        self.assertFalse(result["deepseek_configured"])
        self.assertFalse(result["browser_ready"])

    def test_browser_button_only_opens_fixed_boss_home(self):
        self.assertEqual(self.client.post("/browser/open").status_code, 200)
        self.open_boss_page.assert_called_once_with("https://www.zhipin.com/")
        self.analyze_jd.assert_not_called()
        self.search_jobs.assert_not_called()

    def test_browser_button_failure_is_controlled(self):
        self.open_boss_page.side_effect = RuntimeError("未找到 Chrome")
        response = self.client.post("/browser/open")
        self.assertEqual(response.status_code, 503)
        self.assertIn("Chrome", response.json()["detail"])

    def test_stream_progress_precedes_job_and_has_final_result(self):
        events = self.events()
        kinds = [item["type"] for item in events]
        self.assertEqual(kinds, ["progress", "progress", "progress", "progress", "job", "result"])
        self.assertEqual([item["stage"] for item in events if item["type"] == "progress"], ["search", "filter", "jd", "analysis"])
        self.assertEqual(events[-1]["data"]["count"], 1)
        self.assertEqual(events[-1]["data"]["results"][0]["url"], URL)
        self.search_jobs.assert_called_once_with("郑州", "AI", 5)
        self.analyze_jd.assert_called_once_with("AI 开发", CONTENT)

    def test_stream_and_json_return_identical_final_data(self):
        streamed = self.events()[-1]["data"]
        ordinary = self.client.post("/jobs/search-analyze", json=self.query).json()
        self.assertEqual(streamed, ordinary)

    def test_invalid_stream_request_never_searches(self):
        response = self.client.post("/jobs/search-analyze-stream", json=dict(self.query, max_results=6))
        self.assertEqual(response.status_code, 422)
        self.search_jobs.assert_not_called()
        self.analyze_jd.assert_not_called()

    def test_missing_key_stops_before_browser_and_paid_search(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            events = self.events()
            response = self.client.post("/jobs/search-analyze", json=self.query)
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["status_code"], 503)
        self.assertIn("DEEPSEEK_API_KEY", events[-1]["detail"])
        self.assertEqual(response.status_code, 503)
        self.check_boss_browser.assert_not_called()
        self.search_jobs.assert_not_called()

    def test_stream_browser_failure_is_error_event_without_retries(self):
        self.check_boss_browser.side_effect = RuntimeError("请先登录")
        events = self.events()
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["status_code"], 503)
        self.check_boss_browser.assert_called_once()
        self.search_jobs.assert_not_called()

    def test_stream_no_match_never_calls_model(self):
        self.search_jobs.return_value = []
        result = self.events()[-1]["data"]
        self.assertEqual(result["status"], "no_matching_job")
        self.assertEqual(result["results"], [])
        self.analyze_jd.assert_not_called()

    def test_stream_partial_result_keeps_first_job_and_stops(self):
        second = "https://www.zhipin.com/job_detail/second456.html"
        self.search_jobs.return_value = [
            {"title": "AI 开发", "url": URL, "snippet": ""},
            {"title": "AI 后端", "url": second, "snippet": ""},
        ]
        self.read_boss_jd.side_effect = [
            {"title": "AI 开发", "url": URL, "content": CONTENT}, RuntimeError("需要验证"),
        ]
        events = self.events()
        self.assertEqual(len([item for item in events if item["type"] == "job"]), 1)
        final = events[-1]["data"]
        self.assertEqual((final["status"], final["count"]), ("partial", 1))
        self.assertEqual(final["errors"][0]["url"], second)
        self.analyze_jd.assert_called_once()
        self.read_boss_jd.assert_called_with(second, wait_for_ready=True)

    def test_busy_request_never_starts_a_second_analysis(self):
        with api._operation():
            response = self.client.post("/jd", json={"title": "AI 开发", "content": CONTENT})
            events = self.events()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(events[-1]["status_code"], 409)
        self.search_jobs.assert_not_called()
        self.analyze_jd.assert_not_called()
        # 锁在请求结束后释放，下一次正常请求能够执行。
        self.assertEqual(self.client.post("/jd", json={"title": "AI 开发", "content": CONTENT}).status_code, 200)

    def test_unexpected_stream_error_hides_raw_exception(self):
        self.search_jobs.side_effect = Exception("offline-model-secret private diagnostic")
        events = self.events()
        self.assertEqual(events[-1]["status_code"], 500)
        self.assertNotIn("offline-model-secret", str(events))
        self.assertNotIn("private diagnostic", str(events))
        self.analyze_jd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
