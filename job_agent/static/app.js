"use strict";
// 前端只收集输入和展示结果；搜索、读取网页及模型调用仍由 Python 完成。
const $ = (id) => document.getElementById(id);
let mode = "search", busy = false, service = null, timer = null, started = 0;
let displayed = [];
const stageOrder = ["search", "filter", "jd", "analysis"];

function notice(message, success = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("success", success);
  $("notice").hidden = !message;
}
function updateButtons() {
  const configured = service && service.deepseek_configured;
  $("search-form").querySelector("button[type=submit]").disabled =
    busy || !configured || !service.serpapi_configured || !service.browser_ready;
  $("jd-form").querySelector("button[type=submit]").disabled = busy || !configured;
  document.querySelectorAll(".tab").forEach((button) => { button.disabled = busy; });
  $("fill-example").disabled = busy;
  $("open-browser").disabled = busy;
}
function switchMode(next) {
  mode = next;
  $("search-form").hidden = next !== "search";
  $("jd-form").hidden = next !== "jd";
  $("form-heading").textContent = next === "search" ? "设置搜索条件" : "提供岗位描述";
  $("mode-note").textContent = next === "search"
    ? "目前支持 BOSS 部分职位与列表模板。首次使用请在专用浏览器中手动完成登录。"
    : "直接分析你提供的正文，不访问招聘网站，也不需要登录 BOSS。";
  document.querySelectorAll(".tab").forEach((button) => {
    const active = button.dataset.mode === next;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
}
function errorMessage(data) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => (item.loc || []).slice(1).join(" / ") + "：" + item.msg).join("\n");
  return "服务未能完成请求，请查看终端日志后重试。";
}
async function jsonRequest(path, options = {}) {
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error("无法连接本地服务，请确认启动终端仍在运行，然后刷新页面。"); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorMessage(data));
  return data;
}
async function refreshStatus() {
  $("refresh-status").disabled = true;
  try {
    service = await jsonRequest("/health");
    $("service-status").replaceChildren();
    [
      [service.serpapi_configured, "搜索服务"],
      [service.deepseek_configured, "分析服务"],
      [service.browser_ready, "BOSS 浏览器"],
    ].forEach(([ready, name]) => {
      const chip = document.createElement("span");
      chip.className = "chip " + (ready ? "ready" : "missing");
      chip.textContent = name + (ready ? "已就绪" : "待准备");
      $("service-status").append(chip);
    });
    const missing = [];
    if (!service.serpapi_configured) missing.push("SERPAPI_API_KEY");
    if (!service.deepseek_configured) missing.push("DEEPSEEK_API_KEY");
    $("setup-message").textContent = missing.length
      ? "未配置：" + missing.join("、") + "。请在启动终端配置对应环境变量并重启；密钥无需填入页面。"
      : service.browser_ready
        ? "服务配置已就绪。请确认专用 Chrome 已手动登录；浏览器就绪不代表已通过网站验证。"
        : "分析服务已就绪，可直接粘贴 JD。关键词搜索请先打开 BOSS 登录窗口，登录后刷新状态。";
  } catch (error) {
    service = null;
    notice(error.message);
  } finally {
    $("refresh-status").disabled = false;
    updateButtons();
  }
}
function setStage(stage, message) {
  $("progress-message").textContent = message;
  const current = stageOrder.indexOf(stage);
  document.querySelectorAll(".steps li").forEach((step, index) => {
    step.classList.toggle("current", index === current);
    step.classList.toggle("done", index < current);
  });
}
function begin() {
  busy = true; displayed = [];
  $("job-results").replaceChildren();
  $("error-box").hidden = true;
  $("result-summary").hidden = true;
  $("empty-state").hidden = true;
  $("progress").hidden = false;
  document.querySelector(".steps").hidden = mode === "jd";
  $("result-count").textContent = "正在处理";
  started = Date.now();
  $("elapsed").textContent = "0 秒";
  timer = setInterval(() => {
    $("elapsed").textContent = Math.floor((Date.now() - started) / 1000) + " 秒";
  }, 1000);
  updateButtons();
}
function finish() {
  busy = false;
  clearInterval(timer);
  $("progress").hidden = true;
  updateButtons();
}
function showError(message) {
  $("error-box").textContent = message;
  $("error-box").hidden = false;
  $("result-count").textContent = displayed.length ? "已完成 " + displayed.length + " 个" : "未完成";
  if (!displayed.length) {
    $("empty-state").hidden = false;
    $("empty-title").textContent = "本次请求未完成";
    $("empty-description").textContent = "请先处理上方提示，再发起新的请求。不会自动重试。";
  }
}
function appendInline(parent, text) {
  // 只识别 **加粗**，其余全部作为文本显示，防止外部 JD 或模型回复执行 HTML。
  text.split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2); parent.append(strong);
    } else parent.append(document.createTextNode(part));
  });
}
function renderAnalysis(content) {
  const container = document.createElement("div");
  container.className = "analysis-text";
  let list = null;
  String(content || "").split(/\r?\n/).forEach((line) => {
    const text = line.trim();
    if (!text) { list = null; return; }
    const bullet = text.match(/^[-*•]\s+(.+)/);
    const ordered = text.match(/^\d+[.、)]\s*(.+)/);
    if (bullet || ordered) {
      const kind = bullet ? "UL" : "OL";
      if (!list || list.tagName !== kind) { list = document.createElement(kind); container.append(list); }
      const li = document.createElement("li"); appendInline(li, (bullet || ordered)[1]); list.append(li);
    } else {
      list = null;
      const heading = text.match(/^#{1,6}\s+(.+)/);
      const element = document.createElement(heading ? "h4" : "p");
      appendInline(element, heading ? heading[1] : text);
      container.append(element);
    }
  });
  return container;
}
function addJob(job) {
  displayed.push(job);
  $("empty-state").hidden = true;
  const card = document.createElement("article");
  card.className = "job-card";
  const heading = document.createElement("div"); heading.className = "job-title-row";
  const number = document.createElement("span"); number.className = "job-number";
  number.textContent = String(displayed.length).padStart(2, "0");
  const info = document.createElement("div"), title = document.createElement("h3");
  title.textContent = job.title; info.append(title);
  let url = null;
  try {
    const parsed = new URL(job.url);
    if (["https:", "http:"].includes(parsed.protocol)) url = parsed.href;
  } catch { /* 手动 JD 没有原始链接。 */ }
  if (url) {
    const link = document.createElement("a");
    link.className = "source-link"; link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = "查看原始职位 ↗"; info.append(link);
  } else {
    const source = document.createElement("div"); source.className = "jd-source";
    source.textContent = "来源：你提供的 JD 正文"; info.append(source);
  }
  heading.append(number, info); card.append(heading, renderAnalysis(job.analysis));
  $("job-results").append(card);
  $("result-count").textContent = "已完成 " + displayed.length + " 个";
}
function finalResult(data) {
  displayed = [];
  $("job-results").replaceChildren();
  (data.results || []).forEach(addJob);
  $("result-count").textContent = "完成 " + (data.count || 0) + " / " + data.requested_count + " 个";
  $("result-summary").textContent = data.message || "分析完成。";
  $("result-summary").classList.toggle("warning", data.status === "partial" || !data.count);
  $("result-summary").hidden = false;
  if (data.errors && data.errors.length) {
    showError(data.errors.map((item) => item.title + " · " + item.stage + "\n" + item.message).join("\n\n"));
  }
  if (!data.count) {
    $("empty-state").hidden = false;
    $("empty-title").textContent = "本轮没有找到可分析的岗位";
    $("empty-description").textContent = "可以修改关键词后重新搜索，或切换到「粘贴 JD 分析」。";
  }
}
async function search(event) {
  event.preventDefault();
  if (busy) return;
  const city = $("city").value.trim(), keyword = $("keyword").value.trim();
  if (!city || !keyword) { notice("请填写城市和岗位关键词，不能只输入空格。"); return; }
  notice(""); begin();
  setStage("search", "正在检查浏览器并搜索相关招聘网页…");
  try {
    const response = await fetch("/jobs/search-analyze-stream", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({city, keyword, max_results: Number($("max-results").value)}),
    });
    if (!response.ok) throw new Error(errorMessage(await response.json().catch(() => ({}))));
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = "", completed = false, failed = false;
    function consume(line) {
      if (!line.trim()) return;
      const item = JSON.parse(line);
      if (item.type === "progress") setStage(item.stage, item.message);
      else if (item.type === "job") addJob(item.job);
      else if (item.type === "result") { finalResult(item.data); completed = true; }
      else if (item.type === "error") { failed = true; showError(item.detail); }
    }
    while (true) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
      const lines = buffer.split("\n"); buffer = lines.pop();
      lines.forEach(consume);
      if (done) break;
    }
    if (buffer.trim()) consume(buffer);
    if (!completed && !failed) throw new Error("与服务的连接提前结束，已显示的结果会保留；请检查终端日志。");
  } catch (error) {
    showError(error instanceof TypeError ? "无法连接本地服务，请检查启动终端。" : error.message);
  } finally { finish(); }
}
async function analyzeJD(event) {
  event.preventDefault();
  if (busy) return;
  const title = $("jd-title").value.trim(), content = $("jd-content").value.trim();
  if (!title || Array.from(content).length < 10) { notice("请填写岗位标题，并提供至少 10 字的 JD 正文。"); return; }
  notice(""); begin();
  setStage("analysis", "正在依据你提供的 JD 分析技术要求与待核实信息…");
  try {
    const data = await jsonRequest("/jd", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({title, content})});
    addJob(data);
    $("result-summary").textContent = "分析完成。结论仅基于你提供的标题与正文，仍需核实。";
    $("result-summary").classList.remove("warning");
    $("result-summary").hidden = false;
  } catch (error) { showError(error.message); }
  finally { finish(); }
}
document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => { if (!busy) switchMode(button.dataset.mode); });
});
$("search-form").addEventListener("submit", search);
$("jd-form").addEventListener("submit", analyzeJD);
$("refresh-status").addEventListener("click", refreshStatus);
$("open-browser").addEventListener("click", async () => {
  $("open-browser").disabled = true;
  try {
    const data = await jsonRequest("/browser/open", {method: "POST"});
    notice(data.message, true);
  } catch (error) { notice(error.message); }
  finally { updateButtons(); }
});
function updateLength() {
  const length = Array.from($("jd-content").value.trim()).length;
  $("jd-length").textContent = "正文 " + length + " 字 · 至少需要 10 字";
}
$("jd-content").addEventListener("input", () => { updateLength(); $("example-hint").hidden = true; });
$("fill-example").addEventListener("click", () => {
  $("jd-title").value = "演示用 AI 应用开发实习岗位";
  $("jd-content").value = "岗位职责：使用 Python 开发大模型应用，使用 FastAPI 提供接口，对接模型 API 并处理 JSON 数据。岗位要求：掌握 Python 基础，理解 HTTP，能够使用 Git。加分项：有单元测试经验。公司名称、薪资、工作地点、招聘截止日期与是否仍在招聘未提供。";
  $("example-hint").hidden = false; updateLength();
});
switchMode("search");
updateButtons();
refreshStatus();
