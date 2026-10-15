"""招聘搜索 HTTP 接口：验证参数，调用搜索函数，返回 JSON。"""

from fastapi import FastAPI, HTTPException, Query
from search import search_jobs

app = FastAPI(title="招聘搜索接口")


@app.get("/")
def home():
    """浏览器访问根路径时执行。"""
    return {"message": "FastAPI 服务已启动", "docs": "/docs"}


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
    except ValueError:
        raise HTTPException(status_code=400, detail="搜索参数不正确，请检查后重试。") from None
    except RuntimeError:
        # 不把原始异常或请求 URL 返回给客户端，避免泄露密钥。
        raise HTTPException(
            status_code=503,
            detail="搜索服务暂时不可用，请检查服务端 SERPAPI_API_KEY、网络或账户额度。",
        ) from None

    return {"city": city, "keyword": keyword, "count": len(results), "results": results}


if __name__ == "__main__":
    import uvicorn

    # Uvicorn 负责启动 HTTP 服务；按 Ctrl+C 停止。
    uvicorn.run(app, host="127.0.0.1", port=8000)
