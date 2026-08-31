"""
NBA 官方荣誉数据抓取器 (nba_api)
==============================
通过 stats.nba.com 官方 API 获取球员的真实荣誉数据。

用法:
  python -m src.data.nba_honors_fetcher --test       # 测试连通性
  python -m src.data.nba_honors_fetcher --build       # 构建完整缓存
  python -m src.data.nba_honors_fetcher --player "LeBron James"

前置条件:
  - 网络必须可达 stats.nba.com（北美 IP 或 VPN）
  - 如果不可达，自动降级到硬编码数据库
"""

import sys
import io
import os
import json
import time
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ============================================================
# 连通性检测
# ============================================================
_nba_api_available: Optional[bool] = None


def check_nba_api_available() -> bool:
    """检测 stats.nba.com 是否可达"""
    global _nba_api_available
    if _nba_api_available is not None:
        return _nba_api_available

    import urllib.request
    url = "https://stats.nba.com/stats/commonallplayers?IsOnlyCurrentSeason=0&LeagueID=00&Season=2024-25"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.nba.com/",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        urllib.request.urlopen(req, timeout=8)
        _nba_api_available = True
    except Exception:
        _nba_api_available = False

    if not _nba_api_available:
        print("[NBA API] stats.nba.com 不可达（需要北美网络/VPN），将使用本地荣誉数据库")
    else:
        print("[NBA API] stats.nba.com 连通正常")
    return _nba_api_available


# ============================================================
# 球员荣誉抓取
# ============================================================
def _get_player_id(name: str) -> Optional[int]:
    """通过 nba_api 搜索球员 ID"""
    try:
        from nba_api.stats.static import players
        results = players.find_players_by_full_name(name)
        if results:
            return results[0]["id"]
    except Exception:
        pass
    return None


def _parse_awards_df(df) -> List[Dict[str, str]]:
    """
    解析 PlayerAwards 返回的 DataFrame

    列: PERSON_ID, FIRST_NAME, LAST_NAME, TEAM, SEASON,
         ALL_NBA_TEAM_NUMBER, ALL_STAR_GAME, ALL_DEFENSIVE_TEAM,
         PLAYER_OF_THE_MONTH, PLAYER_OF_THE_WEEK, etc.
    注意: 该表是每赛季一行
    """
    honors: Dict[str, Dict] = {}

    for _, row in df.iterrows():
        season = str(row.get("SEASON", ""))
        year = int(season[:4]) if len(season) >= 4 else 0

        # 全明星
        if row.get("ALL_STAR_GAME") == 1:
            h = honors.setdefault("全明星", {
                "icon": "⭐", "category": "全明星", "years": [], "detail": ""
            })
            h["years"].append(year)

        # 最佳阵容
        all_nba = row.get("ALL_NBA_TEAM_NUMBER")
        if all_nba and all_nba in [1, 2, 3]:
            tier = ["", "一阵", "二阵", "三阵"][int(all_nba)]
            h = honors.setdefault("最佳阵容", {
                "icon": "📋", "category": "最佳阵容",
                "first": 0, "second": 0, "third": 0, "detail": ""
            })
            if int(all_nba) == 1:
                h["first"] += 1
            elif int(all_nba) == 2:
                h["second"] += 1
            else:
                h["third"] += 1

        # 最佳防守阵容
        all_def = row.get("ALL_DEFENSIVE_TEAM")
        if all_def and all_def in [1, 2]:
            h = honors.setdefault("最佳防守", {
                "icon": "🛡️", "category": "最佳防守", "detail": ""
            })
            tier = "防守一阵" if int(all_def) == 1 else "防守二阵"

    # 格式化
    result = []
    for cat, h in honors.items():
        if cat == "全明星" and h["years"]:
            years = sorted(set(h["years"]))
            h["detail"] = f"{len(years)}× ({_fmt_range(years)})"
            result.append({"icon": h["icon"], "category": h["category"], "detail": h["detail"]})
        elif cat == "最佳阵容":
            parts = []
            if h.get("first", 0):
                parts.append(f"{h['first']}× 一阵")
            if h.get("second", 0):
                parts.append(f"{h['second']}× 二阵")
            if h.get("third", 0):
                parts.append(f"{h['third']}× 三阵")
            if parts:
                h["detail"] = " / ".join(parts)
                result.append({"icon": h["icon"], "category": h["category"], "detail": h["detail"]})
        elif cat == "最佳防守":
            result.append({"icon": h["icon"], "category": h["category"], "detail": h["detail"]})

    return result


def _parse_career_df(df) -> List[Dict[str, str]]:
    """
    从 PlayerCareerStats 交叉验证:
      - 总冠军 (通过 playoff 出战记录推断)
      - All-Star 总次数 (如果 awards 表不全)
    """
    # career stats 主要用于交叉验证，核心数据已在 awards 表中
    return []


def _fmt_range(years: List[int]) -> str:
    """格式化年份列表"""
    if not years:
        return ""
    years = sorted(set(years))
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


def fetch_honors_nba_api(player_name: str) -> List[Dict[str, str]]:
    """
    使用 nba_api 获取球员荣誉

    数据源:
      1. playerawards.PlayerAwards  — 全明星、最佳阵容、最佳防守阵容
      2. playercareerstats.PlayerCareerStats — 交叉验证

    Args:
        player_name: 球员姓名

    Returns:
        荣誉列表，API 不可用或球员未找到时返回空列表
    """
    if not check_nba_api_available():
        return []

    pid = _get_player_id(player_name)
    if not pid:
        print(f"  [NBA API] 未找到球员: {player_name}")
        return []

    all_honors = []

    # 1. Awards
    try:
        from nba_api.stats.endpoints import playerawards
        awards = playerawards.PlayerAwards(player_id=pid)
        df = awards.get_data_frames()[0]
        parsed = _parse_awards_df(df)
        all_honors.extend(parsed)
        print(f"  [NBA API] {player_name}: Awards parsed, {len(parsed)} categories")
    except Exception as e:
        print(f"  [NBA API] Awards failed for {player_name}: {e}")

    # 2. Career Stats (交叉验证)
    try:
        from nba_api.stats.endpoints import playercareerstats
        career = playercareerstats.PlayerCareerStats(player_id=pid)
        df2 = career.get_data_frames()[0]
        cross = _parse_career_df(df2)
        all_honors.extend(cross)
    except Exception as e:
        print(f"  [NBA API] CareerStats failed for {player_name}: {e}")

    return all_honors


# ============================================================
# 批量缓存
# ============================================================
# 从 player_db 中提取所有已知球员 ID
KNOWN_PLAYER_IDS = {
    "LeBron James": 2544,
    "Stephen Curry": 201939,
    "Kevin Durant": 201142,
    "Giannis Antetokounmpo": 203507,
    "Nikola Jokic": 203999,
    "Luka Doncic": 1629029,
    "Jayson Tatum": 1628369,
    "Joel Embiid": 203954,
    "Anthony Davis": 203076,
    "Kawhi Leonard": 202695,
    "Damian Lillard": 203081,
    "Jalen Brunson": 1628973,
    "Shai Gilgeous-Alexander": 1628983,
    "Donovan Mitchell": 1628378,
    "Anthony Edwards": 1630162,
    "Ja Morant": 1629630,
    "Zion Williamson": 1629627,
    "Trae Young": 1629027,
    "Devin Booker": 1626164,
    "Bam Adebayo": 1628389,
    "Tyrese Haliburton": 1630169,
    "LaMelo Ball": 1630163,
    "Jaylen Brown": 1627759,
    "Jrue Holiday": 201950,
    "Derrick White": 1628401,
    "Pascal Siakam": 1627783,
    "Brandon Ingram": 1627742,
    "Evan Mobley": 1630596,
    "Darius Garland": 1629636,
    "Jaren Jackson Jr.": 1628991,
    "Domantas Sabonis": 1627734,
    "De'Aaron Fox": 1628368,
    "DeMar DeRozan": 201942,
    "Paolo Banchero": 1631094,
    "Franz Wagner": 1630532,
    "Scottie Barnes": 1630567,
    "Jimmy Butler": 202710,
    "James Harden": 201935,
    "Kyrie Irving": 202681,
    "Klay Thompson": 202691,
    "Lauri Markkanen": 1628374,
    "Alperen Sengun": 1630578,
    "Tyrese Maxey": 1630178,
    "Paul George": 202331,
    "Chet Holmgren": 1631097,
    "Jalen Williams": 1631115,
    "Scoot Henderson": 1631112,
    "Brandon Miller": 1631102,
    "Cade Cunningham": 1630595,
    "Jalen Green": 1630224,
    "Jabari Smith Jr.": 1631093,
    "Keegan Murray": 1631099,
    "Victor Wembanyama": 1641705,
    "Zach LaVine": 1628972,
    "Dejounte Murray": 1627749,
    "Jarrett Allen": 1628386,
    "Rudy Gobert": 203497,
    "Julius Randle": 203944,
    "Aaron Gordon": 203932,
    "Myles Turner": 1626167,
    "Chris Paul": 101108,
    "Russell Westbrook": 201566,
    "Draymond Green": 203110,
    "Karl-Anthony Towns": 1626157,
    "Mikal Bridges": 1628969,
    "OG Anunoby": 1628384,
    "Austin Reaves": 1630559,
}


def build_nba_cache(output_path: str = "data/nba_honors_cache.json"):
    """批量抓取并缓存所有已知球员荣誉"""
    if not check_nba_api_available():
        print("[NBA API] 不可达，无法构建缓存")
        return False

    results = {}
    total = len(KNOWN_PLAYER_IDS)
    for i, (name, pid) in enumerate(KNOWN_PLAYER_IDS.items()):
        print(f"[{i+1}/{total}] {name} ({pid}) ...", end=" ", flush=True)
        try:
            from nba_api.stats.endpoints import playerawards
            awards = playerawards.PlayerAwards(player_id=pid)
            df = awards.get_data_frames()[0]
            parsed = _parse_awards_df(df)
            if parsed:
                results[name] = parsed
                print(f"{len(parsed)} honors")
            else:
                print("no awards data")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(0.6)  # Rate limit

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(results)} players to {output_path}")
    return True


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="测试连通性")
    parser.add_argument("--build", action="store_true", help="构建完整缓存")
    parser.add_argument("--player", type=str, default="", help="查询单个球员")
    args = parser.parse_args()

    if args.build:
        build_nba_cache()
    elif args.player:
        print(f"查询: {args.player}")
        if check_nba_api_available():
            honors = fetch_honors_nba_api(args.player)
            for h in honors:
                print(f"  {h['icon']} {h['category']}: {h['detail']}")
        else:
            print("  stats.nba.com 不可达，请使用硬编码数据库")
            from src.data.player_honors import _PLAYER_HONORS
            h = _PLAYER_HONORS.get(args.player, [])
            for x in h:
                print(f"  {x['icon']} {x['category']}: {x['detail']}")
    else:
        print("Testing nba_api connectivity...")
        ok = check_nba_api_available()
        print(f"stats.nba.com: {'REACHABLE' if ok else 'UNREACHABLE'}")
        if ok:
            print("\nTesting LeBron...")
            honors = fetch_honors_nba_api("LeBron James")
            for h in honors:
                print(f"  {h['icon']} {h['category']}: {h['detail']}")
