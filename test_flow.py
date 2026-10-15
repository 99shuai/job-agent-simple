"""离线测试：使用假密钥及模拟 API，不发送真实网络请求。"""

import contextlib
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import httpx
import openai
import main
import search
import llm


def job(number):
    return {"title": f"岗位 {number}", "url": f"https://example.com/jobs/{number}", "snippet": "Python"}


class OfflineTests(unittest.TestCase):
    def setUp(self):
        # 清除真实配置；未被具体测试模拟的 API 调用直接报错。
        for guard in (
            patch.dict(os.environ, {"SERPAPI_API_KEY": "test-serpapi-key",
                                    "DEEPSEEK_API_KEY": "test-deepseek-key"}, clear=True),
            patch("search.urlopen", side_effect=AssertionError("禁止真实搜索请求")),
            patch("openai.OpenAI", side_effect=AssertionError("禁止真实 LLM 请求")),
        ):
            guard.start()
            self.addCleanup(guard.stop)

    def run_flow(self, batches, rewritten="Python AI", quantity="3", analyze_error=None):
        output = io.StringIO()
        with patch("builtins.input", side_effect=["郑州", "AI Agent", quantity]), \
             patch("main.search_jobs", side_effect=batches) as search_mock, \
             patch("main.expand_keyword", return_value=rewritten) as expand_mock, \
             patch("main.analyze_jobs", return_value="模拟分析", side_effect=analyze_error) as analyze_mock, \
             contextlib.redirect_stdout(output):
            main.main()
        return search_mock, expand_mock, analyze_mock, output.getvalue()

    def test_enough_results_stop_after_first_search(self):
        s, e, a, out = self.run_flow([[job(1), job(2), job(3)]])
        self.assertEqual(s.call_count, 1)
        e.assert_not_called()
        a.assert_called_once_with([job(1), job(2), job(3)])
        self.assertIn("已满足数量要求", out)

    def test_insufficient_results_rewrite_and_search_again(self):
        s, e, a, out = self.run_flow([[job(1)], [job(2), job(3)]])
        self.assertEqual(s.call_count, 2)
        e.assert_called_once_with("AI Agent")
        self.assertEqual(s.call_args.args, ("郑州", "Python AI", 3))
        a.assert_called_once_with([job(1), job(2), job(3)])
        self.assertIn("第 2/2 次请求", out)

    def test_duplicate_rewritten_keywords_do_not_search_again(self):
        for rewritten in ("AI Agent", "  ai   AGENT  ", "AI\tAgent"):
            with self.subTest(keyword=rewritten):
                s, e, a, out = self.run_flow([[job(1)]], rewritten)
                self.assertEqual(s.call_count, 1)
                self.assertEqual(e.call_count, 1)
                a.assert_called_once_with([job(1)])
                self.assertIn("关键词重复", out)

    def test_empty_rewritten_keyword_does_not_search_again(self):
        s, e, a, out = self.run_flow([[job(1)]], "   ")
        self.assertEqual(s.call_count, 1)
        self.assertIn("关键词为空", out)

    def test_first_batch_duplicates_do_not_count_as_enough(self):
        s, e, a, out = self.run_flow([[job(1), job(1), job(2)], [job(3)]])
        self.assertEqual(s.call_count, 2)
        self.assertEqual(e.call_count, 1)
        a.assert_called_once_with([job(1), job(2), job(3)])

    def test_duplicates_within_and_between_batches_are_removed(self):
        s, e, a, out = self.run_flow([[job(1), job(1)], [job(1), job(2), job(2)]])
        a.assert_called_once_with([job(1), job(2)])
        self.assertEqual(s.call_count, 2)
        self.assertIn("搜索上限", out)

    def test_link_surrounding_spaces_are_ignored_for_dedup(self):
        duplicate = dict(job(1), url=" https://example.com/jobs/1 ")
        s, e, a, out = self.run_flow([[job(1)], [duplicate, job(2)]])
        a.assert_called_once_with([job(1), job(2)])

    def test_merged_results_never_exceed_requested_count(self):
        s, e, a, out = self.run_flow([[job(1), job(2)], [job(3), job(4), job(5)]])
        a.assert_called_once_with([job(1), job(2), job(3)])

    def test_still_insufficient_stops_after_second_search(self):
        s, e, a, out = self.run_flow([[job(1)], [job(1)]])
        self.assertEqual(s.call_count, 2)
        self.assertEqual(e.call_count, 1)
        a.assert_called_once_with([job(1)])
        self.assertIn("搜索上限", out)

    def test_two_empty_batches_skip_analysis(self):
        s, e, a, out = self.run_flow([[], []])
        self.assertEqual(s.call_count, 2)
        self.assertEqual(e.call_count, 1)
        a.assert_not_called()

    def test_search_failures_abort_without_retry(self):
        for batches, expected_calls in (([RuntimeError("搜索失败")], 1),
                                        ([[], RuntimeError("搜索失败")], 2)):
            with self.subTest(calls=expected_calls):
                s, e, a, out = self.run_flow(batches)
                self.assertEqual(s.call_count, expected_calls)
                self.assertEqual(e.call_count, expected_calls - 1)
                a.assert_not_called()
                self.assertIn("流程已终止", out)

    def test_keyword_rewrite_failure_aborts(self):
        with patch("main.expand_keyword", side_effect=RuntimeError("改写失败")), \
             patch("main.search_jobs", return_value=[job(1)]) as s, \
             patch("main.analyze_jobs") as a, \
             patch("builtins.input", side_effect=["郑州", "AI Agent", "3"]), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            main.main()
        self.assertEqual(s.call_count, 1)
        a.assert_not_called()
        self.assertIn("流程已终止", out.getvalue())

    def test_analysis_failure_aborts_without_retry(self):
        s, e, a, out = self.run_flow([[job(1), job(2), job(3)]], analyze_error=RuntimeError("分析失败"))
        self.assertEqual(a.call_count, 1)
        self.assertEqual(s.call_count, 1)
        self.assertIn("流程已终止", out)

    def test_default_and_invalid_quantity(self):
        s, e, a, out = self.run_flow([[job(1), job(2), job(3)]], quantity="")
        self.assertEqual(s.call_args.args[2], 3)
        for quantity in ("0", "21", "abc", "1.5"):
            with self.subTest(quantity=quantity):
                s, e, a, out = self.run_flow([], quantity=quantity)
                s.assert_not_called()
                e.assert_not_called()
                a.assert_not_called()

    def test_missing_keys_skip_input_and_api(self):
        with patch.dict(os.environ, {}, clear=True), patch("builtins.input") as inp, \
             patch("main.search_jobs") as s, contextlib.redirect_stdout(io.StringIO()) as out:
            main.main()
        inp.assert_not_called()
        s.assert_not_called()
        self.assertIn("SERPAPI_API_KEY", out.getvalue())
        self.assertIn("DEEPSEEK_API_KEY", out.getvalue())

    def search_payload(self, payload):
        manager = MagicMock()
        manager.__enter__.return_value = io.StringIO(json.dumps(payload))
        with patch("search.urlopen", return_value=manager) as request:
            results = search.search_jobs("郑州", "AI Agent", 3)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["timeout"], 30)
        return results

    def test_search_adapter_limit_and_no_results(self):
        rows = [{"title": f"岗位 {i}", "link": f"https://example.com/{i}", "snippet": "Python"} for i in range(5)]
        self.assertEqual(len(self.search_payload({"organic_results": rows})), 3)
        self.assertEqual(self.search_payload({"organic_results": []}), [])
        self.assertEqual(self.search_payload({"error": "Baidu hasn't returned any results for this query."}), [])

    def test_search_http_network_timeout_errors_hide_secrets(self):
        for failure in (HTTPError("secret-url", 401, "test-serpapi-key", None, None),
                        URLError("test-serpapi-key"), TimeoutError()):
            with self.subTest(error=type(failure).__name__), patch("search.urlopen", side_effect=failure) as request:
                with self.assertRaises(RuntimeError) as error:
                    search.search_jobs("郑州", "AI Agent")
                self.assertNotIn("test-serpapi-key", str(error.exception))
                self.assertEqual(request.call_count, 1)

    def test_invalid_search_response_safely_fails(self):
        for payload in ([], {"search_metadata": None}, {"organic_results": None}, {"error": "test-serpapi-key"}):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                self.search_payload(payload)
        manager = MagicMock()
        manager.__enter__.return_value = io.StringIO("not json")
        with patch("search.urlopen", return_value=manager), self.assertRaises(RuntimeError):
            search.search_jobs("郑州", "AI Agent")

    def test_llm_errors_no_retries_and_hide_secrets(self):
        request = httpx.Request("POST", "https://example.com")
        response = httpx.Response(429, request=request)
        failures = (openai.APITimeoutError(request=request),
                    openai.APIConnectionError(message="test-deepseek-key", request=request),
                    openai.APIStatusError("test-deepseek-key", response=response, body=None))
        for failure in failures:
            with self.subTest(error=type(failure).__name__), patch("openai.OpenAI", side_effect=None) as factory:
                client = factory.return_value.__enter__.return_value
                client.chat.completions.create.side_effect = failure
                with self.assertRaises(RuntimeError) as error:
                    llm.call_deepseek("规则", "数据")
                self.assertNotIn("test-deepseek-key", str(error.exception))
                self.assertEqual(factory.call_args.kwargs["max_retries"], 0)
                self.assertEqual(factory.call_args.kwargs["timeout"], 60)
                self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_llm_empty_and_truncated_reply_fail(self):
        for choices in ([], [SimpleNamespace(message=SimpleNamespace(content=" "), finish_reason="stop")],
                        [SimpleNamespace(message=SimpleNamespace(content="部分回复"), finish_reason="length")]):
            with self.subTest(choices=choices), patch("openai.OpenAI", side_effect=None) as factory:
                factory.return_value.__enter__.return_value.chat.completions.create.return_value = SimpleNamespace(choices=choices)
                with self.assertRaises(RuntimeError):
                    llm.call_deepseek("规则", "数据")

    def test_keyword_reply_validation(self):
        for text in ("", "  ", "词一\n词二"):
            with self.subTest(text=text), patch("llm.call_deepseek", return_value=text), self.assertRaises(RuntimeError):
                llm.expand_keyword("AI Agent")
        with patch("llm.call_deepseek", return_value=" Python AI "):
            self.assertEqual(llm.expand_keyword("AI Agent"), "Python AI")

    def test_analysis_context_and_empty_results(self):
        with patch("llm.call_deepseek", return_value="分析") as call:
            llm.analyze_jobs([])
            call.assert_not_called()
            self.assertEqual(llm.analyze_jobs([job(1)]), "分析")
            self.assertEqual(json.loads(call.call_args.args[1]), [job(1)])

    def test_flow_logs_do_not_contain_keys(self):
        s, e, a, out = self.run_flow([[job(1)], [job(2)]])
        self.assertNotIn("test-serpapi-key", out)
        self.assertNotIn("test-deepseek-key", out)


if __name__ == "__main__":
    unittest.main()
