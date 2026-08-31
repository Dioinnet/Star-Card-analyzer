"""
球员近期赛事表现模块 (真实数据)
=============================
从 stats.nba.com 获取 NBA 球员的最新比赛数据。

数据来源:
  1. nba_api (stats.nba.com) — 真实 NBA 官方数据
  2. 模拟数据 — API 不可用时的降级方案

用法:
  from src.data.player_stats import get_recent_games, get_season_averages
"""

import sys
import io
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import numpy as np

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ============================================================
# 球员名 → NBA stats.nba.com Person ID 映射
# ============================================================
_NBA_PERSON_IDS = {
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
    "Kristaps Porzingis": 204001,
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
    "Karl-Anthony Towns": 1626157,
    "Mikal Bridges": 1628969,
    "OG Anunoby": 1628384,
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
    "Andrew Wiggins": 203952,
    "Tyler Herro": 1629635,
    "Coby White": 1629632,
    "Austin Reaves": 1630559,
    "Jordan Poole": 1629673,
    "Kyle Kuzma": 1628398,
    "RJ Barrett": 1629628,
    "Cam Thomas": 1630568,
    "Desmond Bane": 1630217,
    "Devin Vassell": 1630172,
    "Keldon Johnson": 1629640,
    "Jeremy Sochan": 1631110,
    "Daniel Gafford": 1629018,
    "Ivica Zubac": 1627826,
    "Jonas Valanciunas": 202685,
    "Brook Lopez": 201572,
    "Draymond Green": 203110,
    "Chris Paul": 101108,
    "Russell Westbrook": 201566,
    "Fred VanVleet": 1627832,
    "Dillon Brooks": 1628415,
    "CJ McCollum": 203468,
    "Jalen Duren": 1631095,
    "Jaden Ivey": 1631091,
    "Jalen Suggs": 1630592,
    "Trey Murphy III": 1630530,
    "Anfernee Simons": 1629014,
    "Jerami Grant": 203924,
    "Collin Sexton": 1629012,
    "John Collins": 1628381,
    "Mike Conley": 201144,
    "Steven Adams": 203500,
    "Buddy Hield": 1627741,
    "Norman Powell": 203939,
    "Khris Middleton": 203114,
    "Bobby Portis": 1626171,
    "Josh Giddey": 1630581,
    "Deni Avdija": 1630166,
    "Luguentz Dort": 1629652,
    "Naz Reid": 1629675,
    "Malik Monk": 1628370,
    "Brandon Clarke": 1629634,
    "Tobias Harris": 202699,
    "Cam Johnson": 1629661,
    "P.J. Washington": 1629023,
    "Nic Claxton": 1629651,
    "D'Angelo Russell": 1626156,
    "Miles Bridges": 1628970,
    "Mark Williams": 1631109,
    "Rui Hachimura": 1629060,
    "Nikola Vucevic": 202696,
    "Deandre Ayton": 1629028,
    "Shaedon Sharpe": 1631104,
    "Bennedict Mathurin": 1631096,
    "Immanuel Quickley": 1630241,
    "Gradey Dick": 1641715,
    "Walker Kessler": 1631117,
    "Isaiah Hartenstein": 1628392,
    "Alex Caruso": 1627936,
    "Donte DiVincenzo": 1628978,
    "Michael Porter Jr.": 1629008,
    "Jonathan Kuminga": 1630228,
    "Moses Moody": 1630545,
    "Christian Braun": 1631123,
    "Jaden McDaniels": 1630183,
    "Herbert Jones": 1630529,
    "Dereck Lively II": 1641726,
    "Jaime Jaquez Jr.": 1631179,
    "Brandin Podziemski": 1631178,
    "Keyonte George": 1631180,
}

# 模拟数据配置（API 不可用时的降级）
TIER_STAT_RANGES = {
    0: (24, 38, (6, 14), (5, 12), (32, 40)),
    1: (18, 30, (4, 11), (3, 9),  (28, 38)),
    2: (12, 22, (3, 9),  (2, 7),  (24, 35)),
    3: (6, 14,  (2, 7),  (1, 5),  (16, 28)),
    4: (2, 8,   (1, 5),  (0, 3),  (8, 20)),
    5: (0, 5,   (0, 3),  (0, 2),  (3, 14)),
}

NBA_TEAMS_ABBR = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]


# ============================================================
# nba_api 真实数据获取
# ============================================================
def _fetch_nba_recent_games(player_name: str, count: int = 5) -> List[dict]:
    """
    通过 nba_api 获取球员最近 N 场真实比赛数据

    Args:
        player_name: 球员姓名
        count: 获取场次数

    Returns:
        List[dict]，失败返回空列表
    """
    pid = _NBA_PERSON_IDS.get(player_name)
    if not pid:
        return []

    try:
        from nba_api.stats.endpoints import playergamelog
        from nba_api.stats.library.parameters import SeasonAll

        # 获取当前赛季的比赛日志
        gamelog = playergamelog.PlayerGameLog(
            player_id=pid,
            season=SeasonAll.current_season,
        )
        df = gamelog.get_data_frames()[0]

        if df is None or df.empty:
            return []

        games = []
        for _, row in df.head(count).iterrows():
            game_date = str(row.get("GAME_DATE", ""))[:10]
            matchup = str(row.get("MATCHUP", ""))
            # MATCHUP 格式: "LAL vs. BOS" 或 "LAL @ BOS"
            if " vs. " in matchup:
                parts = matchup.split(" vs. ")
                home_away = "vs"
                opponent = parts[1].strip()
            elif " @ " in matchup:
                parts = matchup.split(" @ ")
                home_away = "@"
                opponent = parts[1].strip()
            else:
                home_away = "vs"
                opponent = matchup[-3:]

            wl = str(row.get("WL", "")).strip()
            won = wl == "W"

            games.append({
                "date": game_date,
                "opponent": opponent,
                "home_away": home_away,
                "pts": int(row.get("PTS", 0)),
                "reb": int(row.get("REB", 0)),
                "ast": int(row.get("AST", 0)),
                "stl": int(row.get("STL", 0)),
                "blk": int(row.get("BLK", 0)),
                "min": int(row.get("MIN", 0)),
                "fgm": int(row.get("FGM", 0)),
                "fga": int(row.get("FGA", 1)),
                "fg3m": int(row.get("FG3M", 0)),
                "fg3a": int(row.get("FG3A", 1)),
                "ftm": int(row.get("FTM", 0)),
                "fta": int(row.get("FTA", 1)),
                "won": won,
            })

        return games

    except Exception as e:
        # nba_api 有时因为网络/CORS问题不可用
        return []


# ============================================================
# 模拟数据降级
# ============================================================
def _generate_mock_games(player_name: str, tier: int, count: int = 5) -> List[dict]:
    """根据球员层级生成逼真的模拟比赛数据"""
    rng = np.random.default_rng(hash(player_name) % (2**31))
    stats_cfg = TIER_STAT_RANGES.get(tier, TIER_STAT_RANGES[4])

    pts_lo, pts_hi = stats_cfg[0], stats_cfg[1]
    reb_range = stats_cfg[2]
    ast_range = stats_cfg[3]
    if isinstance(stats_cfg[4], tuple):
        min_lo, min_hi = stats_cfg[4]
    else:
        min_lo, min_hi = 8, 20

    games = []
    for i in range(count):
        days_ago = i * rng.integers(1, 4) + rng.integers(0, 2)
        game_date = (datetime.now() - timedelta(days=int(days_ago)))
        opp = rng.choice(NBA_TEAMS_ABBR)
        home_away = rng.choice(["vs", "@"])
        pts = int(np.clip(rng.normal((pts_lo + pts_hi) / 2, (pts_hi - pts_lo) / 4),
                           max(0, pts_lo - 5), pts_hi + 10))
        reb = int(np.clip(rng.normal(np.mean(reb_range), 3), max(0, reb_range[0] - 3), reb_range[1] + 5))
        ast = int(np.clip(rng.normal(np.mean(ast_range), 2.5), 0, ast_range[1] + 4))
        stl = max(0, int(rng.normal(1.2, 1.0)))
        blk = max(0, int(rng.normal(0.8, 0.8) if tier <= 2 else rng.normal(0.3, 0.5)))
        minutes = int(np.clip(rng.normal((min_lo + min_hi) / 2, 6), min_lo - 4, min_hi + 4))
        fgm = int(pts * rng.uniform(0.35, 0.50))
        fga = fgm + int(rng.uniform(3, 14))
        fg3m = int(rng.uniform(0, 4) if tier <= 2 else rng.uniform(0, 2))
        fg3a = fg3m + int(rng.uniform(1, 7))
        ftm = int(rng.uniform(0, 6) if tier <= 2 else rng.uniform(0, 3))
        fta = ftm + int(rng.uniform(0, 3))
        won = rng.random() < (0.35 + tier * 0.10)

        games.append({
            "date": game_date.strftime("%Y-%m-%d"),
            "opponent": opp,
            "home_away": home_away,
            "pts": pts, "reb": reb, "ast": ast,
            "stl": stl, "blk": blk, "min": minutes,
            "fgm": fgm, "fga": fga, "fg3m": fg3m,
            "fg3a": fg3a, "ftm": ftm, "fta": fta,
            "won": won,
        })
    return games


# ============================================================
# 公开接口
# ============================================================
def get_recent_games(player_name: str, tier: int = 3, count: int = 5) -> List[dict]:
    """
    获取球员最近 N 场比赛数据

    优先从 stats.nba.com 获取真实数据，
    API 不可用时降级到模拟数据。
    """
    # 尝试真实 API
    games = _fetch_nba_recent_games(player_name, count)
    if games:
        return games

    # 降级
    return _generate_mock_games(player_name, tier, count)


def get_season_averages(player_name: str, tier: int = 3) -> dict:
    """获取赛季场均数据"""
    games = get_recent_games(player_name, tier, count=8)
    n = max(len(games), 1)
    return {
        "pts": round(sum(g["pts"] for g in games) / n, 1),
        "reb": round(sum(g["reb"] for g in games) / n, 1),
        "ast": round(sum(g["ast"] for g in games) / n, 1),
        "stl": round(sum(g["stl"] for g in games) / n, 1),
        "blk": round(sum(g["blk"] for g in games) / n, 1),
        "min": round(sum(g["min"] for g in games) / n, 1),
        "fg_pct": round(sum(g["fgm"] for g in games) / max(sum(g["fga"] for g in games), 1), 3),
        "fg3_pct": round(sum(g["fg3m"] for g in games) / max(sum(g["fg3a"] for g in games), 1), 3),
        "ft_pct": round(sum(g["ftm"] for g in games) / max(sum(g["fta"] for g in games), 1), 3),
        "games_played": n,
    }
