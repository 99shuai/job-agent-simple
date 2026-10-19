"""验证普通 Python 启动时的虚拟环境委托，不启动服务器。"""
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
import start


class StartupTests(unittest.TestCase):
    def test_plain_python_waits_for_project_venv_and_preserves_flags(self):
        expected = start.ROOT / (".venv/Scripts/python.exe" if start.os.name == "nt" else ".venv/bin/python")
        with patch.object(sys, "executable", str(start.ROOT / "outside-python.exe")), \
             patch.object(sys, "argv", ["start.py", "--no-browser", "--port", "8001"]), \
             patch.object(Path, "is_file", return_value=True), \
             patch("start.subprocess.call", return_value=7) as delegate:
            self.assertEqual(start.main(), 7)
        delegate.assert_called_once_with([str(expected), str(Path(start.__file__).resolve()), "--no-browser", "--port", "8001"])

    def test_keyboard_interrupt_during_venv_delegation_is_controlled(self):
        with patch.object(sys, "executable", str(start.ROOT / "outside-python.exe")), \
             patch.object(sys, "argv", ["start.py"]), \
             patch.object(Path, "is_file", return_value=True), \
             patch("start.subprocess.call", side_effect=KeyboardInterrupt):
            self.assertEqual(start.main(), 130)


if __name__ == "__main__":
    unittest.main()
