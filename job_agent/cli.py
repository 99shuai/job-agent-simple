"""固定流程：输入 → 搜索 → 分析 → 终端输出。"""

import os

from .search import search_jobs
from .llm import analyze_jobs, analyze_jd
from .boss import fetch_boss_jd, is_boss_job_url
from .llm import expand_keyword

def main() -> None:
    """组织流程，各步骤的具体工作交给普通函数。"""
    # 只读取环境变量，不加载或保存真实密钥文件。
    missing = [name for name in ("SERPAPI_API_KEY", "DEEPSEEK_API_KEY")
               if not os.getenv(name, "").strip()]
    if missing:
        print("缺少环境变量：" + "、".join(missing))
        print("请按 README.md 配置后重新运行。")
        return
    try:
        city = input("请输入城市（例如：郑州）：").strip()
        keyword = input("请输入岗位关键词（例如：AI Agent 开发）：").strip()
        quantity = input("请输入搜索结果数量（1~20,默认 3）：").strip()
        try:
            max_results = int(quantity or "3")
        except ValueError:
            print("搜索结果数量必须是 1~20 的整数，请重新运行。")
            return
        if not 1 <= max_results <= 20:
            print("搜索结果数量必须在 1~20 之间，请重新运行。")
            return
        if not city or not keyword:
            print("城市和岗位关键词不能为空，请重新运行。")
            return
        results = []
        seen_urls = set()
        searched_keywords = set()
        # 最多搜索两次：原关键词一次、改写关键词一次。
        for round_number in range(1, 3):
            # 忽略大小写和多余空白，避免同一个关键词反复搜索。
            keyword_id = " ".join(keyword.split()).casefold()
            if not keyword_id:
                print("[搜索] 改写关键词为空，停止搜索。")
                break
            if keyword_id in searched_keywords:
                print("[搜索] 改写关键词与已搜索关键词重复，停止搜索。")
                break
            searched_keywords.add(keyword_id)
            print(f"[搜索] 第 {round_number}/2 次请求，目标 {max_results} 条。")
            batch = search_jobs(city, keyword, max_results)
            added = 0
            for result in batch:
                # 按链接去掉首轮、次轮内部及跨轮重复结果。
                url_id = result['url'].strip()
                if url_id not in seen_urls:
                    seen_urls.add(url_id)
                    results.append(result)
                    added += 1
            results = results[:max_results]
            print(f"[搜索] 本轮返回 {len(batch)} 条，新增 {added} 条，保留 {len(results)} 条。")
            if len(results) >= max_results:
                print("[搜索] 已满足数量要求，停止搜索。")
                break
            if round_number == 2:
                print("[搜索] 已达到两次搜索上限，停止搜索。")
                break
            print("[改写] 结果不足，调用 DeepSeek 改写一次关键词。")
            keyword = expand_keyword(keyword)

        if not results:
            print("未找到搜索结果，未调用岗位分析。可换一个关键词重试。")
            return

        print("\n搜索结果（仅为网页线索，尚未核实为有效职位）：")
        for number, result in enumerate(results, 1):
            print(f"\n{number}. {result['title']}")
            print(f"链接：{result['url']}")
            print(f"摘要：{result['snippet'] or '搜索接口未提供摘要'}")

        # 搜索摘要与网页正文分开处理；只有支持的详情链接才提供 JD 选项。
        boss_indexes = [
            number for number, result in enumerate(results, 1)
            if is_boss_job_url(result["url"])
        ]
        if boss_indexes:
            options = "、".join(map(str, boss_indexes))
            choice = input(f"\n读取一个 BOSS 岗位的 JD，输入编号（{options}；回车只分析摘要）：").strip()
            if choice:
                try:
                    selected_number = int(choice)
                except ValueError:
                    raise ValueError("JD 编号必须是上面列出的整数。") from None
                if selected_number not in boss_indexes:
                    raise ValueError("请选择支持的 BOSS 职位详情编号。")
                selected = results[selected_number - 1]
                jd = fetch_boss_jd(selected["url"])
                print(f"\n岗位：{jd['title'] or selected['title']}\n来源：{jd['url']}")
                print("\n网页 JD（页面可见正文，完整性待核实）：\n" + jd["content"])
                print("\n[分析] 调用 DeepSeek 分析这一个岗位的 JD……")
                print(analyze_jd(jd["title"] or selected["title"], jd["content"]))
                return
        else:
            print("[JD] 本次没有可读取的 BOSS 职位详情链接，仅分析搜索摘要。")
        print("\n尚未核实：完整 JD、公司主体、薪资、工作地点、技术要求、是否仍在招聘。")
        print("结论只基于搜索摘要，未读取完整 JD。")
        print("\n[分析] 调用 DeepSeek 分析现有结果……")
        print("\nDeepSeek 分析：\n" + analyze_jobs(results))
    except (RuntimeError, ValueError) as exc:
        print(f"错误：{exc}；本次流程已终止，不再重试。")
    except (KeyboardInterrupt, EOFError):
        print("\n输入已取消，程序结束。")


if __name__ == "__main__":
    main()