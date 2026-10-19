"""招聘搜索 HTTP 接口：验证参数，调用搜索函数，返回 JSON。"""

from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .boss import (
    check_boss_browser,
    is_boss_job_url,
    is_boss_list_url,
    open_boss_job,
    open_boss_page,
    read_boss_jd,
    read_boss_job_links,
)
from .job_filter import filter_job
from .llm import analyze_jd
from .search import search_jobs

logger = logging.getLogger("uvicorn.error")
app = FastAPI(title="招聘搜索接口")


app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def local_browser_protection(request: Request, call_next):
    """阻止其他网页借本机服务调用付费 API 或打开浏览器，不影响本地命令行调用。"""
    action = request.method not in {"GET", "HEAD", "OPTIONS"} or request.url.path == "/jobs"
    origin = request.headers.get("origin")
    expected_origin = f"{request.url.scheme}://{request.url.netloc}"
    cross_site = request.headers.get("sec-fetch-site") == "cross-site"
    if action and ((origin is not None and origin != expected_origin) or cross_site):
        return JSONResponse(status_code=403, content={"detail": "只接受本地页面发起的操作请求。"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path == "/":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
    if not request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


STATIC_DIR = Path(__file__).resolve().parent / "static"
APP_ID = "job-agent-simple-web-1"
_operation_lock = threading.Lock()


@contextmanager
def _operation():
    """本地应用一次处理一个分析请求，避免多次点击导致重复付费或浏览器冲突。"""
    if not _operation_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有任务正在运行，请等待当前分析完成。")
    try:
        yield
    finally:
        _operation_lock.release()


def _one_request():
    with _operation():
        yield


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class JobDescription(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., max_length=30000)


class JobLink(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)


class JobSearch(BaseModel):
    city: str = Field(..., min_length=1, max_length=30)
    keyword: str = Field(..., min_length=1, max_length=100)
    max_results: int = Field(5, ge=1, le=5, description="最多分析并返回的岗位数，范围 1～5；筛选后可能不足")


@app.get("/", include_in_schema=False)
def home():
    """直接展示交互页面，接口文档仍保留在 /docs。"""
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    """仅返回配置是否存在；不发送搜索或模型请求，也不返回密钥。"""
    try:
        check_boss_browser()
        browser_ready = True
    except RuntimeError:
        browser_ready = False
    return {
        "app": APP_ID,
        "serpapi_configured": bool(os.getenv("SERPAPI_API_KEY", "").strip()),
        "deepseek_configured": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
        "browser_ready": browser_ready,
    }


@app.post("/browser/open")
def prepare_browser():
    """页面按钮的准备动作；登录和验证仍由用户在专用窗口完成。"""
    try:
        open_boss_page("https://www.zhipin.com/")
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return {"message": "已请求打开专用 Chrome。请手动登录 BOSS，保持窗口打开，回到本页点击“刷新状态”。"}


@app.get("/jobs")
def get_jobs(
    city: str = Query(..., min_length=1, max_length=30, description="城市，例如郑州"),
    keyword: str = Query(..., min_length=1, max_length=100, description="岗位关键词"),
    max_results: int = Query(3, ge=1, le=20, description="最多返回条数"),
):
    """单轮搜索招聘网页；当前接口不调用 DeepSeek。"""
    city, keyword = city.strip(), keyword.strip()
    # 长度校验还不能排除纯空格，因此需要额外检查。
    if not city or not keyword:
        raise HTTPException(status_code=422, detail="城市和岗位关键词不能只包含空白字符。")

    try:
        results = search_jobs(city, keyword, max_results)
        results = filter_job(results, keyword)
    except ValueError:
        raise HTTPException(status_code=400, detail="搜索参数不正确，请检查后重试。") from None
    except RuntimeError:
        # 不把原始异常或请求 URL 返回给客户端，避免泄露密钥。
        raise HTTPException(
            status_code=503,
            detail="搜索服务暂时不可用，请检查服务端 SERPAPI_API_KEY、网络或账户额度。",
        ) from None

    return {"city": city, "keyword": keyword, "count": len(results), "results": results}


@app.post("/jd", dependencies=[Depends(_one_request)])
def analyze_jd_endpoint(jd: JobDescription):
    """分析岗位标题和 JD 正文，返回 DeepSeek 分析结果。"""
    title = jd.title.strip()
    content = jd.content.strip()

    if not title or not content:
        raise HTTPException(
            status_code=422,
            detail="岗位标题和 JD 正文不能为空。",
        )
    if len(content) < 10:
        raise HTTPException(
            status_code=422,
            detail="岗位 JD 正文内容过短，请提供更完整的描述。",
        )

    try:
        analysis_result = analyze_jd(title, content)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None

    return {
        "title": title,
        "content": content,
        "analysis": analysis_result,
    }


@app.post("/jobs/analyze", dependencies=[Depends(_one_request)])
def analyze_job_endpoint(job: JobLink):
    try:
        # 读取已打开、且与传入链接匹配的职位页
        jd = read_boss_jd(job.url)

        if not jd["title"] or len(jd["content"]) < 10:
            raise HTTPException(
                status_code=409,
                detail="页面标题或 JD 正文不完整，请检查浏览器页面。",
            )

        # 将正文交给现有的分析函数
        analysis = analyze_jd(jd["title"], jd["content"])

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None

    return {
        "title": jd["title"],
        "url": jd["url"],
        "analysis": analysis,
    }

def _search_events(query: JobSearch):
    """同一份搜索逻辑：普通接口收集最终结果，前端接口逐条发送进度。"""
    city, keyword = query.city.strip(), query.keyword.strip()
    if not city or not keyword:
        raise HTTPException(status_code=422, detail="城市和关键词不能为空白。")
    missing = [name for name in ("SERPAPI_API_KEY", "DEEPSEEK_API_KEY") if not os.getenv(name, "").strip()]
    if missing:
        raise HTTPException(status_code=503, detail="缺少环境变量：" + "、".join(missing) + "。请配置后重启程序。")

    yield {"type": "progress", "stage": "search", "message": "正在检查专用浏览器并搜索招聘网页…"}
    try:
        check_boss_browser()
        # 搜索网页数固定为 5，与本次想分析几个岗位分开，避免只搜到一个列表或其他网站。
        results = search_jobs(city, keyword, 5)
        yield {"type": "progress", "stage": "filter", "message": f"搜索到 {len(results)} 个网页，正在筛选并合并职位链接…"}
        filtered = filter_job(results, keyword)
        unique = {}
        for job in filtered:
            if is_boss_job_url(job["url"]):
                unique.setdefault(urlsplit(job["url"]).path, job)

        if len(unique) < query.max_results:
            listing = next((job for job in filtered if is_boss_list_url(job["url"])), None)
            if listing:
                yield {"type": "progress", "stage": "filter", "message": "正在从一个 BOSS 列表页补充岗位链接…"}
                open_boss_page(listing["url"])
                links = read_boss_job_links(listing["url"], 5)
                for job in filter_job(links, keyword):
                    if is_boss_job_url(job["url"]):
                        unique.setdefault(urlsplit(job["url"]).path, job)
        candidates = list(unique.values())[:query.max_results]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None

    logger.info("[搜索] 网页=%d，筛选后=%d，候选=%d，上限=%d", len(results), len(filtered), len(candidates), query.max_results)
    analyzed, errors = [], []
    for index, selected in enumerate(candidates, start=1):
        stage = "读取 JD"
        try:
            yield {"type": "progress", "stage": "jd", "message": f"正在读取第 {index}/{len(candidates)} 个岗位的 JD…"}
            open_boss_job(selected["url"])
            jd = read_boss_jd(selected["url"], wait_for_ready=True)
            title, content = jd["title"].strip(), jd["content"].strip()
            if not title or len(content) < 10:
                raise HTTPException(status_code=409, detail="页面标题或 JD 不完整，请检查登录或验证状态。")
            stage = "DeepSeek 分析"
            yield {"type": "progress", "stage": "analysis", "message": f"正在分析第 {index}/{len(candidates)} 个岗位：{title}"}
            analysis = analyze_jd(title, content)
            job = {"title": title, "url": selected["url"], "analysis": analysis}
            analyzed.append(job)
            yield {"type": "job", "job": job}
        except (HTTPException, ValueError, RuntimeError) as exc:
            code = exc.status_code if isinstance(exc, HTTPException) else (422 if isinstance(exc, ValueError) else 503)
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            logger.warning("[分析] 第 %d 个岗位在%s阶段失败，已停止；完成=%d", index, stage, len(analyzed))
            if not analyzed:
                raise HTTPException(status_code=code, detail=detail) from None
            errors.append({"title": selected["title"], "url": selected["url"], "stage": stage, "message": detail})
            break

    if errors:
        status, message = "partial", "中途失败，已停止后续调用；保留已完成的岗位分析。"
    elif not candidates:
        status, message = "no_matching_job", "未得到符合关键词且可读取的 BOSS 详情链接，未调用模型。"
    elif len(analyzed) < query.max_results:
        status, message = "completed", "本轮符合条件的不重复岗位不足目标数量，未额外搜索。"
    else:
        status, message = "completed", "已完成指定数量的岗位分析。"
    yield {"type": "result", "data": {
        "status": status, "city": city, "keyword": keyword, "requested_count": query.max_results,
        "search_count": len(results), "candidate_count": len(candidates), "count": len(analyzed),
        "results": analyzed, "errors": errors, "message": message,
    }}


@app.post("/jobs/search-analyze", dependencies=[Depends(_one_request)])
def search_and_analyze_endpoint(query: JobSearch):
    """关键词 → 筛选 → JD → 分析，返回最多 max_results 个岗位。"""
    for event in _search_events(query):
        if event["type"] == "result":
            return event["data"]


@app.post("/jobs/search-analyze-stream")
def stream_search_endpoint(query: JobSearch):
    """发送一行一个 JSON 事件，前端可以显示真实阶段和已经完成的岗位。"""
    def events():
        try:
            with _operation():
                for event in _search_events(query):
                    yield json.dumps(event, ensure_ascii=False) + "\n"
        except HTTPException as exc:
            yield json.dumps({"type": "error", "status_code": exc.status_code, "detail": exc.detail}, ensure_ascii=False) + "\n"
        except Exception:
            # 流响应已开始，使用错误事件收尾，不把内部异常或请求地址返回前端。
            logger.error("搜索流程发生未预期错误，已终止请求。")
            yield json.dumps({"type": "error", "status_code": 500, "detail": "服务遇到异常，请检查终端日志后重试。"}, ensure_ascii=False) + "\n"
    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

if __name__ == "__main__":
    import uvicorn

    # Uvicorn 负责启动 HTTP 服务；按 Ctrl+C 停止。
    uvicorn.run(app, host="127.0.0.1", port=8000)
