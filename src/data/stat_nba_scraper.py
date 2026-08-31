"""
stat-nba.com 荣誉爬虫
=====================
从 stat-nba.com 抓取球员的真实荣誉数据。

每个球员页有 <div id="award"> 包含完整荣誉文本，格式:
  "11-12赛季总冠军(迈阿密热火)12-13赛季总冠军(...)08-09赛季MVP..."

用法:
  python -m src.data.stat_nba_scraper --test       # 测试 LeBron
  python -m src.data.stat_nba_scraper --build       # 批量构建缓存
  python -m src.data.stat_nba_scraper --player 1862 # 单球员
"""

import sys
import io
import os
import json
import re
import time
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
from bs4 import BeautifulSoup

STAT_NBA_BASE = "http://www.stat-nba.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ============================================================
# 荣誉名称 → {icon, category} 映射
# ============================================================
_HONOR_MAP: Dict[str, Tuple[str, str, int]] = {
    "总冠军": ("🏆", "总冠军", 0),
    "总决赛最有价值球员": ("🌟", "FMVP", 1),
    "FMVP": ("🌟", "FMVP", 1),
    "最有价值球员": ("🥇", "MVP", 2),
    "MVP": ("🥇", "MVP", 2),
    "最佳防守球员": ("🛡️", "DPOY", 3),
    "DPOY": ("🛡️", "DPOY", 3),
    "全明星": ("⭐", "全明星", 4),
    "最佳阵容一阵": ("📋", "最佳阵容一阵", 5),
    "最佳阵容二阵": ("📋", "最佳阵容二阵", 5),
    "最佳阵容三阵": ("📋", "最佳阵容三阵", 5),
    "最佳阵容第1阵": ("📋", "最佳阵容一阵", 5),
    "最佳阵容第2阵": ("📋", "最佳阵容二阵", 5),
    "最佳阵容第3阵": ("📋", "最佳阵容三阵", 5),
    "防守一阵": ("🛡️", "防守一阵", 6),
    "防守二阵": ("🛡️", "防守二阵", 6),
    "最佳防守阵容一阵": ("🛡️", "防守一阵", 6),
    "最佳防守阵容二阵": ("🛡️", "防守二阵", 6),
    "最佳防守阵容第1阵": ("🛡️", "防守一阵", 6),
    "最佳防守阵容第2阵": ("🛡️", "防守二阵", 6),
    "最佳新秀": ("🌟", "ROY", 7),
    "得分王": ("👑", "得分王", 8),
    "助攻王": ("🤝", "助攻王", 9),
    "篮板王": ("🏀", "篮板王", 10),
    "抢断王": ("🤚", "抢断王", 11),
    "盖帽王": ("🛡️", "盖帽王", 12),
    "进步最快球员": ("📈", "MIP", 13),
    "MIP": ("📈", "MIP", 13),
    "最佳第六人": ("📈", "6MOY", 14),
    "全明星MVP": ("⭐", "全明星MVP", 15),
    "新秀一阵": ("📋", "新秀一阵", 16),
    "新秀二阵": ("📋", "新秀二阵", 16),
    "最佳新秀阵容一阵": ("📋", "新秀一阵", 16),
    "最佳新秀阵容二阵": ("📋", "新秀二阵", 16),
    "最佳新秀阵容第1阵": ("📋", "新秀一阵", 16),
    "最佳新秀阵容第2阵": ("📋", "新秀二阵", 16),
    "名人堂": ("🏛️", "名人堂", 17),
}

# stat-nba player_id → 球员名 映射 (逐步积累)
_PLAYER_ID_MAP: Dict[int, str] = {}


def _fetch_player_page(player_id: int) -> Optional[str]:
    """获取球员页面 HTML"""
    url = f"{STAT_NBA_BASE}/player/{player_id}.html"
    try:
        time.sleep(0.8)
        resp = requests.get(url, headers=HEADERS, timeout=12)
        resp.encoding = "utf-8"
        if resp.status_code == 200:
            return resp.text
        print(f"  [{player_id}] HTTP {resp.status_code}")
        return None
    except Exception as e:
        print(f"  [{player_id}] Error: {e}")
        return None


def _parse_player_name(html: str) -> str:
    """从 HTML 中解析球员英文名"""
    soup = BeautifulSoup(html, "html.parser")
    name_div = soup.find("div", class_="name")
    if name_div:
        text = name_div.get_text(strip=True)
        # "勒布朗-詹姆斯/LeBron James百度百科..."
        m = re.search(r"/([a-zA-Z\s\-.']+)\s*(?:百度|wiki)", text)
        if m:
            return m.group(1).strip()
    return ""


def _parse_award_text(award_div_text: str) -> List[Dict[str, str]]:
    """
    解析 div#player_award 中的荣誉文本

    格式: "个人主要荣誉11-12赛季总冠军(迈阿密热火)12-13赛季总冠军(...)
           08-09赛季MVP(骑士)04-05赛季全明星首发..."

    解析策略:
      用正则提取每一个 {赛季标记}{荣誉名称}({细节})
      赛季标记: XX-XX赛季 或 XXXX年XX月
    """
    if not award_div_text:
        return []

    text = re.sub(r"个人主要荣誉", "", award_div_text)

    # 正则提取: (赛季标记)(荣誉内容直到下一个赛季标记或末尾)
    # 赛季标记: \d{2}-\d{2}赛季 | \d{4}年\d{2}月
    pattern = r'(\d{2}-\d{2}赛季|\d{4}年\d{2}月)(.*?)(?=\d{2}-\d{2}赛季|\d{4}年\d{2}月|$)'
    matches = re.findall(pattern, text)

    # 聚合: honor_name → list of seasons
    counts: Dict[str, List[str]] = {}

    for season_marker, honor_block in matches:
        season = season_marker.replace("赛季", "").replace("年", "-")
        honor_block = honor_block.strip()

        # 跳过只有链接的（如 数据>>）
        if not honor_block or honor_block in ("数据>>",):
            continue

        # 去掉结尾的 数据>> 链接
        honor_block = re.sub(r"数据>>$", "", honor_block).strip()
        if not honor_block:
            continue

        # 提取荣誉名称（去掉括号内的英文缩写和细节）
        # 如：总冠军(迈阿密热火) → 总冠军
        # 如：最有价值球员(MVP) → 最有价值球员
        honor_name = re.sub(r"\([^)]*\)", "", honor_block).strip()

        if not honor_name:
            continue

        # 特殊处理：全明星——合并 "全明星首发" / "全明星替补" / "全明星" → "全明星"
        if honor_name.startswith("全明星"):
            honor_name = "全明星"

        counts.setdefault(honor_name, []).append(season)

    return _counts_to_honors(counts)


def _counts_to_honors(honor_counts: Dict[str, List[str]]) -> List[Dict[str, str]]:
    """将荣誉计数转换为结构化列表"""
    # 先聚合
    categories: Dict[str, Dict] = {}  # category_key → {icon, category, items}

    for honor_name, seasons in honor_counts.items():
        if honor_name not in _HONOR_MAP:
            continue
        icon, cat, priority = _HONOR_MAP[honor_name]
        key = cat  # 同一类别的合并

        if key not in categories:
            categories[key] = {"icon": icon, "category": cat,
                               "priority": priority, "seasons": [], "count": 0}
        categories[key]["seasons"].extend(seasons)
        categories[key]["count"] += len(seasons)

    # 格式化
    result = []
    for cat_data in sorted(categories.values(), key=lambda x: x["priority"]):
        count = cat_data["count"]
        seasons = sorted(set(cat_data["seasons"]))
        if not seasons:
            continue

        # 格式化 detail
        if cat_data["category"] in ("全明星",):
            year_range = _seasons_to_years(seasons)
            detail = f"{count}× ({year_range})"
        elif cat_data["category"] in ("MVP", "FMVP", "DPOY", "ROY", "得分王",
                                        "助攻王", "篮板王", "抢断王", "盖帽王",
                                        "MIP", "6MOY", "全明星MVP", "名人堂"):
            years = _seasons_to_years(seasons)
            detail = f"{count}× ({years})"
        elif "一阵" in cat_data["category"] or "二阵" in cat_data["category"] or "三阵" in cat_data["category"]:
            # 这类已按级别分开
            years = _seasons_to_years(seasons)
            detail = f"{count}× ({years})"
        else:
            years = _seasons_to_years(seasons)
            detail = f"{count}× ({years})"

        result.append({
            "icon": cat_data["icon"],
            "category": cat_data["category"],
            "detail": detail,
        })

    # 合并最佳阵容
    result = _merge_all_nba(result)

    return result


def _merge_all_nba(honors: List[Dict]) -> List[Dict]:
    """合并「最佳阵容一阵/二阵/三阵」为一个条目"""
    first = second = third = None
    others = []
    for h in honors:
        if h["category"] == "最佳阵容一阵":
            first = h
        elif h["category"] == "最佳阵容二阵":
            second = h
        elif h["category"] == "最佳阵容三阵":
            third = h
        else:
            others.append(h)

    parts = []
    for label, item in [("一阵", first), ("二阵", second), ("三阵", third)]:
        if item:
            cnt = int(item["detail"].split("×")[0]) if "×" in item["detail"] else 0
            if cnt > 0:
                parts.append(f"{cnt}× {label}")

    if parts:
        others.insert(4, {"icon": "📋", "category": "最佳阵容",
                          "detail": " / ".join(parts)})
    return others


def _seasons_to_years(seasons: List[str]) -> str:
    """把赛季列表格式化为年份范围, '19-20','20-21','22-23' → '2020-2021, 2023'"""
    years = []
    for s in seasons:
        m = re.match(r"(\d{2})-(\d{2})", s)
        if m:
            y1 = 2000 + int(m.group(1))
            y2 = 2000 + int(m.group(2))
            years.append(y2)  # 用结束年（颁奖年）
        else:
            m2 = re.match(r"(\d{4})-(\d{2})", s)
            if m2:
                years.append(int(m2.group(1)))
    years = sorted(set(years))
    if not years:
        return ", ".join(seasons)
    if len(years) <= 3:
        return ", ".join(str(y) for y in years)

    ranges = []
    s = e = years[0]
    for y in years[1:]:
        if y == e + 1:
            e = y
        else:
            ranges.append((s, e))
            s = e = y
    ranges.append((s, e))
    parts = [str(s) if s == e else f"{s}-{e}" for s, e in ranges]
    return ", ".join(parts)


def fetch_player_honors(player_id: int) -> Tuple[str, List[Dict[str, str]]]:
    """
    抓取单个球员的荣誉

    Returns:
        (player_name, honors_list)
    """
    html = _fetch_player_page(player_id)
    if not html:
        return ("", [])

    name = _parse_player_name(html)
    soup = BeautifulSoup(html, "html.parser")
    award_div = soup.find("div", id="player_award") or soup.find("div", id="award")
    if award_div:
        award_text = award_div.get_text(strip=True)
        honors = _parse_award_text(award_text)
        return (name, honors)

    # 如果 div#award 不存在，尝试从 award 页面抓取
    return (name, _scrape_award_pages(player_id))


def _scrape_award_pages(player_id: int) -> List[Dict[str, str]]:
    """备用方案: 从各个 /award/itemX.html?player_id= 页面聚合"""
    # 限于关键荣誉页面
    award_items = {
        15: "总冠军", 5: "总决赛最有价值球员", 0: "最有价值球员",
        12: "全明星", 8: "最佳阵容",
        2: "最佳防守球员", 10: "最佳防守阵容",
        1: "最佳新秀", 3: "最佳第六人", 4: "进步最快球员",
        14: "各项数据王",
    }
    all_honors: Dict[str, List[str]] = {}

    for item_id, honor_name in award_items.items():
        try:
            time.sleep(0.5)
            url = f"{STAT_NBA_BASE}/award/item{item_id}.html?player_id={player_id}"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.encoding = "utf-8"
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            # 找表格行中的赛季信息
            for row in soup.find_all("tr"):
                cells = row.find_all(["th", "td"])
                if len(cells) >= 1:
                    season_text = cells[0].get_text(strip=True)
                    if re.match(r"\d{2}-\d{2}", season_text):
                        if honor_name not in all_honors:
                            all_honors[honor_name] = []
                        all_honors[honor_name].append(season_text)
        except Exception as e:
            print(f"    Award item{item_id} failed: {e}")

    return _counts_to_honors(all_honors)


# ============================================================
# 批量缓存
# ============================================================
def find_player_id(name: str) -> Optional[int]:
    """通过扫描 stat-nba 找到球员 ID（搜索功能有限，需要手动发现）"""
    global _PLAYER_ID_MAP
    # 检查缓存
    for pid, pname in _PLAYER_ID_MAP.items():
        if pname.lower() == name.lower():
            return pid
    return None


def build_cache(
    player_ids: List[int],
    output_path: str = "data/stat_nba_honors_cache.json",
) -> Dict[str, List[Dict]]:
    """批量抓取并缓存"""
    results = {}
    total = len(player_ids)
    for i, pid in enumerate(player_ids):
        name, honors = fetch_player_honors(pid)
        print(f"[{i+1}/{total}] {pid} {name}: ", end="")
        if honors:
            results[name] = honors
            _PLAYER_ID_MAP[pid] = name
            print(f"{len(honors)} honors")
        else:
            print("NO DATA")

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(results)} players to {output_path}")
    return results


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="测试 LeBron")
    parser.add_argument("--build", action="store_true", help="批量构建缓存")
    parser.add_argument("--player", type=int, default=0, help="指定球员ID")
    parser.add_argument("--scan", type=int, nargs=2, metavar=("FROM", "TO"),
                        help="扫描ID范围发现球员")
    args = parser.parse_args()

    if args.scan:
        start, end = args.scan
        print(f"Scanning IDs {start}-{end}...")
        found = {}
        for pid in range(start, end + 1):
            html = _fetch_player_page(pid)
            if html:
                name = _parse_player_name(html)
                if name:
                    found[pid] = name
                    print(f"  {pid}: {name}")
        # Save discovery
        with open("data/stat_nba_player_ids.json", "w", encoding="utf-8") as f:
            json.dump(found, f, ensure_ascii=False, indent=2)
        print(f"Found {len(found)} players")

    elif args.build:
        # 需要先有 player_id 列表
        id_file = "data/stat_nba_player_ids.json"
        if os.path.exists(id_file):
            with open(id_file, "r", encoding="utf-8") as f:
                pid_map = json.load(f)
            ids = [int(k) for k in pid_map.keys()]
            build_cache(ids)
        else:
            print("请先运行 --scan 发现球员ID: python -m src.data.stat_nba_scraper --scan 1 5000")

    elif args.player:
        name, honors = fetch_player_honors(args.player)
        print(f"Player: {name}")
        for h in honors:
            print(f"  {h['icon']} {h['category']}: {h['detail']}")

    else:
        # 默认：测试 LeBron James
        print("=== Testing LeBron James (ID 1862) ===\n")
        name, honors = fetch_player_honors(1862)
        print(f"Player: {name}")
        print(f"Honors: {len(honors)} categories\n")
        for h in honors:
            print(f"  {h['icon']} {h['category']}: {h['detail']}")
