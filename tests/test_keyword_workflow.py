"""关键词到 JD 分析的离线测试，不启动浏览器、不调用真实 API。"""

import io
import os
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch
from urllib.error import URLError

from fastapi.testclient import TestClient
from playwright.sync_api import Error
from job_agent.api import app
from job_agent import boss

LIST_URL = "https://www.zhipin.com/zhaopin/example~~/"
JOB_URL = "https://www.zhipin.com/job_detail/example123.html"
SECOND_JOB = "https://www.zhipin.com/job_detail/second456.html"
CONTENT = "模拟岗位 JD：负责 AI 应用接口开发，需要 Python 和 HTTP 基础。"


class KeywordWorkflowTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"SERPAPI_API_KEY": "offline-key", "DEEPSEEK_API_KEY": "offline-key"})
        env.start()
        self.addCleanup(env.stop)
        self.search_result = {"title": "AI 招聘列表", "url": LIST_URL, "snippet": "AI 开发"}
        self.candidate = {"title": "AI 开发", "url": JOB_URL, "snippet": ""}
        self.jd = {"title": "AI 岗位详情", "url": JOB_URL, "content": CONTENT}
        specs = [
            ("check_boss_browser", None),
            ("search_jobs", [self.search_result]),
            ("open_boss_page", None),
            ("read_boss_job_links", [self.candidate]),
            ("open_boss_job", None),
            ("read_boss_jd", self.jd),
            ("analyze_jd", "模拟分析"),
        ]
        self.trace = MagicMock()
        for name, result in specs:
            guard = patch("job_agent.api." + name, return_value=result)
            mock = guard.start()
            self.addCleanup(guard.stop)
            setattr(self, name, mock)
            self.trace.attach_mock(mock, name)
        for target in ("builtins.input", "subprocess.Popen"):
            guard = patch(target, side_effect=AssertionError("离线接口测试不能交互或打开浏览器"))
            guard.start()
            self.addCleanup(guard.stop)
        self.client = TestClient(app, base_url="http://127.0.0.1")
        self.addCleanup(self.client.close)
        self.payload = {"city": "郑州", "keyword": "AI"}

    def test_keyword_to_list_to_jd_to_analysis_in_order(self):
        response = self.client.post("/jobs/search-analyze", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(response.json()["results"][0]["url"], JOB_URL)
        self.assertEqual(response.json()["results"][0]["analysis"], "模拟分析")
        self.assertEqual(self.trace.mock_calls, [
            call.check_boss_browser(),
            call.search_jobs("郑州", "AI", 5),
            call.open_boss_page(LIST_URL),
            call.read_boss_job_links(LIST_URL, 5),
            call.open_boss_job(JOB_URL),
            call.read_boss_jd(JOB_URL, wait_for_ready=True),
            call.analyze_jd("AI 岗位详情", CONTENT),
        ])

    def test_direct_details_are_deduplicated_and_all_are_analyzed(self):
        self.search_jobs.return_value = [
            self.candidate,
            dict(self.candidate, url=JOB_URL + "?source=duplicate"),
            dict(self.candidate, url=SECOND_JOB),
        ]
        response = self.client.post("/jobs/search-analyze", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.open_boss_page.assert_not_called()
        self.read_boss_job_links.assert_not_called()
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(self.open_boss_job.call_args_list, [call(JOB_URL), call(SECOND_JOB)])
        self.assertEqual(self.read_boss_jd.call_count, 2)
        self.assertEqual(self.analyze_jd.call_count, 2)

    def test_no_eligible_source_does_not_open_or_analyze(self):
        self.search_jobs.return_value = [
            {"title": "AI", "url": "https://example.com/jobs", "snippet": ""}
        ]
        response = self.client.post("/jobs/search-analyze", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "no_matching_job")
        self.assertEqual(response.json()["results"], [])
        self.open_boss_page.assert_not_called()
        self.open_boss_job.assert_not_called()
        self.analyze_jd.assert_not_called()

    def test_list_candidates_are_filtered_before_opening_detail(self):
        self.read_boss_job_links.return_value = [
            {"title": "Java 开发", "url": SECOND_JOB, "snippet": ""}
        ]
        response = self.client.post("/jobs/search-analyze", json=self.payload)
        self.assertEqual(response.json()["status"], "no_matching_job")
        self.open_boss_job.assert_not_called()
        self.analyze_jd.assert_not_called()

    def test_invalid_inputs_do_not_check_browser_or_search(self):
        cases = [
            {}, {"city": "郑州"}, {"city": " ", "keyword": "AI"},
            {"city": "郑州", "keyword": " "},
            {"city": "x" * 31, "keyword": "AI"},
            {"city": "郑州", "keyword": "x" * 101},
        ] + [dict(self.payload, max_results=value) for value in (0, 6, "abc")]
        for payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post("/jobs/search-analyze", json=payload)
                self.assertEqual(response.status_code, 422)
        self.check_boss_browser.assert_not_called()
        self.search_jobs.assert_not_called()
        self.analyze_jd.assert_not_called()

    def test_browser_not_ready_stops_before_paid_search(self):
        self.check_boss_browser.side_effect = RuntimeError("请先登录")
        self.assertEqual(self.client.post("/jobs/search-analyze", json=self.payload).status_code, 503)
        self.search_jobs.assert_not_called()
        self.analyze_jd.assert_not_called()

    def test_search_failure_stops_without_retry(self):
        self.search_jobs.side_effect = RuntimeError("搜索失败")
        self.assertEqual(self.client.post("/jobs/search-analyze", json=self.payload).status_code, 503)
        self.search_jobs.assert_called_once()
        self.open_boss_page.assert_not_called()
        self.analyze_jd.assert_not_called()

    def test_list_failure_stops_without_alternate_search(self):
        self.read_boss_job_links.side_effect = RuntimeError("列表需要验证")
        self.assertEqual(self.client.post("/jobs/search-analyze", json=self.payload).status_code, 503)
        self.search_jobs.assert_called_once()
        self.open_boss_job.assert_not_called()
        self.analyze_jd.assert_not_called()

    def test_jd_failure_stops_before_model(self):
        self.read_boss_jd.side_effect = RuntimeError("JD 不可见")
        self.assertEqual(self.client.post("/jobs/search-analyze", json=self.payload).status_code, 503)
        self.read_boss_jd.assert_called_once()
        self.analyze_jd.assert_not_called()

    def test_incomplete_jd_does_not_call_model(self):
        self.read_boss_jd.return_value = dict(self.jd, content="short")
        self.assertEqual(self.client.post("/jobs/search-analyze", json=self.payload).status_code, 409)
        self.analyze_jd.assert_not_called()

    def test_model_failure_does_not_repeat_search_or_model(self):
        self.analyze_jd.side_effect = RuntimeError("模型失败")
        self.assertEqual(self.client.post("/jobs/search-analyze", json=self.payload).status_code, 503)
        self.search_jobs.assert_called_once()
        self.read_boss_jd.assert_called_once()
        self.analyze_jd.assert_called_once()


    def use_direct_jobs(self, count):
        jobs = [
            {"title": f"AI 开发 {i}", "url": f"https://www.zhipin.com/job_detail/job{i}.html", "snippet": ""}
            for i in range(count)
        ]
        self.search_jobs.return_value = jobs
        self.read_boss_jd.side_effect = lambda url, **kwargs: {
            "title": "详情 " + url.split("/")[-1], "url": url, "content": CONTENT + url,
        }
        self.analyze_jd.side_effect = lambda title, content: "分析 " + title
        return jobs

    def test_five_jobs_are_each_analyzed_with_their_own_jd_and_link(self):
        jobs = self.use_direct_jobs(5)
        response = self.client.post("/jobs/search-analyze", json=dict(self.payload, max_results=5))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["requested_count"], data["candidate_count"], data["count"]), (5, 5, 5))
        self.assertEqual([item["url"] for item in data["results"]], [job["url"] for job in jobs])
        self.assertEqual(self.analyze_jd.call_count, 5)
        for item, model_call in zip(data["results"], self.analyze_jd.call_args_list):
            self.assertEqual(model_call.args, (item["title"], CONTENT + item["url"]))
            self.assertEqual(item["analysis"], "分析 " + item["title"])
        self.search_jobs.assert_called_once_with("郑州", "AI", 5)
        self.read_boss_job_links.assert_not_called()

    def test_one_and_two_job_limits_stop_before_extra_calls(self):
        for limit in (1, 2):
            with self.subTest(limit=limit):
                self.use_direct_jobs(5)
                for mock in (self.search_jobs, self.read_boss_jd, self.analyze_jd, self.open_boss_job):
                    mock.reset_mock()
                response = self.client.post("/jobs/search-analyze", json=dict(self.payload, max_results=limit))
                self.assertEqual(response.json()["count"], limit)
                self.assertEqual(self.read_boss_jd.call_count, limit)
                self.assertEqual(self.analyze_jd.call_count, limit)
                self.search_jobs.assert_called_once()
        self.open_boss_page.assert_not_called()

    def test_duplicate_list_links_are_not_reanalyzed(self):
        self.read_boss_job_links.return_value = [
            self.candidate, dict(self.candidate, url=JOB_URL + "?source=2"),
            dict(self.candidate, url=SECOND_JOB),
        ]
        response = self.client.post("/jobs/search-analyze", json=self.payload)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(self.read_boss_jd.call_count, 2)
        self.assertEqual(self.analyze_jd.call_count, 2)

    def test_list_fills_short_direct_results_and_deduplicates_both_sources(self):
        self.search_jobs.return_value = [self.candidate, self.search_result]
        self.read_boss_job_links.return_value = [
            dict(self.candidate, url=JOB_URL + "?source=2"),
            dict(self.candidate, url=SECOND_JOB),
            {"title": "Java 开发", "url": "https://www.zhipin.com/job_detail/java.html", "snippet": ""},
        ]
        response = self.client.post("/jobs/search-analyze", json=dict(self.payload, max_results=2))
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(self.open_boss_job.call_args_list, [call(JOB_URL), call(SECOND_JOB)])
        self.read_boss_job_links.assert_called_once_with(LIST_URL, 5)
        self.search_jobs.assert_called_once()

    def test_shortage_is_explicit_without_extra_search(self):
        self.use_direct_jobs(2)
        data = self.client.post("/jobs/search-analyze", json=self.payload).json()
        self.assertEqual((data["requested_count"], data["count"]), (5, 2))
        self.assertIn("不足", data["message"])
        self.search_jobs.assert_called_once()
        self.assertEqual(self.analyze_jd.call_count, 2)

    def test_later_jd_failure_keeps_completed_results_and_stops(self):
        jobs = self.use_direct_jobs(3)
        self.read_boss_jd.side_effect = [self.jd, RuntimeError("请完成登录验证")]
        response = self.client.post("/jobs/search-analyze", json=self.payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["status"], data["count"]), ("partial", 1))
        self.assertEqual(data["results"][0]["url"], jobs[0]["url"])
        self.assertEqual(data["errors"][0]["url"], jobs[1]["url"])
        self.assertEqual(data["errors"][0]["stage"], "读取 JD")
        self.assertEqual(self.read_boss_jd.call_count, 2)
        self.assertEqual(self.analyze_jd.call_count, 1)
        self.assertEqual(self.open_boss_job.call_count, 2)

    def test_later_model_failure_keeps_results_and_never_retries(self):
        self.use_direct_jobs(3)
        self.analyze_jd.side_effect = ["第一个分析", RuntimeError("模型超时")]
        data = self.client.post("/jobs/search-analyze", json=self.payload).json()
        self.assertEqual((data["status"], data["count"]), ("partial", 1))
        self.assertEqual(data["results"][0]["analysis"], "第一个分析")
        self.assertEqual(data["errors"][0]["stage"], "DeepSeek 分析")
        self.assertEqual(self.analyze_jd.call_count, 2)
        self.assertEqual(self.read_boss_jd.call_count, 2)
        self.search_jobs.assert_called_once()

    def test_later_incomplete_jd_stops_without_analyzing_it(self):
        self.use_direct_jobs(3)
        self.read_boss_jd.side_effect = [self.jd, dict(self.jd, content="short")]
        data = self.client.post("/jobs/search-analyze", json=self.payload).json()
        self.assertEqual((data["status"], data["count"]), ("partial", 1))
        self.assertEqual(self.analyze_jd.call_count, 1)

    def test_empty_search_has_consistent_empty_results(self):
        self.search_jobs.return_value = []
        data = self.client.post("/jobs/search-analyze", json=self.payload).json()
        self.assertEqual(data["status"], "no_matching_job")
        self.assertEqual((data["count"], data["candidate_count"]), (0, 0))
        self.assertEqual(data["results"], [])
        self.assertEqual(data["errors"], [])
        self.analyze_jd.assert_not_called()


class BossListTests(unittest.TestCase):
    def setUp(self):
        self.page = MagicMock()
        self.page.url = LIST_URL
        self.browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[self.page])])
        guard = patch("job_agent.boss.sync_playwright")
        self.factory = guard.start()
        self.addCleanup(guard.stop)
        driver = self.factory.return_value.__enter__.return_value
        driver.chromium.connect_over_cdp.return_value = self.browser
        self.links = self.page.locator.return_value
        self.nodes = []
        self.set_links([
            ("/job_detail/example123.html?source=1", "AI 开发"),
            ("/job_detail/example123.html?source=2", "重复 AI"),
            ("https://evil.example/job_detail/evil.html", "AI 外部链接"),
            ("/job_detail/second456.html", "AI 后端"),
        ])
        for target in ("builtins.input", "subprocess.Popen"):
            guard = patch(target, side_effect=AssertionError("读取函数不能交互或启动浏览器"))
            guard.start()
            self.addCleanup(guard.stop)

    def set_links(self, rows):
        self.nodes = []
        for href, title in rows:
            node = MagicMock()
            node.get_attribute.return_value = href
            node.inner_text.return_value = title
            self.nodes.append(node)
        self.links.count.return_value = len(self.nodes)
        self.links.nth.side_effect = lambda number: self.nodes[number]

    def test_relative_links_deduplication_and_external_link_rejection(self):
        result = boss.read_boss_job_links(LIST_URL)
        self.assertEqual([job["url"] for job in result], [JOB_URL + "?source=1", SECOND_JOB])
        self.assertEqual([job["title"] for job in result], ["AI 开发", "AI 后端"])
        self.page.goto.assert_not_called()

    def test_limit_stops_reading_more_jobs(self):
        result = boss.read_boss_job_links(LIST_URL, 1)
        self.assertEqual(len(result), 1)
        for node in self.nodes[1:]:
            node.inner_text.assert_not_called()

    def test_invalid_list_or_limit_never_connects(self):
        for url, limit in ((JOB_URL, 5), (LIST_URL, 0), (LIST_URL, 6)):
            with self.subTest(url=url, limit=limit):
                with self.assertRaises(ValueError):
                    boss.read_boss_job_links(url, limit)
        self.factory.assert_not_called()

    def test_timeout_or_verification_is_controlled(self):
        self.links.first.wait_for.side_effect = Error("private diagnostic detail")
        with self.assertRaises(RuntimeError) as exc:
            boss.read_boss_job_links(LIST_URL)
        self.assertNotIn("private diagnostic detail", str(exc.exception))

    def test_navigation_during_read_is_rejected(self):
        def navigate(*args, **kwargs):
            self.page.url = "https://www.zhipin.com/web/user/"
            return "/job_detail/example123.html"
        self.nodes[0].get_attribute.side_effect = navigate
        with self.assertRaisesRegex(RuntimeError, "页面跳转"):
            boss.read_boss_job_links(LIST_URL)

    def test_list_url_validation(self):
        self.assertTrue(boss.is_boss_list_url(LIST_URL))
        self.assertTrue(boss.is_boss_list_url(LIST_URL + "?source=search"))
        for url in (
            None, JOB_URL, "http://www.zhipin.com/zhaopin/example/",
            "https://www.zhipin.com.evil.example/zhaopin/example/",
            "https://user@www.zhipin.com/zhaopin/example/",
            "https://www.zhipin.com:invalid/zhaopin/example/",
        ):
            self.assertFalse(boss.is_boss_list_url(url))


class BrowserPreparationTests(unittest.TestCase):
    def test_browser_endpoint_check_is_local_and_bounded(self):
        manager = MagicMock()
        manager.__enter__.return_value = io.StringIO(json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1/mock"}))
        with patch("job_agent.boss.urlopen", return_value=manager) as request:
            boss.check_boss_browser()
        request.assert_called_once_with("http://127.0.0.1:9222/json/version", timeout=2)

    def test_browser_not_ready_has_clear_message(self):
        with patch("job_agent.boss.urlopen", side_effect=URLError("private diagnostic detail")):
            with self.assertRaisesRegex(RuntimeError, "--login") as exc:
                boss.check_boss_browser()
        self.assertNotIn("private diagnostic detail", str(exc.exception))


class JDSelectorRegressionTests(unittest.TestCase):
    def test_company_description_is_not_included_in_jd(self):
        from bs4 import BeautifulSoup
        html = """
        <div class="job-detail">
          <div class="job-detail-section">
            <h3>职位描述</h3><div class="job-sec-text">岗位职责：开发 AI 接口。</div>
          </div>
          <div class="job-detail-section job-detail-company">
            <div class="detail-section-item company-info-box">
              <h3>公司介绍</h3><div class="job-sec-text">公司介绍和福利，不能混入 JD。</div>
            </div>
          </div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(len(soup.select(".job-sec-text")), 2)
        nodes = soup.select(boss.JD_SELECTOR)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].get_text(), "岗位职责：开发 AI 接口。")


if __name__ == "__main__":
    unittest.main()
