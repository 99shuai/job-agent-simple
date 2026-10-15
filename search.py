"""只获取搜索摘要，不访问招聘网页。"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


def search_jobs(city: str, keyword: str, max_results: int = 3,) -> list[dict]:
    """调用一次 SerpApi 百度搜索，返回标题、原始链接和摘要。"""
    key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("缺少环境变量 SERPAPI_API_KEY。")
    if not city.strip() or not keyword.strip():
        raise ValueError("城市和岗位关键词不能为空。")
    if not 1 <= max_results <= 50:
        raise ValueError("max_results 必须在 1 到 50 之间。")

    params = urlencode({
        "engine": "baidu",
        "q": f"{city.strip()} {keyword.strip()} 招聘",
        "api_key": key,
        "rn": max_results,
    })
    try:
        with urlopen(f"https://serpapi.com/search.json?{params}", timeout=30) as response:
            data = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"搜索失败（HTTP {exc.code}），请检查密钥、账户额度或稍后重试。") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("搜索请求失败或超时，请检查网络。") from None
    except (ValueError, UnicodeError):
        raise RuntimeError("搜索接口返回了无法解析的 JSON。") from None

    if not isinstance(data, dict):
        raise RuntimeError("搜索接口返回格式异常。")
    # 旧项目已验证：百度无结果时，SerpApi 可能返回这一条 error。
    if data.get("error") == "Baidu hasn't returned any results for this query." and not data.get("organic_results"):
        return []
    metadata = data.get("search_metadata", {})
    if not isinstance(metadata, dict):
        raise RuntimeError("搜索接口返回的状态信息格式异常。")
    if data.get("error") or metadata.get("status") == "Error":
        # 不输出原始错误或请求 URL，防止其中含有密钥。
        raise RuntimeError("搜索接口返回错误，请检查 SERPAPI_API_KEY、账户额度和搜索参数。")
    rows = data.get("organic_results", [])
    if not isinstance(rows, list):
        raise RuntimeError("搜索结果格式异常。")

    results = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title, link = row.get("title"), row.get("link")
        if not isinstance(title, str) or not isinstance(link, str) or not title.strip() or not link.strip():
            continue
        snippet = row.get("snippet", "")
        results.append({"title": title, "url": link,
                        "snippet": snippet if isinstance(snippet, str) else ""})
        if len(results) >= max_results:
            break
    return results