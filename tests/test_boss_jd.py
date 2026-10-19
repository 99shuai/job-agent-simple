"""BOSS JD 离线检查：只使用模拟浏览器，不启动 Chrome、不发网络请求。"""

import contextlib
import importlib
import io
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from playwright.sync_api import Error
from job_agent import boss as boss_demo
from job_agent import cli as main

URL = "https://www.zhipin.com/job_detail/example123.html"
OTHER = "https://www.zhipin.com/job_detail/another456.html"
CONTENT = "负责 Python 接口开发，要求了解 HTTP；这是模拟 JD。"


class BossJDTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        launcher = patch("job_agent.boss.subprocess.Popen")
        self.launch = launcher.start()
        self.addCleanup(launcher.stop)
        prompt = patch("builtins.input", return_value="")
        self.prompt = prompt.start()
        self.addCleanup(prompt.stop)
        finder = patch("job_agent.boss.find_chrome", return_value=Path("mock-chrome.exe"))
        self.finder = finder.start()
        self.addCleanup(finder.stop)
        self.page = MagicMock()
        self.page.url = URL
        self.page.title.return_value = " 模拟岗位 "
        self.page.locator.return_value.count.return_value = 1
        self.page.locator.return_value.inner_text.return_value = " " + CONTENT + " "
        self.browser = MagicMock()
        self.browser.contexts = [SimpleNamespace(pages=[self.page])]
        factory = patch("job_agent.boss.sync_playwright")
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        self.driver = self.factory.return_value.__enter__.return_value
        self.driver.chromium.connect_over_cdp.return_value = self.browser
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def test_import_does_not_launch_browser_or_wait_for_input(self):
        importlib.reload(boss_demo)
        self.launch.assert_not_called()
        self.prompt.assert_not_called()
        self.factory.assert_not_called()

    def test_url_validation(self):
        for url in (URL, URL + "?source=search#jd", " " + URL + " "):
            self.assertTrue(boss_demo.is_boss_job_url(url))
        for url in (
            "", None, "http://www.zhipin.com/job_detail/example123.html",
            "https://www.zhipin.com/zhengzhou/",
            "https://www.zhipin.com.evil.example/job_detail/example123.html",
            "https://www.zhipin.com@evil.example/job_detail/example123.html",
            "https://user:password@www.zhipin.com/job_detail/example123.html",
            "https://www.zhipin.com:9999/job_detail/example123.html",
            "https://www.zhipin.com:bad/job_detail/example123.html",
            "https://www.liepin.com/job/123.shtml",
        ):
            with self.subTest(url=url):
                self.assertFalse(boss_demo.is_boss_job_url(url))

    def test_unsupported_url_never_launches_browser(self):
        with self.assertRaises(ValueError):
            boss_demo.fetch_boss_jd("https://www.zhipin.com/zhengzhou/")
        self.finder.assert_not_called()
        self.launch.assert_not_called()
        self.factory.assert_not_called()

    def test_reads_exact_selected_job_and_preserves_original_link(self):
        wrong = MagicMock()
        wrong.url = OTHER
        self.browser.contexts = [SimpleNamespace(pages=[self.page, wrong])]
        original = URL + "?source=search"
        result = boss_demo.fetch_boss_jd(original)
        self.assertEqual(result, {"title": "模拟岗位", "url": original, "content": CONTENT})
        wrong.locator.assert_not_called()
        self.page.locator.assert_called_once_with('.job-detail-section:not(.job-detail-company) > .job-sec-text')
        self.page.locator.return_value.inner_text.assert_called_once_with(timeout=5000)
        self.driver.chromium.connect_over_cdp.assert_called_once_with(
            "http://127.0.0.1:9222", timeout=8000, no_defaults=True)
        self.launch.assert_called_once()
        self.assertEqual(self.launch.call_args.args[0][-1], original)
        self.page.goto.assert_not_called()
        self.browser.close.assert_not_called()

    def test_missing_selected_page_fails_without_reading_another_job(self):
        self.page.url = OTHER
        with self.assertRaisesRegex(RuntimeError, "所选岗位"):
            boss_demo.fetch_boss_jd(URL)
        self.page.locator.assert_not_called()

    def test_missing_or_ambiguous_jd_fails(self):
        for count in (0, 2):
            with self.subTest(count=count):
                self.page.locator.return_value.count.return_value = count
                with self.assertRaisesRegex(RuntimeError, "唯一"):
                    boss_demo.fetch_boss_jd(URL)
        self.page.locator.return_value.inner_text.assert_not_called()

    def test_empty_jd_fails(self):
        self.page.locator.return_value.inner_text.return_value = " \n "
        with self.assertRaisesRegex(RuntimeError, "正文为空"):
            boss_demo.fetch_boss_jd(URL)

    def test_navigation_during_read_is_rejected(self):
        def navigate_during_read(**kwargs):
            self.page.url = OTHER
            return CONTENT
        self.page.locator.return_value.inner_text.side_effect = navigate_during_read
        with self.assertRaisesRegex(RuntimeError, "读取期间"):
            boss_demo.fetch_boss_jd(URL)

    def test_launch_failure_stops_before_input_and_connection(self):
        self.launch.side_effect = OSError("private path")
        with self.assertRaisesRegex(RuntimeError, "启动失败") as exc:
            boss_demo.fetch_boss_jd(URL)
        self.assertNotIn("private path", str(exc.exception))
        self.prompt.assert_not_called()
        self.factory.assert_not_called()
        self.launch.assert_called_once()

    def test_connection_failure_is_safe_and_not_retried(self):
        self.driver.chromium.connect_over_cdp.side_effect = Error("private-token")
        with self.assertRaises(RuntimeError) as exc:
            boss_demo.fetch_boss_jd(URL)
        self.assertNotIn("private-token", str(exc.exception))
        self.driver.chromium.connect_over_cdp.assert_called_once()
        self.page.locator.assert_not_called()


    def test_read_only_function_never_launches_browser_or_waits_for_input(self):
        result = boss_demo.read_boss_jd(URL)
        self.assertEqual(result["content"], CONTENT)
        self.launch.assert_not_called()
        self.prompt.assert_not_called()
        self.finder.assert_not_called()
        self.driver.chromium.connect_over_cdp.assert_called_once()
        self.browser.close.assert_not_called()


class ChromePathTests(unittest.TestCase):
    def test_explicit_environment_path_has_priority(self):
        with patch.dict(os.environ, {"CHROME_PATH": "custom/chrome.exe"}, clear=True), \
             patch("job_agent.boss.Path.is_file", return_value=True), \
             patch("job_agent.boss.shutil.which") as which:
            self.assertEqual(boss_demo.find_chrome(), Path("custom/chrome.exe"))
            which.assert_not_called()

    def test_invalid_environment_path_reports_configuration_error(self):
        with patch.dict(os.environ, {"CHROME_PATH": "missing.exe"}, clear=True), \
             patch("job_agent.boss.Path.is_file", return_value=False), \
             patch("job_agent.boss.shutil.which") as which:
            with self.assertRaisesRegex(RuntimeError, "CHROME_PATH"):
                boss_demo.find_chrome()
            which.assert_not_called()

    def test_finds_chrome_on_path(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("job_agent.boss.shutil.which", return_value="chrome-from-path"):
            self.assertEqual(boss_demo.find_chrome(), Path("chrome-from-path"))

    def test_finds_common_windows_installation(self):
        with patch.dict(os.environ, {"PROGRAMFILES": "MockProgramFiles"}, clear=True), \
             patch("job_agent.boss.shutil.which", return_value=None), \
             patch("job_agent.boss.Path.is_file", return_value=True):
            self.assertEqual(boss_demo.find_chrome(),
                             Path("MockProgramFiles/Google/Chrome/Application/chrome.exe"))

    def test_missing_chrome_has_clear_error(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("job_agent.boss.shutil.which", return_value=None), \
             patch("job_agent.boss.Path.is_file", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "CHROME_PATH"):
                boss_demo.find_chrome()


class SearchToJDTests(unittest.TestCase):
    def setUp(self):
        guards = [
            patch.dict(os.environ, {"SERPAPI_API_KEY": "mock", "DEEPSEEK_API_KEY": "mock"}, clear=True),
            patch("job_agent.cli.search_jobs", return_value=[{"title": "搜索标题", "url": URL, "snippet": "摘要"}]),
            patch("job_agent.cli.expand_keyword"),
            patch("job_agent.cli.fetch_boss_jd", return_value={"title": "正文页标题", "url": URL, "content": CONTENT}),
            patch("job_agent.cli.analyze_jd", return_value="模拟 JD 分析"),
            patch("job_agent.cli.analyze_jobs", return_value="模拟摘要分析"),
            patch("job_agent.boss.subprocess.Popen", side_effect=AssertionError("禁止真实启动浏览器")),
        ]
        mocks = []
        for guard in guards:
            mocks.append(guard.start())
            self.addCleanup(guard.stop)
        _, self.search, self.rewrite, self.fetch, self.jd_analysis, self.summary_analysis, _ = mocks
        self.output = io.StringIO()

    def run_flow(self, choice):
        with patch("builtins.input", side_effect=["郑州", "AI", "1", choice]), \
             contextlib.redirect_stdout(self.output):
            main.main()

    def test_selected_job_uses_jd_analysis_once(self):
        self.run_flow("1")
        self.search.assert_called_once()
        self.rewrite.assert_not_called()
        self.fetch.assert_called_once_with(URL)
        self.jd_analysis.assert_called_once_with("正文页标题", CONTENT)
        self.summary_analysis.assert_not_called()
        self.assertIn(URL, self.output.getvalue())

    def test_skip_preserves_original_summary_flow(self):
        self.run_flow("")
        self.fetch.assert_not_called()
        self.jd_analysis.assert_not_called()
        self.summary_analysis.assert_called_once()

    def test_invalid_selection_never_opens_browser_or_calls_model(self):
        for choice in ("abc", "0", "2"):
            with self.subTest(choice=choice):
                self.run_flow(choice)
        self.fetch.assert_not_called()
        self.jd_analysis.assert_not_called()
        self.summary_analysis.assert_not_called()

    def test_jd_failure_stops_without_model_or_retry(self):
        self.fetch.side_effect = RuntimeError("模拟网页失败")
        self.run_flow("1")
        self.fetch.assert_called_once()
        self.jd_analysis.assert_not_called()
        self.summary_analysis.assert_not_called()
        self.assertIn("流程已终止", self.output.getvalue())

    def test_jd_model_failure_does_not_fall_back_or_retry(self):
        self.jd_analysis.side_effect = RuntimeError("模拟模型失败")
        self.run_flow("1")
        self.jd_analysis.assert_called_once()
        self.summary_analysis.assert_not_called()
        self.assertIn("流程已终止", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
