# 职引 · 招聘搜索与 JD 分析

一个基于 Python、FastAPI 和 DeepSeek 的本地招聘信息阅读助手。
在网页中输入城市和关键词，搜索并筛选招聘网页，读取受支持的 BOSS 岗位 JD，
逐个整理技术方向、明确要求和待核实信息；也可以直接粘贴 JD 分析。

目前是固定工作流应用，未实现自主 Tool Calling 或 RAG。

## 一条命令运行

在项目根目录执行：

```powershell
cd D:\Myproject\job-agent-simple
python start.py
```

启动器会优先使用项目已有的 .venv，启动本地服务并自动打开
http://127.0.0.1:8000 。Windows 也可以直接双击 **启动.bat**。

- 保持启动终端运行；按 Ctrl+C 停止。
- 默认保存 Python 代码后自动重载，不需要每次手动重启。
- 已运行同一应用时再次启动会打开已有页面，不重复启动服务。
- 旧接口或其他程序占用 8000 端口时，会明确提示；也可运行 `python start.py --port 8001`。
- 调试选项：`--no-browser` 不自动打开页面，`--no-reload` 关闭自动重载。
- 前端使用原生 HTML / CSS / JavaScript，不需要 Node.js 或前端构建步骤。

## 首次安装

建议 Python 3.10 或更高版本。已经安装好依赖时跳过本节。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

使用系统已经安装的 Chrome，不需要另行下载 Playwright Chromium。
非默认安装路径可通过 CHROME_PATH 指定。

## API Key 配置

继续使用环境变量 SERPAPI_API_KEY 和 DEEPSEEK_API_KEY。已有配置无需重填。
页面只显示配置是否存在，不接收、显示或保存真实密钥。

若尚未配置，可在启动应用的同一 PowerShell 终端用隐藏输入配置：

```powershell
$env:SERPAPI_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'SerpApi 密钥' -AsSecureString)).Password
$env:DEEPSEEK_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'DeepSeek 密钥' -AsSecureString)).Password
python start.py
```

缺少配置时页面给出对应变量名，并禁用需要它的提交按钮。
修改环境变量后重启应用。.env.example 只是变量说明，程序不会自动加载 .env 文件。

| 可选变量 | 默认值或用途 |
| --- | --- |
| DEEPSEEK_BASE_URL | https://api.deepseek.com |
| DEEPSEEK_MODEL | deepseek-chat |
| CHROME_PATH | Chrome 可执行文件；未配置时自动查找 PATH 和 Windows 常见位置 |

## 在网页中使用

### 关键词搜索

1. 点击“打开 BOSS 登录窗口”，在专用 Chrome 中手动完成登录或验证，保持窗口打开。
2. 回到页面点击“刷新状态”。浏览器就绪只表示端口可连接，不代表登录一定有效。
3. 填写城市、关键词、最多分析岗位数，点击“搜索并分析岗位”。
4. 页面显示实际阶段和已完成的岗位，结果保留原始职位链接。

每次只发送一次 SerpApi 搜索，获取最多 5 个网页；再按标题和摘要关键词筛选。
优先使用详情链接，不足时从一个受支持的 BOSS 列表读取最多 5 个详情链接。
链接按职位路径去重，忽略来源查询参数。之后顺序读取 JD、逐个调用 DeepSeek。

选择分析数量是上限，范围 1～5，不保证凑满。分析一个岗位调用一次模型，
最多 5 次。不会翻页、自动换关键词或自动重试。
无匹配结果时不调用模型。中途失败立即停止，保留已经完成的结果。
页面禁止重复提交，服务端也一次只处理一个分析任务。

### 粘贴 JD 分析

切换“粘贴 JD 分析”，填写岗位标题和至少 10 字的正文，点击“分析这份 JD”。
这个入口只需要 DeepSeek，不需要 SerpApi、Chrome 或 BOSS 登录。
“填入演示 JD”只填充明确标记的虚构示例；点击分析才调用真实模型。

结论基于提供或读取的正文，提示词要求区分明确要求、推测与待核实信息。
模型输出不代表招聘事实已核实，也不提供个人简历匹配。

## 项目目录

```text
job-agent-simple/
├── start.py                 # 网页启动入口，自动选择虚拟环境并打开浏览器
├── 启动.bat                 # Windows 双击启动
├── main.py                  # 保留的命令行练习入口
├── job_agent/
│   ├── api.py               # HTTP 接口、输入校验与流程进度
│   ├── static/
│   │   ├── index.html       # 页面结构
│   │   ├── style.css        # 桌面和手机样式
│   │   ├── app.js           # 表单提交、进度和结果展示
│   │   └── icon.svg
│   ├── cli.py               # 命令行搜索、一次关键词改写和分析
│   ├── search.py            # SerpApi 百度搜索
│   ├── job_filter.py        # 标题和摘要关键词筛选
│   ├── boss.py              # 专用 Chrome 准备和 BOSS JD 提取
│   └── llm.py               # DeepSeek 调用和输入上下文
├── tests/                   # 离线模拟测试
├── examples/liepin_jd.py     # 未接入主流程的旧提取练习
├── DEMO.md                  # 项目演示和面试讲解
├── requirements.txt
├── .env.example
└── .gitignore
```

前端 app.js 通过 fetch 请求 FastAPI。后端 _search_events 只执行一份搜索分析流程：
普通 JSON 接口取最终结果，网页接口逐行发送进度与岗位，不会重复执行搜索或模型调用。
模型和网页内容通过文本节点显示，仅支持安全的简单 Markdown 排版，不直接执行返回的 HTML。

## 接口与高级运行

接口文档仍保留在 http://127.0.0.1:8000/docs 。

| 接口 | 用途 |
| --- | --- |
| GET / | 交互页面 |
| GET /health | 配置与本机浏览器就绪状态，不返回密钥 |
| POST /browser/open | 打开固定 BOSS 首页供手动登录 |
| GET /jobs | 搜索和关键词筛选，不调用模型 |
| POST /jd | 接收 title 和 content，分析提供的 JD |
| POST /jobs/analyze | 单岗位调试，读取已打开的指定详情链接 |
| POST /jobs/search-analyze | 城市、关键词、数量 → 多岗位分析 JSON |
| POST /jobs/search-analyze-stream | 网页使用的逐行 JSON 进度流 |

关键词接口请求体：

```json
{"city": "郑州", "keyword": "AI", "max_results": 3}
```

JSON 结果包含 status、requested_count、search_count、candidate_count、count、results、
errors 和 message。results 每项含 title、url、analysis。

- completed：本轮结束，数量可能不足，结合 count 和 message 查看。
- no_matching_job：没有符合条件的支持链接，空结果、不调用模型。
- partial：中途失败，已有结果保留，失败岗位和阶段在 errors 中。
- 首条岗位之前失败：普通接口返回对应 HTTP 错误；流接口发送 type=error 事件和 status_code。
- 请求流只有执行阶段和逐个岗位结果，不是模型逐 token 输出；进度来自实际执行步骤。

仍可手动启动后端或保留的终端练习：

```powershell
.\.venv\Scripts\python.exe -m uvicorn job_agent.api:app --reload
.\.venv\Scripts\python.exe main.py
```

main.py 是独立命令行练习：最多两轮搜索、一次关键词改写，选择一个岗位读取 JD 或分析摘要。
它与网页的多岗位流程不同。

## 验证与限制

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m pip check
```

2026-10-19：118 项离线测试通过；另以无头 Chrome 模拟验证网页搜索、JD 输入、
多岗位结果、无结果、失败提示、重复提交、缺少配置、文本安全展示和手机布局。
本次前端开发没有新增真实 SerpApi 或 DeepSeek 请求。

历史单岗位流程曾真实联调成功；新的多岗位循环和网页完整操作使用模拟数据验证，
不能据此保证第三方招聘网站持续可用或模型分析准确。

当前 JD 读取只支持 BOSS 的 /job_detail/ 详情及 /zhaopin/ 列表模板。
仅支持标题或摘要包含完整关键词的匹配，可能漏掉同义词和分散写法。
网站验证、模板变化或正文缺失会导致读取停止，不自动处理验证码或绕过登录。
读取可见 JD 不代表核实了职位状态、公司或薪资。

专用 Chrome 资料位于系统临时目录 job-agent-boss-cdp，可能保留登录状态，不属于仓库；
程序不复制个人 Chrome 资料或导出 Cookie。本地应用仅绑定 127.0.0.1。
不保存数据库或查询历史，不自动投递，不发送消息。

## 安全边界与开发规范

应用仅面向本机个人使用，绑定 127.0.0.1，没有公网多用户认证。
接口校验本地主机名，拒绝带其他来源或跨站标记的操作请求；首页限制脚本来源并禁止被嵌入。
浏览器侧采用文本节点展示网页和模型内容，不直接插入外部 HTML。
手动 JD 标题最多 200 字，正文最多 30000 字；后端与模型适配函数均限制超长输入。

密钥只读环境变量，异常不返回请求地址或原始服务错误；.gitignore 排除密钥文件、
日志、常见证书和浏览器状态文件。系统临时目录中的 Chrome 登录资料仍由你自行管理，
不能提交到仓库。JD 中的指令按外部数据处理，提示词约束不能替代人工核实。

- .editorconfig：统一缩进、UTF-8 与文件结尾。
- .gitattributes：Python 与网页文件使用 LF，Windows 启动脚本使用 CRLF。
- requirements-dev.txt：仅离线接口测试需要的依赖。
- GitHub Actions：推送和 PR 运行离线测试，最小只读权限，第三方 Action 固定到提交 SHA。
  测试不需要配置真实 API Key，也不会调用真实招聘网站或模型。

开发环境运行测试前安装：
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

2026-10-19 进行了工作区与现有可达 Git 历史的密钥模式及已配置密钥匹配检查，
未发现真实密钥或私钥；118 项离线测试通过。在线依赖漏洞库查询因网络失败未完成，
pip check 通过仅表示依赖关系一致，不能据此认定没有已知漏洞。
