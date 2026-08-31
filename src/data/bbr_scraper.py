"""
Basketball-Reference 荣誉爬虫
=============================
从 Basketball-Reference.com 抓取球员的真实荣誉数据。

用法:
  python -m src.data.bbr_scraper            # 测试爬虫
  python -m src.data.bbr_scraper --build    # 构建完整荣誉数据库
"""

import sys
import io
import os
import json
import time
from typing import Optional, List, Dict, Tuple
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
from bs4 import BeautifulSoup

# ============================================================
# BBR URL 映射 (球员名 → BBR player ID)
# ============================================================
BBR_PLAYER_IDS = {
    "LeBron James": "jamesle01",
    "Stephen Curry": "curryst01",
    "Kevin Durant": "duranke01",
    "Giannis Antetokounmpo": "antetgi01",
    "Nikola Jokic": "jokicni01",
    "Luka Doncic": "doncilu01",
    "Jayson Tatum": "tatumja01",
    "Joel Embiid": "embiijo01",
    "Anthony Davis": "davisan02",
    "Kawhi Leonard": "leonaka01",
    "Damian Lillard": "lillada01",
    "Jalen Brunson": "brunsja01",
    "Shai Gilgeous-Alexander": "gilgesh01",
    "Donovan Mitchell": "mitchdo01",
    "Anthony Edwards": "edwaran01",
    "Ja Morant": "moranja01",
    "Zion Williamson": "willizi01",
    "Trae Young": "youngtr01",
    "Devin Booker": "bookede01",
    "Bam Adebayo": "adebaba01",
    "Tyrese Haliburton": "halibu01",
    "LaMelo Ball": "ballla01",
    "Jaylen Brown": "brownja02",
    "Jrue Holiday": "holidjr01",
    "Derrick White": "whitede01",
    "Pascal Siakam": "siakapa01",
    "Brandon Ingram": "ingrabr01",
    "Evan Mobley": "mobleev01",
    "Darius Garland": "garlada01",
    "Jaren Jackson Jr.": "jacksja02",
    "Domantas Sabonis": "sabondo01",
    "De'Aaron Fox": "foxde01",
    "DeMar DeRozan": "derozde01",
    "Paolo Banchero": "banchpa01",
    "Franz Wagner": "wagnefr01",
    "Scottie Barnes": "barnessc01",
    "Jimmy Butler": "butleji01",
    "James Harden": "hardeja01",
    "Kyrie Irving": "irvinky01",
    "Klay Thompson": "thompkl01",
    "Lauri Markkanen": "markkla01",
    "Alperen Sengun": "sengual01",
    "Tyrese Maxey": "maxeyty01",
    "Paul George": "georgpa01",
    "Chet Holmgren": "holmgch01",
    "Jalen Williams": "willija06",
    "Scoot Henderson": "hendesc01",
    "Brandon Miller": "millebr02",
    "Cade Cunningham": "cunnica01",
    "Jalen Green": "greenja02",
    "Jabari Smith Jr.": "smithja05",
    "Keegan Murray": "murrake02",
    "Victor Wembanyama": "wembavi01",
    "Zach LaVine": "lavinza01",
    "Dejounte Murray": "murrade01",
    "Jarrett Allen": "allenja01",
    "Rudy Gobert": "goberru01",
    "Julius Randle": "randlju01",
    "Aaron Gordon": "gordoaa01",
    "Myles Turner": "turnemy01",
    "Chris Paul": "paulch01",
    "Russell Westbrook": "westbru01",
    "Draymond Green": "greendr01",
    "Karl-Anthony Towns": "townska01",
    "Mikal Bridges": "bridgmi01",
    "OG Anunoby": "anunoog01",
    "Austin Reaves": "reaveau01",
    "Jordan Poole": "poolejo01",
    "Kyle Kuzma": "kuzmaky01",
    "Tyler Herro": "herroty01",
    "Andrew Wiggins": "wiggian01",
    "RJ Barrett": "barrerj01",
    "Cam Thomas": "thomaca02",
    "Desmond Bane": "banede01",
    "Fred VanVleet": "vanvlfr01",
    "Dillon Brooks": "brookdi01",
    "CJ McCollum": "mccolcj01",
    "Nikola Vucevic": "vucevni01",
    "Brook Lopez": "lopezbr01",
    "Khris Middleton": "middlkh01",
    "Bobby Portis": "portibo01",
    "Jonas Valanciunas": "valanjo01",
    "Jerami Grant": "grantje01",
    "Anfernee Simons": "simonan01",
    "Deandre Ayton": "aytonde01",
    "Collin Sexton": "sextoco01",
    "John Collins": "collijo01",
    "Mike Conley": "conlemi01",
    "Steven Adams": "adamsst01",
    "Buddy Hield": "hieldbu01",
    "Norman Powell": "powelno01",
    "D'Angelo Russell": "russeda01",
    "Miles Bridges": "bridgmi02",
    "Nic Claxton": "claxtni01",
    "Rui Hachimura": "hachiru01",
    "Isaiah Hartenstein": "harteis01",
    "Donte DiVincenzo": "divindo01",
    "Jaden McDaniels": "mcdanja02",
    "Malik Monk": "monkma01",
    "Naz Reid": "reidna01",
    "Michael Porter Jr.": "portemi01",
    "Jonathan Kuminga": "kuminjo01",
    "Moses Moody": "moodymo01",
    "Christian Braun": "braunch01",
    "Josh Giddey": "giddejo01",
    "Deni Avdija": "avdijde01",
    "Dereck Lively II": "livelde01",
    "Jaime Jaquez Jr.": "jaqueja01",
    "Brandin Podziemski": "podzibr01",
    "Keyonte George": "georgke01",
    "Stephon Castle": "castlst01",
    "Cooper Flagg": "flagga01",  # 2025 draft
    "Tobias Harris": "harrito02",
    "Cam Johnson": "johnsca02",
    "P.J. Washington": "washipe01",
    "Daniel Gafford": "gaffoda01",
    "Jaden Ivey": "iveyja01",
    "Jalen Suggs": "suggsja01",
    "Jalen Duren": "durenja01",
    "Trey Murphy III": "murphtr01",
    "Herbert Jones": "joneshe01",
    "Devin Vassell": "vassede01",
    "Keldon Johnson": "johnske02",
    "Jeremy Sochan": "sochaje01",
    "Mark Williams": "willima07",
    "Shaedon Sharpe": "sharpsh01",
    "Bennedict Mathurin": "mathube01",
    "Immanuel Quickley": "quickim01",
    "Gradey Dick": "dickgr01",
    "Walker Kessler": "kesslwa01",
    "Alex Caruso": "carusal01",
}

BBR_BASE = "https://www.basketball-reference.com"

# 使用 Session + 完整浏览器模拟头绕过 403
_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
        # 先访问首页拿到 cookie
        try:
            _session.get(BBR_BASE, timeout=10)
        except Exception:
            pass
    return _session


def _get_parser():
    try:
        import lxml  # noqa: F401
        return "lxml"
    except ImportError:
        return "html.parser"


def _bbr_url(player_id: str) -> str:
    """构建 BBR 球员页面 URL"""
    first_letter = player_id[0]
    return f"{BBR_BASE}/players/{first_letter}/{player_id}.html"


def fetch_player_page(player_id: str, retries: int = 2) -> Optional[str]:
    """获取 BBR 球员页面 HTML"""
    url = _bbr_url(player_id)
    session = _get_session()

    for attempt in range(retries + 1):
        try:
            time.sleep(2.0 + attempt * 1.5)  # Rate limit + backoff
            resp = session.get(url, timeout=15,
                               headers={"Referer": BBR_BASE + "/players/"})
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"  [BBR] Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
            else:
                print(f"  [BBR] {player_id}: {e}")
                return None


def parse_honors(html: str) -> List[Dict[str, str]]:
    """
    从 BBR 球员页 HTML 中解析荣誉数据

    BBR 页面结构:
      - <div id="meta"> → <p> 标签含荣誉文本
      - 示例: <p><strong>6x MVP</strong></p>
      - 示例: <p><strong>4x NBA Champ</strong></p>
    """
    soup = BeautifulSoup(html, _get_parser())
    honors = []

    # ---- 1. 从 meta 区提取奖项 ----
    meta = soup.find("div", id="meta")
    if meta:
        for p in meta.find_all("p"):
            text = p.get_text(strip=True).replace("\n", " ")
            if not text or len(text) < 4:
                continue

            # 解析荣誉
            parsed = _parse_award_text(text)
            if parsed:
                honors.append(parsed)

    # ---- 2. 从 season 表格提取全明星 ----
    # BBR 的 All-Star 行加粗: <tr class="full_table"><td class="left"><strong>...</strong>
    # 实际在全明星赛中出场: 统计 id="all_star_game" 的行
    # 简化: 直接搜索 all_star 表格
    allstar_table = soup.find("table", id="all_star_game")
    allstar_count = 0
    allstar_years = []
    if allstar_table:
        for row in allstar_table.find_all("tr"):
            year_cell = row.find("th", {"data-stat": "year_id"})
            if year_cell:
                year_text = year_cell.get_text(strip=True)
                if year_text and len(year_text) == 7:  # "2023-24"
                    allstar_years.append(year_text[:4])
        allstar_count = len(allstar_years)

    # 如果 meta 中没有 All Star 或数量不匹配，用实际计数覆盖
    if allstar_count > 0:
        # 检查是否已有全明星条目
        as_exists = any("全明星" in h.get("category", "") for h in honors)
        if not as_exists:
            years_range = _format_year_range(allstar_years)
            honors.append({
                "icon": "⭐",
                "category": "全明星",
                "detail": f"{allstar_count}× ({years_range})" if allstar_years else f"{allstar_count}× NBA全明星",
            })
        else:
            # 用实际数据更新
            for h in honors:
                if "全明星" in h.get("category", ""):
                    years_range = _format_year_range(allstar_years)
                    h["detail"] = f"{allstar_count}× ({years_range})"

    # ---- 3. 从 Leaders 表格提取排名 ----
    _extract_leaderboard(soup, honors)

    return _deduplicate_honors(honors)


def _parse_award_text(text: str) -> Optional[Dict[str, str]]:
    """解析 BBR 奖项文本为结构化荣誉条目"""

    text_lower = text.lower()

    # 总冠军
    if "nba champ" in text_lower:
        num = _extract_number(text)
        return {"icon": "🏆", "category": "总冠军", "detail": f"{num}× NBA总冠军"}
    # MVP
    if text_lower.startswith(tuple(f"{i}x mvp" for i in range(1, 10))) or \
       ("mvp" in text_lower and "all-star" not in text_lower and "finals" not in text_lower):
        num = _extract_number(text)
        if "nba mvp" in text_lower or text_lower.strip().endswith("mvp"):
            return {"icon": "🥇", "category": "MVP", "detail": f"{num}× 常规赛MVP"}
    # FMVP
    if "finals mvp" in text_lower or "bill russell" in text_lower:
        num = _extract_number(text)
        return {"icon": "🌟", "category": "FMVP", "detail": f"{num}× 总决赛MVP"}
    # 全明星 (meta 中的可能不准，后面会校正)
    if "all star" in text_lower or "all-star" in text_lower:
        num = _extract_number(text)
        if "mvp" not in text_lower:
            return {"icon": "⭐", "category": "全明星", "detail": f"{num}× NBA全明星"}
    # 最佳阵容
    if "all-nba" in text_lower:
        num = _extract_number(text)
        return {"icon": "📋", "category": "最佳阵容", "detail": f"{num}× 最佳阵容"}
    # 最佳防守
    if "all-defensive" in text_lower:
        num = _extract_number(text)
        return {"icon": "🛡️", "category": "最佳防守", "detail": f"{num}× 最佳防守阵容"}
    # DPOY
    if "defensive player of the year" in text_lower or "dpoy" in text_lower:
        num = _extract_number(text)
        return {"icon": "🛡️", "category": "DPOY", "detail": f"{num}× 最佳防守球员"}
    # ROY
    if "rookie of the year" in text_lower:
        num = _extract_number(text)
        return {"icon": "🌟", "category": "ROY", "detail": f"{num}× 最佳新秀"}
    # 得分王
    if "scoring champ" in text_lower or "scoring leader" in text_lower:
        num = _extract_number(text)
        return {"icon": "👑", "category": "得分王", "detail": f"{num}× 得分王"}
    # 助攻王
    if "assists leader" in text_lower:
        num = _extract_number(text)
        return {"icon": "🤝", "category": "助攻王", "detail": f"{num}× 助攻王"}
    # 篮板王
    if "rebounds leader" in text_lower:
        num = _extract_number(text)
        return {"icon": "🏀", "category": "篮板王", "detail": f"{num}× 篮板王"}
    # 盖帽王
    if "blocks leader" in text_lower:
        num = _extract_number(text)
        return {"icon": "🛡️", "category": "盖帽王", "detail": f"{num}× 盖帽王"}
    # 抢断王
    if "steals leader" in text_lower:
        num = _extract_number(text)
        return {"icon": "🤚", "category": "抢断王", "detail": f"{num}× 抢断王"}
    # 6MOY
    if "sixth man" in text_lower:
        num = _extract_number(text)
        return {"icon": "📈", "category": "6MOY", "detail": f"{num}× 最佳第六人"}
    # MIP
    if "most improved" in text_lower:
        num = _extract_number(text)
        return {"icon": "📈", "category": "MIP", "detail": f"{num}× 进步最快球员"}
    # 奥运
    if "olympic" in text_lower and ("gold" in text_lower or "medal" in text_lower):
        return {"icon": "🏅", "category": "奥运", "detail": text.strip()}
    # Hall of Fame
    if "hall of fame" in text_lower:
        return {"icon": "🏛️", "category": "名人堂", "detail": "Naismith篮球名人堂"}

    return None


def _extract_number(text: str) -> int:
    """从文本中提取数字 ('6x MVP' → 6)"""
    import re
    m = re.search(r'(\d+)\s*x', text)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*×', text)
    if m:
        return int(m.group(1))
    return 1


def _format_year_range(years: List[str]) -> str:
    """格式化年份列表为范围字符串 ['2020','2021','2023'] → '2020-2021, 2023'"""
    if not years:
        return ""
    years_int = sorted([int(y) for y in years])
    if len(years_int) <= 3:
        return ", ".join(str(y) for y in years_int)
    # 找连续区间
    ranges = []
    start = years_int[0]
    end = years_int[0]
    for y in years_int[1:]:
        if y == end + 1:
            end = y
        else:
            ranges.append((start, end))
            start = end = y
    ranges.append((start, end))
    parts = []
    for s, e in ranges:
        if s == e:
            parts.append(str(s))
        else:
            parts.append(f"{s}-{e}")
    return ", ".join(parts)


def _extract_leaderboard(soup: BeautifulSoup, honors: List[Dict]):
    """从 Leaderboard 区域提取奖项排名"""
    leaderboard = soup.find("div", id="leaderboard")
    if not leaderboard:
        return
    # 可以进一步解析 MVP shares, award voting 等
    # 此处保留扩展点
    pass


def _deduplicate_honors(honors: List[Dict]) -> List[Dict]:
    """去重并按重要性排序"""
    seen = set()
    result = []
    priority = {
        "总冠军": 0, "MVP": 1, "FMVP": 2, "DPOY": 3,
        "全明星": 4, "最佳阵容": 5, "最佳防守": 6,
        "ROY": 7, "得分王": 8, "助攻王": 9, "篮板王": 10,
        "盖帽王": 11, "抢断王": 12, "MIP": 13, "6MOY": 14,
        "奥运": 15, "名人堂": 16,
    }
    for h in honors:
        key = h["category"]
        if key not in seen:
            seen.add(key)
            result.append(h)
    result.sort(key=lambda h: priority.get(h["category"], 99))
    return result


def get_player_honors_from_bbr(player_name: str) -> List[Dict[str, str]]:
    """从 BBR 获取球员荣誉（主入口）"""
    player_id = BBR_PLAYER_IDS.get(player_name)
    if not player_id:
        # 检查大小写不敏感
        for db_name, pid in BBR_PLAYER_IDS.items():
            if db_name.lower() == player_name.lower():
                player_id = pid
                break
    if not player_id:
        return []

    html = fetch_player_page(player_id)
    if not html:
        return []

    return parse_honors(html)


# ============================================================
# 批量构建 + 缓存
# ============================================================
def build_honors_cache(output_path: str = "data/bbr_honors_cache.json"):
    """抓取所有已映射球员的荣誉并缓存到 JSON"""
    results = {}
    total = len(BBR_PLAYER_IDS)
    for i, (name, pid) in enumerate(BBR_PLAYER_IDS.items()):
        print(f"[{i+1}/{total}] {name} ({pid}) ...", end=" ", flush=True)
        honors = get_player_honors_from_bbr(name)
        if honors:
            results[name] = honors
            print(f"{len(honors)} honors")
        else:
            print("FAILED")

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(results)} players to {output_path}")


def load_honors_cache(cache_path: str = "data/bbr_honors_cache.json") -> Dict:
    """加载缓存的荣誉数据"""
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="构建完整缓存")
    parser.add_argument("--player", type=str, default="LeBron James", help="查询单个球员")
    parser.add_argument("--test", type=int, default=2, help="测试前N个球员")
    args = parser.parse_args()

    if args.build:
        build_honors_cache()
    else:
        print(f"Testing first {args.test} players...\n")
        names = list(BBR_PLAYER_IDS.keys())[:args.test]
        for name in names:
            print(f"--- {name} ---")
            honors = get_player_honors_from_bbr(name)
            for h in honors:
                print(f"  {h['icon']} {h['category']}: {h['detail']}")
            print()
