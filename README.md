# 极简 AI 招聘搜索助手

固定流程：输入城市、岗位关键词与数量 → SerpApi 百度搜索 → 数量不足时改写关键词并补充搜索一次 → DeepSeek 分析 → 终端输出。
这是学习用的固定流程应用，暂不使用 Tool Calling 或自主决策。
默认最多保留 3 条，用户可输入 1~20 条；每轮获取一页结果，最多搜索两轮，按链接去重。不访问网页详情，也不保存数据库。
搜索网页可能是招聘列表页或无关页面，不代表已确认的有效职位。

## 在 VS Code 的 PowerShell 终端运行

建议使用 Python 3.10 或更高版本。

```powershell
cd D:\Myproject\job-agent-simple
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

在同一个终端配置 `SERPAPI_API_KEY` 与 `DEEPSEEK_API_KEY`。
如果环境变量已经存在，可跳过配置。下面通过隐藏输入读取密钥，避免真实密钥进入命令历史：

```powershell
$env:SERPAPI_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'SerpApi 密钥' -AsSecureString)).Password
$env:DEEPSEEK_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'DeepSeek 密钥' -AsSecureString)).Password
python main.py
```

输入示例：城市 `郑州`，岗位关键词 `AI Agent 开发`。
以后在已配置变量、已激活虚拟环境的终端中，只需 `python main.py`。
如果 PowerShell 不允许激活虚拟环境，可以直接用 `.\.venv\Scripts\python.exe` 替代上面的 `python`，无需修改执行策略。
`.env.example` 只是参考，不会自动加载。不要把真实密钥写入文件或提交到 Git。

可选配置（通常不需要）：

```powershell
$env:DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
$env:DEEPSEEK_MODEL = 'deepseek-chat'
```

## 优先理解三个函数

1. `main.py` 的 `main()`：接收输入，调用 `search_jobs(city, keyword)`，打印结果，然后调用 `analyze_jobs(results)`。
2. `search.py` 的 `search_jobs()`：用标准库发送 HTTP 请求，搜索词为“城市 岗位关键词 招聘”，单轮默认最多返回 3 条，提取 `organic_results` 中的 `title`、`link`、`snippet`，组成字典列表。
3. `llm.py` 的 `analyze_jobs()`：把字典列表转成 JSON 放入用户消息，通过 OpenAI Python SDK 调用 DeepSeek，返回 `response.choices[0].message.content` 中的分析文本。

数据示例：`[{"title": "网页标题", "url": "原始网址", "snippet": "搜索摘要"}]`。
空结果不会调用模型。请求超时或缺少密钥时显示中文错误，不打印含密钥的请求 URL 或原始 API 错误。
提示词要求区分摘要证据、推测和待核实信息；模型仍可能误判，分析需要根据原始链接人工核实。

接口参考：[SerpApi 百度搜索](https://serpapi.com/baidu-search-api)、[DeepSeek 官方示例](https://api-docs.deepseek.com/)。
## 离线检查关键词改写流程

```powershell
python -m unittest -v test_flow
```

测试使用假密钥并屏蔽真实 API 调用，无需配置真实密钥。
运行流程最多搜索两次、改写一次、分析一次；达到去重后的目标数量即停止。
关键词重复检查忽略大小写和多余空白；结果按原始链接（忽略首尾空白）去重。
不同链接指向同一岗位、关键词语义相同但写法不同，目前无法识别。
任一步 API 失败都会显示错误并终止当前流程，不自动重试。
终端日志显示搜索轮次、返回/新增/保留数量及停止原因，不保存日志文件。

## FastAPI 搜索接口

`api_demo.py` 的 GET /jobs 调用真实 SerpApi 搜索，读取服务端环境变量 `SERPAPI_API_KEY`。
当前接口只做一轮搜索，不调用 DeepSeek；`main.py` 仍保留原有关键词改写、补充搜索和分析流程。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe api_demo.py
```

保持终端运行，在浏览器打开：

- `http://127.0.0.1:8000/`：确认服务启动。
- `http://127.0.0.1:8000/jobs?city=郑州&keyword=Python&max_results=3`：真实搜索。
- `http://127.0.0.1:8000/docs`：接口文档，可通过 Try it out 填参数后 Execute。

参数：city 和 keyword 必填，去掉首尾空白后不能为空，长度上限分别为 30 和 100；max_results 默认为 3，允许 1~20。
成功返回 city、keyword、count 和 results；没有结果时仍返回 200，count 为 0。
每次合法请求会发起一次真实搜索，不自动重试；刷新页面也会再次调用，请控制验证次数。

错误响应：参数缺失、长度/数量不合法或纯空白返回 422；搜索函数参数错误返回 400；搜索服务失败返回 503。
错误使用 FastAPI 的 detail 字段，不将原始异常或含密钥的请求 URL 返回给客户端。
按 Ctrl+C 停止服务。修改代码后需重启，再验证。

离线测试（无需真实密钥，不发送搜索或模型请求）：

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_api test_flow
```
