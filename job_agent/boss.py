"""读取一个 BOSS 职位详情页的可见 JD；登录由用户手动完成。"""

import argparse
import json
import os
import time
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, Error


# 公司介绍也使用 job-sec-text，只取职位描述区的直接子元素。
JD_SELECTOR = '.job-detail-section:not(.job-detail-company) > .job-sec-text'

def is_boss_job_url(url: str) -> bool:
    """只接受 BOSS 的 HTTPS 职位详情链接，列表页和其他网站不支持。"""
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url.strip())
        return (
            parts.scheme == "https"
            and parts.hostname == "www.zhipin.com"
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
            and re.fullmatch(r"/job_detail/[A-Za-z0-9_-]+\.html", parts.path) is not None
        )
    except ValueError:
        return False


def find_chrome() -> Path:
    """优先读取 CHROME_PATH，否则查找 PATH 和 Windows 常见安装位置。"""
    configured = os.getenv("CHROME_PATH", "").strip()
    if configured:
        path = Path(configured)
        if path.is_file():
            return path
        raise RuntimeError("CHROME_PATH 指向的文件不存在，请检查 Chrome 安装路径。")

    for name in ("chrome", "google-chrome", "google-chrome-stable", "chromium"):
        found = shutil.which(name)
        if found:
            return Path(found)

    # 主要面向 Windows；非默认安装位置可通过 CHROME_PATH 指定。
    for directory in (
        os.getenv("PROGRAMFILES", r"C:\Program Files"),
        os.getenv("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.getenv("LOCALAPPDATA", ""),
    ):
        if directory:
            path = Path(directory) / "Google/Chrome/Application/chrome.exe"
            if path.is_file():
                return path
    raise RuntimeError("没有找到 Chrome，请通过环境变量 CHROME_PATH 指定可执行文件路径。")



def is_boss_list_url(url: str) -> bool:
    """只识别 BOSS 搜索结果中常见的 /zhaopin/ 列表页。"""
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url.strip())
        return (
            parts.scheme == "https"
            and parts.hostname == "www.zhipin.com"
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
            and re.fullmatch(r"/zhaopin/[A-Za-z0-9_~-]+/?", parts.path) is not None
        )
    except ValueError:
        return False


def check_boss_browser() -> None:
    """开始付费搜索前先确认本机专用浏览器已启动；不读取登录凭据。"""
    try:
        with urlopen("http://127.0.0.1:9222/json/version", timeout=2) as response:
            data = json.load(response)
        if not isinstance(data, dict) or not data.get("webSocketDebuggerUrl"):
            raise ValueError("Invalid Chrome endpoint")
    except (OSError, ValueError):
        raise RuntimeError(
            "请先运行 python -m job_agent.boss --login，在专用 Chrome 登录并保持窗口打开。"
        ) from None


def _find_boss_page(browser, url: str, wait: bool = False):
    """等待刚打开的目标标签页，最多 8 秒；只处理浏览器事件，不重新搜索。"""
    target_path = urlsplit(url).path
    deadline = time.monotonic() + 8
    while True:
        tabs = [page for context in browser.contexts for page in context.pages]
        matches = [
            page for page in tabs
            if urlsplit(page.url).hostname == "www.zhipin.com"
            and urlsplit(page.url).path == target_path
        ]
        if matches:
            return matches[-1]
        if not wait or time.monotonic() >= deadline or not tabs:
            raise RuntimeError("未找到所选岗位或列表的标签页，请检查专用 Chrome 是否需要登录或验证。")
        # 给新标签页时间完成导航；不会再发送搜索或模型请求。
        tabs[0].wait_for_timeout(200)


def read_boss_job_links(url: str, limit: int = 5) -> list[dict]:
    """从一个已打开的 BOSS 列表页提取最多 5 个详情链接，不翻页。"""
    if not is_boss_list_url(url):
        raise ValueError("当前只支持 BOSS 的 /zhaopin/ 列表页。")
    if not 1 <= limit <= 5:
        raise ValueError("列表提取数量必须在 1 到 5 之间。")
    url = url.strip()
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(
                "http://127.0.0.1:9222", timeout=8000, no_defaults=True
            )
            page = _find_boss_page(browser, url, wait=True)
            links = page.locator('a[href*="/job_detail/"]')
            links.first.wait_for(state="attached", timeout=8000)
            jobs = []
            seen = set()
            for number in range(links.count()):
                link = links.nth(number)
                detail_url = urljoin(url, link.get_attribute("href") or "")
                if not is_boss_job_url(detail_url):
                    continue
                identity = urlsplit(detail_url).path
                title = link.inner_text(timeout=3000).strip()
                if identity in seen or not title:
                    continue
                seen.add(identity)
                jobs.append({"title": title, "url": detail_url, "snippet": ""})
                if len(jobs) >= limit:
                    break
            if not is_boss_list_url(page.url) or urlsplit(page.url).path != urlsplit(url).path:
                raise RuntimeError("列表读取期间页面跳转，未采用这些职位链接。")
            return jobs
    except Error:
        raise RuntimeError("读取 BOSS 列表失败，请检查专用窗口是否需要登录或验证。") from None

def open_boss_page(url: str) -> None:
    """打开专用 Chrome 中的 BOSS 页面；不自动登录。"""
    if not (is_boss_job_url(url) or is_boss_list_url(url) or url == "https://www.zhipin.com/"):
        raise ValueError('当前仅允许 BOSS 的职位详情、招聘列表或固定登录准备首页。')
    url = url.strip()
    chrome = find_chrome()
    # 专用资料可能保留登录状态，放在系统临时目录，不复制个人 Chrome 资料。
    profile = Path(tempfile.gettempdir()) / "job-agent-boss-cdp"
    try:
        subprocess.Popen([
            str(chrome),
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ])
    except OSError:
        raise RuntimeError("Chrome 启动失败，请检查安装路径和运行权限。") from None



def open_boss_job(url: str) -> None:
    """保留原单岗位入口；列表页不作为职位详情打开。"""
    if not is_boss_job_url(url):
        raise ValueError("当前只支持 BOSS 的 HTTPS 职位详情链接。")
    open_boss_page(url)


def read_boss_jd(url: str, *, wait_for_ready: bool = False) -> dict:
    """仅读取已打开的指定职位页，可供 API 调用；不启动浏览器或等待终端输入。"""
    if not is_boss_job_url(url):
        raise ValueError("当前只支持 BOSS 的 HTTPS 职位详情链接。")
    url = url.strip()
    target_path = urlsplit(url).path
    try:
        with sync_playwright() as p:
            # 连接已有浏览器，不自动导航、不自动重试；超时单位是毫秒。
            browser = p.chromium.connect_over_cdp(
                "http://127.0.0.1:9222", timeout=8000, no_defaults=True
            )
            page = _find_boss_page(browser, url, wait=wait_for_ready)
            jd = page.locator(JD_SELECTOR)
            if wait_for_ready:
                jd.first.wait_for(state="visible", timeout=8000)
            if jd.count() != 1:
                raise RuntimeError("未找到唯一的 JD 正文，可能需要登录、验证或更新定位规则。")
            content = jd.inner_text(timeout=5000).strip()
            title = page.title().strip()
            # 页面若在读取期间跳转，不把其他页面的内容当作所选岗位的 JD。
            if not is_boss_job_url(page.url) or urlsplit(page.url).path != target_path:
                raise RuntimeError("读取期间页面已跳转，未取得所选岗位的 JD。")
            if not content:
                raise RuntimeError("JD 正文为空，未调用分析。")
            print(f"[JD] 读取到 {len(content)} 个字符；仍需核实正文是否完整。")
            # 不调用 browser.close()，仅断开程序连接，保留专用浏览器。
            return {"title": title, "url": url, "content": content}
    except Error:
        raise RuntimeError("连接或读取 Chrome 失败，请检查专用窗口、9222 端口和网页状态。") from None


def fetch_boss_jd(url: str) -> dict:
    """终端流程：打开职位、等手动登录，再调用读取函数。"""
    open_boss_job(url)
    print("[JD] 已请求打开所选岗位，请在专用 Chrome 中手动完成登录或验证。")
    print("请确认完整 JD 可见，不要打开 F12，也不要切到日常 Chrome。")
    print("专用目录可能保留登录状态；实验结束后请关闭该 Chrome。")
    input("保持所选职位页打开，回到本终端按回车读取：")

    return read_boss_jd(url)


def main() -> None:
    """独立练习入口：导入本模块不会启动浏览器或等待输入。"""
    try:
        parser = argparse.ArgumentParser(description="BOSS 专用浏览器准备或单岗位读取")
        parser.add_argument("--login", action="store_true", help="仅打开专用 Chrome，供手动登录")
        args = parser.parse_args()
        if args.login:
            open_boss_page("https://www.zhipin.com/")
            print("请在专用 Chrome 中登录并保持窗口打开，然后使用关键词分析接口。")
            print("后续岗位链接由程序自动传递，无需手动输入。")
            return
        url = input("请输入 BOSS 职位详情链接：").strip()
        jd = fetch_boss_jd(url)
        print(f"\n标题：{jd['title']}\n来源：{jd['url']}\n\n{jd['content']}")
    except (RuntimeError, ValueError) as exc:
        print(f"错误：{exc}")
    except (KeyboardInterrupt, EOFError):
        print("\n输入已取消，程序结束。")


if __name__ == "__main__":
    main()
