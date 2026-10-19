"""一个命令启动本地网页；优先使用项目虚拟环境，不自动安装依赖。"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent
APP_ID = "job-agent-simple-web-1"


def open_when_ready(url):
    """服务就绪后再打开页面，不启动招聘搜索或模型调用。"""
    for _ in range(60):
        try:
            with urlopen(url + "/health", timeout=1) as response:
                if json.load(response).get("app") == APP_ID:
                    webbrowser.open(url)
                    return
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    print("未能自动打开页面，请手动访问：" + url, flush=True)


def main():
    venv = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    if venv.is_file() and Path(sys.executable).resolve() != venv.resolve():
        # Windows 上等待虚拟环境子进程，确保启动终端保持运行。
        try:
            return subprocess.call([str(venv), str(Path(__file__).resolve()), *sys.argv[1:]])
        except KeyboardInterrupt:
            return 130
    parser = argparse.ArgumentParser(description="启动招聘搜索与 JD 分析网页")
    parser.add_argument("--port", type=int, default=8000, help="本地端口，默认 8000")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--no-reload", action="store_true", help="关闭保存代码后自动重载")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1 到 65535 之间")
    try:
        import uvicorn
        import fastapi
        import openai
        import playwright
    except ImportError as exc:
        print("缺少运行依赖，请先执行：")
        print(f'"{sys.executable}" -m pip install -r "{ROOT / "requirements.txt"}"')
        print("缺少的模块：" + (exc.name or "未知模块"))
        return 1

    os.chdir(ROOT)
    url = f"http://127.0.0.1:{args.port}"
    try:
        with socket.create_connection(("127.0.0.1", args.port), timeout=0.5):
            occupied = True
    except OSError:
        occupied = False
    if occupied:
        try:
            with urlopen(url + "/health", timeout=3) as response:
                ours = json.load(response).get("app") == APP_ID
        except (OSError, ValueError):
            ours = False
        if ours:
            print("应用已经在运行：" + url)
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        print(f"端口 {args.port} 已被其他服务或旧版接口占用。请在原终端按 Ctrl+C 停止，")
        print("或者执行：python start.py --port 8001")
        return 1

    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    print("正在启动职引：" + url, flush=True)
    print("保持终端运行；按 Ctrl+C 退出。配置状态和登录按钮可在网页中查看。", flush=True)
    options = {} if args.no_reload else {"reload_dirs": [str(ROOT / "job_agent")]}
    uvicorn.run("job_agent.api:app", host="127.0.0.1", port=args.port,
                reload=not args.no_reload, **options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
