# 招聘会项目演示与面试准备

适用日期：2026 年 10 月 20 日。方向：AI 应用开发为主，兼顾后端开发。

## 项目能解决什么问题

输入城市和岗位关键词，搜索招聘网页，筛选并去重；在用户已登录的专用 Chrome 中读取受支持的 BOSS 职位 JD，然后交给 DeepSeek 整理技术方向、明确要求及待核实信息。也支持直接提交一段 JD 分析。

这是固定流程的大模型应用。搜索和浏览器读取由 Python 按预定顺序执行；尚未实现由模型自主决定调用工具。关键词筛选不是向量检索，目前没有 RAG。

## 今晚先做的事

1. 阅读并理解下面的项目介绍和关键函数，练习一次三分钟讲解。
2. 启动服务，在 /docs 确认有 POST /jobs/search-analyze，数量说明应为“最多分析并返回的岗位数”。
3. 先用提供 JD 的接口验证一次真实分析，并自行保留结果截图；这一步只需要 DeepSeek，不依赖招聘网站登录。
4. 有时间再演示关键词全流程。搜索排序、网站登录或验证会影响结果，不能保证返回指定条数。
5. 打印一页简历，手机保留 PDF。检查 GitHub 是否已包含本地的新目录；下面提供提交命令，本文不会自动推送代码。

## 启动服务

在项目根目录执行。已激活虚拟环境时可以把 .venv 路径替换为 python。

```powershell
cd D:\Myproject\job-agent-simple
python start.py
```

启动后自动打开 http://127.0.0.1:8000 ，可以直接使用网页；接口文档保留在 http://127.0.0.1:8000/docs 。如果端口已被占用，先在原服务终端按 Ctrl+C，不要同时启动两个服务。
API 密钥通过环境变量配置；不要把密钥展示给面试官或放进截图。

## 演示一 直接提供 JD

选择 POST /jd → Try it out → 输入以下 JSON → Execute。

以下内容是“演示用岗位描述”，不是已经核实的真实招聘职位。讲解时明确说明这一点。

```json
{
  "title": "演示用 AI 应用开发实习岗位",
  "content": "岗位职责：使用 Python 开发大模型应用，为业务功能提供 FastAPI 接口，对接大模型 API 并处理 JSON 数据。岗位要求：理解 HTTP 请求，掌握 Python 基础，了解 Git。加分项：有单元测试经验。公司名称、薪资、工作地点、招聘截止日期和是否仍在招聘均未提供。"
}
```

讲解重点：
- FastAPI 把 HTTP JSON 请求转换为 JobDescription 数据对象，先检查空白和正文长度。
- analyze_jd 把标题与正文序列化为 JSON，作为用户消息传给模型。
- call_deepseek 使用 OpenAI 兼容 SDK 调用 DeepSeek，提取回复文本。
- 返回分析不代表招聘事实已被核实；模型提示词要求指出缺失信息。

这一步每次 Execute 都会真实调用一次 DeepSeek；重复点击会再次产生请求。
如需现场展示一次成功结果，请自己运行并保存截图。本次准备工作未调用真实模型。

## 演示二 关键词到 JD 的完整流程

先准备专用 Chrome：

```powershell
.\.venv\Scripts\python.exe -m job_agent.boss --login
```

在专用窗口手动完成登录或验证，并保持窗口打开。
然后在 /docs 使用 POST /jobs/search-analyze：

```json
{
  "city": "郑州",
  "keyword": "AI",
  "max_results": 5
}
```

流程：check_boss_browser → search_jobs → filter_job → 合并详情链接并按路径去重 →
必要时读取一个列表 → 循环 open_boss_job / read_boss_jd → analyze_jd → 返回 results。

- max_results 是最多分析并返回的岗位数，不是保证数量。
- 本次只请求一次 SerpApi，最多读取一个列表的 5 条详情链接，不翻页、不补搜。
- SerpApi 返回的是招聘网页，可能包含其他网站或列表页，网页数不等于职位数。
- 每个岗位分别调用一次 DeepSeek，最多 5 次；完整执行可能较慢。
- status=completed 表示本轮已完成；即使数量不足也会返回 completed，请同时看 count 和 message。
- status=no_matching_job 表示没有符合条件的可用详情链接，不调用模型。
- status=partial 表示已经完成部分岗位、后续发生错误；检查 errors，程序已停止后续调用。
- 首个岗位之前失败会直接返回相应的 HTTP 错误。不要把登录失败或无匹配结果说成抓取成功。

目前的额外限制：详情链接只支持 BOSS 的 /job_detail/ 页面；列表只识别 /zhaopin/ 模板。
关键词必须完整出现在标题或摘要中，可能漏掉同义词或分散写法。
代码只检查本机浏览器端口是否就绪，不保证已登录；真正的登录或验证状态在读取页面时才会发现。
max_results 也用于限制一次搜索的网页数；减少到 1 可能使唯一搜索结果来自其他网站，从而找不到 BOSS 候选。

## 现场没有网络时

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

2026-10-19 实测 118 项离线测试全部通过，pip check 通过。
测试模拟了搜索、浏览器和模型，不消耗真实 API 额度。
可以展示测试结果和代码，但必须说明它是模拟验证，不能当作当天真实网站联调成功。
现有历史记录中曾成功进行过单岗位真实联调；新多岗位循环使用模拟数据验证。
现场网络或网站不可用时，展示之前由你真实运行并保存的截图，并说明截图时间。

## 优先理解的四个函数

1. job_agent/api.py 的 search_and_analyze_endpoint：串联整个关键词流程；for 循环控制数量，unique 按路径去重，异常时保留已完成结果。
2. job_agent/search.py 的 search_jobs：通过 urllib 请求 SerpApi 百度接口，只拿标题、链接和摘要。
3. job_agent/boss.py 的 read_boss_jd：通过 CDP 连接专用 Chrome，匹配指定职位标签页，定位并读取可见的 JD 正文。
4. job_agent/llm.py 的 call_deepseek：读取环境变量、设置超时和禁止自动重试，调用模型并提取回复。analyze_jd 负责组装它的输入。

项目入口有两套：
- API 主流程：python -m uvicorn job_agent.api:app --reload。
- python main.py：保留的命令行练习，结果不足时最多改写一次再搜索；它没有自动串联 API 的多岗位流程。

## 约四十五秒的自我介绍

我是中原工学院计算机专业本科生，想找 AI 应用开发相关实习，也有 Java 后端项目基础。
最近我用 Python、FastAPI 和 DeepSeek 做了一个招聘搜索与 JD 分析助手：
用户输入城市和关键词后，程序搜索并筛选网页，在用户登录后读取受支持的 BOSS 岗位 JD，再让模型整理技术要求和需要核实的信息。
我重点实践了接口参数校验、浏览器正文提取、模型上下文传递、去重和请求数量控制。
目前项目的 92 项离线测试通过，也做过单岗位真实联调。
它现在是固定工作流，我正在理解并完善这部分，后续希望在明确场景下学习检索和工具调用。

请用自己的话说，不要逐字背诵。提到的技术必须能在代码中指出对应位置。

## 常见追问

### 为什么要用 FastAPI
把原来的 Python 函数封装成 HTTP 接口。前端或其他程序可以发请求使用它，Pydantic 负责请求数据校验，/docs 可用于调试。FastAPI 本身不负责模型推理或搜索。

### 为什么不只把摘要交给模型
摘要往往缺失岗位职责和要求。JD 分析可以使用更长的职位正文，但网页缺失或未核实的信息仍不能编造；当前只读支持模板中的可见区域，不能保证所有网页都完整。

### 怎样控制重复和费用
按 BOSS 职位路径去重，忽略来源查询参数。接口只搜索一次；最多读一个列表、分析五个岗位。模型 SDK 禁止自动重试，任一岗位失败后停止。命令行练习另有最多两轮搜索、一次关键词改写的上限。

### 测试怎么做
用 unittest.mock 替换真实搜索、浏览器和模型调用，检查传参、调用次数、返回数量及停止条件。例如五个模拟岗位应各分析一次，同一岗位不同来源链接只分析一次，第二次失败要保留第一条结果并停止。

### 它算自主 Agent 吗
目前是固定流程的大模型应用，代码决定执行顺序。模型负责改写关键词或分析正文，还没有自主选择工具、规划任务或多 Agent 协作。当前没有 RAG。

### 你具体做了什么
据实说明自己写过、改过并理解的部分，也说明使用了 AI 辅助编程。可以举例：关键词改写、接口参数校验、JD 提取调试。不要把 AI 生成后还没理解的测试和模块描述为完全独立设计。

### 下一步怎么做
先完善用户体验和已有流程的稳定性，再选一个真实需求引入结构化信息提取或检索；今晚不为增加简历关键词而临时接入尚未理解的框架。

## GitHub 同步前核对

本地存在目录整理和功能修改，尚未全部提交。当前项目已有 .gitignore，忽略 .venv、缓存和 .env；但不能仅凭忽略规则认定历史中没有密钥。

先执行：
```powershell
git status
git diff --stat
```

确认变更后，显式添加项目文件，避免把密钥或浏览器资料放进仓库：
```powershell
git add README.md DEMO.md requirements.txt .gitignore .env.example main.py start.py job_agent tests examples
git add -- "启动.bat"
git add -u
git diff --cached --stat
git diff --cached --check
```

在自己的终端检查暂存内容，确认没有真实密钥、个人浏览器资料或不打算公开的内容，再执行：
```powershell
git commit -m "完善招聘搜索和 JD 分析接口与离线测试"
git push origin main
```

若 .env.example 仍有改动，确认它只包含变量说明或占位值。本次准备工作没有自动提交或推送。
