from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests
from collections import deque
import random
from functools import lru_cache
import time

app = Flask(__name__)
CORS(app)

WIKI_API_URL = "https://zh.wikipedia.org/w/api.php"
HEADERS = {
    'User-Agent': 'WikiGameBot/1.0 (contact: your_email@example.com)'
}
REQUEST_TIMEOUT = 10
MAX_SEARCH_DEPTH = 3
MAX_BFS_SECONDS = 8
MAX_BFS_PAGES = 80
MAX_LINKS_PER_PAGE = 120
MAX_BACKLINKS = 500
MIN_RANDOM_LINKS = 20
TITLE_VARIANTS = str.maketrans({
    "学": "學",
    "台": "臺",
    "语": "語",
    "计": "計",
    "算": "算",
    "机": "機",
    "电": "電",
    "脑": "腦",
    "软": "軟",
    "件": "件",
    "国": "國",
    "会": "會",
    "发": "發",
    "开": "開",
    "门": "門",
    "体": "體",
    "风": "風",
    "乐": "樂",
    "网": "網",
    "维": "維",
    "论": "論",
    "实": "實",
    "验": "驗",
    "类": "類",
    "标": "標",
    "准": "準",
})


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/api/task')
def get_task():
    return jsonify(generate_random_task())


def generate_random_task():
    for _ in range(8):
        start = get_random_wiki_title()
        if not start or not is_good_random_title(start):
            continue

        current_title, start_links = get_wiki_links_internal(start)
        playable_links = filter_playable_links(start_links)
        if len(playable_links) < MIN_RANDOM_LINKS:
            continue

        if random.random() < 0.65:
            return {
                "start": current_title,
                "target": random.choice(playable_links),
                "difficulty": "easy"
            }

        middle = random.choice(playable_links[:80])
        middle_title, middle_links = get_wiki_links_internal(middle)
        target_links = filter_playable_links(middle_links)
        if target_links:
            return {
                "start": current_title,
                "target": random.choice(target_links),
                "difficulty": "normal",
                "via": middle_title
            }

    return random.choice(fallback_tasks())


def fallback_tasks():
    return [
        {"start": "Python", "target": "高級語言", "difficulty": "fallback"},
        {"start": "Arch Linux", "target": "Linux", "difficulty": "fallback"},
        {"start": "C++", "target": "電腦科學", "difficulty": "fallback"},
        {"start": "米哈遊", "target": "哲學", "difficulty": "fallback"}
    ]


def get_random_wiki_title():
    params = {
        "action": "query",
        "format": "json",
        "list": "random",
        "rnnamespace": 0,
        "rnlimit": 1
    }

    try:
        res = requests.get(
            WIKI_API_URL,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )
        res.raise_for_status()
        data = res.json()
        random_pages = data.get("query", {}).get("random", [])
        if not random_pages:
            return None
        return random_pages[0].get("title")
    except requests.RequestException as exc:
        app.logger.warning("Wikipedia random request failed: %s", exc)
        return None
    except ValueError as exc:
        app.logger.warning("Invalid Wikipedia random response: %s", exc)
        return None


def filter_playable_links(links):
    blocked_prefixes = (
        "Wikipedia:",
        "Help:",
        "Template:",
        "Category:",
        "Portal:",
        "File:",
        "Module:",
        "Draft:",
    )

    return [
        link
        for link in links
        if not link.startswith(blocked_prefixes)
        and len(link) <= 24
        and "消歧义" not in link
        and "消歧義" not in link
    ]


def is_good_random_title(title):
    blocked_fragments = (
        "列表",
        "年表",
        "消歧义",
        "消歧義",
        "模板",
        "/",
    )

    return (
        2 <= len(title) <= 18
        and not any(fragment in title for fragment in blocked_fragments)
    )


# 內部函式：專門用來抓取連結
@lru_cache(maxsize=512)
def get_wiki_links_internal(title):
    links = []
    params = {
        "action": "query",
        "prop": "links",
        "titles": title,
        "pllimit": "max",
        "format": "json",
        "redirects": 1
    }

    try:
        normalized_title = title

        while True:
            res = requests.get(
                WIKI_API_URL,
                params=params,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT
            )
            res.raise_for_status()
            data = res.json()

            pages = data.get("query", {}).get("pages", {})
            if not pages:
                return title, []

            page_id, page = next(iter(pages.items()))
            if page_id == "-1":
                return title, []

            normalized_title = page.get("title", normalized_title)
            raw_links = page.get("links", [])
            links.extend(
                link["title"]
                for link in raw_links
                if link.get("ns") == 0 and "title" in link
            )

            continuation = data.get("continue", {}).get("plcontinue")
            if not continuation:
                break

            params["plcontinue"] = continuation

        return normalized_title, sorted(set(links))
    except requests.RequestException as exc:
        app.logger.warning("Wikipedia request failed for %s: %s", title, exc)
        return title, []
    except ValueError as exc:
        app.logger.warning("Invalid Wikipedia response for %s: %s", title, exc)
        return title, []


@lru_cache(maxsize=512)
def get_wiki_extract_internal(title):
    params = {
        "action": "query",
        "prop": "extracts",
        "titles": title,
        "exintro": 1,
        "explaintext": 1,
        "format": "json",
        "redirects": 1
    }

    try:
        res = requests.get(
            WIKI_API_URL,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )
        res.raise_for_status()
        data = res.json()
        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return ""

        _, page = next(iter(pages.items()))
        return page.get("extract", "")
    except requests.RequestException as exc:
        app.logger.warning("Wikipedia extract request failed for %s: %s", title, exc)
        return ""
    except ValueError as exc:
        app.logger.warning("Invalid Wikipedia extract response for %s: %s", title, exc)
        return ""


@lru_cache(maxsize=256)
def get_wiki_backlinks_internal(title):
    backlinks = []
    params = {
        "action": "query",
        "list": "backlinks",
        "bltitle": title,
        "bllimit": "max",
        "blnamespace": 0,
        "format": "json"
    }

    try:
        while len(backlinks) < MAX_BACKLINKS:
            res = requests.get(
                WIKI_API_URL,
                params=params,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT
            )
            res.raise_for_status()
            data = res.json()

            backlinks.extend(
                item["title"]
                for item in data.get("query", {}).get("backlinks", [])
                if "title" in item
            )

            continuation = data.get("continue", {}).get("blcontinue")
            if not continuation:
                break

            params["blcontinue"] = continuation

        return set(backlinks[:MAX_BACKLINKS])
    except requests.RequestException as exc:
        app.logger.warning("Wikipedia backlink request failed for %s: %s", title, exc)
        return set()
    except ValueError as exc:
        app.logger.warning("Invalid Wikipedia backlink response for %s: %s", title, exc)
        return set()


@app.route('/api/wiki')
def get_wiki_by_query():
    keyword = (
        request.args.get("keyword", "").strip()
        or request.args.get("title", "").strip()
    )
    if not keyword:
        return jsonify({"error": "缺少 keyword 或 title 參數"}), 400

    return get_wiki_response(keyword)


@app.route('/api/wiki/<path:title>')
def get_wiki(title):
    return get_wiki_response(title)


def get_wiki_response(keyword):
    current_title, links = get_wiki_links_internal(keyword)
    if not links:
        return jsonify({
            "error": "找不到頁面或連結",
            "keyword": keyword,
            "current_title": current_title,
            "link_count": 0
        }), 404

    return jsonify({
        "keyword": keyword,
        "current_title": current_title,
        "extract": get_wiki_extract_internal(current_title),
        "link_count": len(links),
        "links": links
    })


@app.route('/api/shortest_path')
def shortest_path_by_query():
    start = request.args.get("start", "").strip()
    target = request.args.get("target", "").strip()
    if not start or not target:
        return jsonify({"error": "缺少 start 或 target 參數"}), 400

    return find_shortest_path(start, target)


@app.route('/api/shortest_path/<path:start>/<path:target>')
def shortest_path(start, target):
    return find_shortest_path(start, target)


def find_shortest_path(start, target):
    # 先用反向連結找 1 到 3 步路徑，比盲目 BFS 穩定很多。
    started_at = time.monotonic()

    if same_title(start, target):
        return jsonify({"path": [start]})

    _, start_links = get_wiki_links_internal(start)
    direct_match = find_matching_title(start_links, target)
    if direct_match:
        return jsonify({"path": [start, direct_match]})

    target_backlinks = get_wiki_backlinks_internal(target)
    two_hop_matches = [link for link in start_links if link in target_backlinks]
    if two_hop_matches:
        return jsonify({"path": [start, two_hop_matches[0], target]})

    searched_pages = 0
    candidates = prioritize_links(start_links, target)[:MAX_BFS_PAGES]
    for middle in candidates:
        if time.monotonic() - started_at > MAX_BFS_SECONDS:
            return jsonify({
                "path": [],
                "message": f"搜尋超過 {MAX_BFS_SECONDS} 秒，先停止避免卡住"
            })

        _, middle_links = get_wiki_links_internal(middle)
        searched_pages += 1

        direct_match = find_matching_title(middle_links, target)
        if direct_match:
            return jsonify({"path": [start, middle, direct_match]})

        bridge_matches = [link for link in middle_links if link in target_backlinks]
        if bridge_matches:
            return jsonify({"path": [start, middle, bridge_matches[0], target]})

    # 找不到時再用很小範圍 BFS 補搜，避免完全漏掉特殊頁面。
    queue = deque([(start, [start])])
    visited = {start}

    while queue:
        if time.monotonic() - started_at > MAX_BFS_SECONDS:
            return jsonify({
                "path": [],
                "message": f"搜尋超過 {MAX_BFS_SECONDS} 秒，先停止避免卡住"
            })

        if searched_pages >= MAX_BFS_PAGES:
            return jsonify({
                "path": [],
                "message": f"已檢查 {MAX_BFS_PAGES} 個頁面，未找到建議路徑"
            })

        curr, path = queue.popleft()
        if len(path) - 1 >= MAX_SEARCH_DEPTH:
            continue

        _, links = get_wiki_links_internal(curr)
        searched_pages += 1

        direct_match = find_matching_title(links, target)
        if direct_match:
            return jsonify({"path": path + [direct_match]})

        links = prioritize_links(links, target)[:MAX_LINKS_PER_PAGE]
        for link in links:
            if link not in visited:
                visited.add(link)
                queue.append((link, path + [link]))

    return jsonify({"path": [], "message": f"搜尋深度 {MAX_SEARCH_DEPTH} 內未找到"})


def prioritize_links(links, target):
    target_lower = normalize_title(target).lower()

    def score(link):
        link_lower = normalize_title(link).lower()
        if same_title(link, target):
            return 0
        if normalize_title(target) in normalize_title(link) or normalize_title(link) in normalize_title(target):
            return 1
        if target_lower in link_lower or link_lower in target_lower:
            return 2
        return 3

    return sorted(links, key=score)


def normalize_title(title):
    return title.strip().translate(TITLE_VARIANTS)


def same_title(first, second):
    return normalize_title(first) == normalize_title(second)


def find_matching_title(titles, target):
    for title in titles:
        if same_title(title, target):
            return title
    return None

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
