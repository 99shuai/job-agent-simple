from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

def main():
    url = "https://www.liepin.com/job/1984085363.shtml"

    # 请求职位详情页
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urlopen(request, timeout=20) as response:
        html = response.read().decode("utf-8")

    # 解析 HTML，找到 JD 所在的区域
    soup = BeautifulSoup(html, "html.parser")
    jd_element = soup.select_one(".job-intro-container .paragraph dd")

    if jd_element is None:
        print("没有找到 JD 正文，请检查页面是否发生变化或需要验证。")
    else:
        content = jd_element.get_text("\n", strip=True)
        print(content)

if __name__ == "__main__":
    main()
