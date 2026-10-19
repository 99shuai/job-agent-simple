"""验证 JD 分析函数的调用逻辑，不调用真实 DeepSeek API。"""

import json
import os
import unittest
from unittest.mock import patch

from job_agent.llm import analyze_jd


class AnalyzeJDTests(unittest.TestCase):
    def setUp(self):
        # 清除真实密钥，并用模拟函数代替 call_deepseek。
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        mock = patch("job_agent.llm.call_deepseek", return_value="模拟分析结果")
        self.model = mock.start()
        self.addCleanup(mock.stop)

    def test_empty_input_stops_before_model_call(self):
        for title, content in (("", "测试正文"), ("测试岗位", ""), ("", "")):
            with self.subTest(title=title, content=content):
                with self.assertRaisesRegex(ValueError, "不能为空"):
                    analyze_jd(title, content)
                self.model.assert_not_called()

    def test_title_and_full_content_are_passed_as_json(self):
        title = 'Python 开发实习生 "Agent 方向"'
        content = "职责：开发招聘助手。\n必备：Python。\n加分：FastAPI。"
        analyze_jd(title, content)
        self.model.assert_called_once()
        prompt, user_content = self.model.call_args.args
        self.assertTrue(prompt.strip())
        self.assertEqual(json.loads(user_content), {"title": title, "content": content})
        self.assertIn("开发实习生", user_content)

    def test_model_reply_is_returned_unchanged(self):
        self.model.return_value = "职责：开发接口。\n必备：Python。\n薪资：未说明。"
        reply = analyze_jd("Python 开发实习生", "负责接口开发，要求掌握 Python。")
        self.assertEqual(reply, self.model.return_value)
        self.model.assert_called_once()

    def test_model_failure_propagates_without_retry(self):
        self.model.side_effect = RuntimeError("模拟请求超时")
        with self.assertRaisesRegex(RuntimeError, "模拟请求超时"):
            analyze_jd("Python 开发实习生", "负责接口开发，要求掌握 Python。")
        self.model.assert_called_once()


if __name__ == "__main__":
    unittest.main()
