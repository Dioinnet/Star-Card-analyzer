"""
NBA 球员荣誉数据库 (经联网搜索校验)
==============================
数据来源: NBA.com 官方 + stat-nba.com 交叉验证。

2024-25 赛季:
  总冠军: OKC Thunder (4-3 vs IND) | FMVP: SGA | MVP: SGA
  DPOY: Evan Mobley | ROY: Stephon Castle | MIP: Dyson Daniels
  6MOY: Payton Pritchard | 一阵: SGA, Jokic, Giannis, Mitchell, Tatum

2025-26 赛季:
  总冠军: NY Knicks (4-1 vs SAS) | FMVP: Jalen Brunson | MVP: SGA (连庄)
  DPOY: Victor Wembanyama (全票) | ROY: Cooper Flagg (DAL)
  MIP: Nickeil Alexander-Walker | 6MOY: Keldon Johnson
  一阵: SGA, Jokic, Wembanyama, Doncic, Cade Cunningham
  二阵: Jaylen Brown, Kawhi Leonard, Donovan Mitchell, Kevin Durant, Jalen Brunson
  三阵: Tyrese Maxey, Jamal Murray, Jalen Johnson, Jalen Duren, Chet Holmgren
  LeBron 21年来首次落选最佳阵容 (仅出战60场)
"""

import sys
import io
from typing import List, Dict

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

HonorList = List[Dict[str, str]]

_PLAYER_HONORS: Dict[str, HonorList] = {

    # ============================================================
    # Tier 0 — MVP/超巨
    # ============================================================
    "Shai Gilgeous-Alexander": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "1× (2025 OKC, 4-3胜步行者)"},
        {"icon": "🥇", "category": "MVP",
         "detail": "2× (2025, 2026) — 历史第14位连庄MVP"},
        {"icon": "🌟", "category": "FMVP",
         "detail": "1× (2025)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "4× (2023-2026)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "4× 一阵 (2023-2026)"},
        {"icon": "🏆", "category": "Clutch POY",
         "detail": "1× 关键球员 (2026)"},
        {"icon": "🏅", "category": "国际赛",
         "detail": "世界杯铜牌 (2023)"},
    ],
    "LeBron James": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "4× (2012 MIA, 2013 MIA, 2016 CLE, 2020 LAL)"},
        {"icon": "🥇", "category": "MVP",
         "detail": "4× (2009, 2010, 2012, 2013)"},
        {"icon": "🌟", "category": "FMVP",
         "detail": "4× (2012, 2013, 2016, 2020)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "21× (2005-2025)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "13× 一阵 / 3× 二阵 / 4× 三阵 (2026首次落选)"},
        {"icon": "👑", "category": "得分王",
         "detail": "1× (2008)"},
        {"icon": "🏅", "category": "奥运",
         "detail": "3× 金牌 (2008, 2012, 2024)"},
        {"icon": "📊", "category": "历史纪录",
         "detail": "历史得分王 / 历史首位40K+10K+10K"},
    ],
    "Nikola Jokic": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "1× (2023 DEN)"},
        {"icon": "🥇", "category": "MVP",
         "detail": "3× (2021, 2022, 2024)"},
        {"icon": "🌟", "category": "FMVP",
         "detail": "1× (2023)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "7× (2019-2025)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "4× 一阵 / 2× 二阵 / 1× 一阵(2025) / 1× 一阵(2026)"},
    ],
    "Giannis Antetokounmpo": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "1× (2021 MIL)"},
        {"icon": "🥇", "category": "MVP",
         "detail": "2× (2019, 2020)"},
        {"icon": "🌟", "category": "FMVP",
         "detail": "1× (2021)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "9× (2017-2025)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "6× 一阵 / 2× 二阵 / 1× 一阵(2025)"},
        {"icon": "🛡️", "category": "DPOY",
         "detail": "1× (2020)"},
    ],
    "Stephen Curry": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "4× (2015, 2017, 2018, 2022 GSW)"},
        {"icon": "🥇", "category": "MVP",
         "detail": "2× (2015, 2016 全票)"},
        {"icon": "🌟", "category": "FMVP",
         "detail": "1× (2022)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "10× (2014-2024)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "4× 一阵 / 4× 二阵 / 2× 三阵"},
        {"icon": "🎯", "category": "三分王",
         "detail": "NBA历史三分王"},
    ],
    "Kevin Durant": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "2× (2017, 2018 GSW)"},
        {"icon": "🥇", "category": "MVP",
         "detail": "1× (2014)"},
        {"icon": "🌟", "category": "FMVP",
         "detail": "2× (2017, 2018)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "15× (2010-2026)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "6× 一阵 / 5× 二阵 / 1× 二阵(2026) — 5队入选历史唯一"},
        {"icon": "👑", "category": "得分王",
         "detail": "4× (2010-2012, 2014)"},
        {"icon": "🏅", "category": "奥运",
         "detail": "4× 金牌 (历史最多)"},
    ],
    "Victor Wembanyama": [
        {"icon": "🛡️", "category": "DPOY",
         "detail": "1× (2026) — 全票当选, 历史最年轻"},
        {"icon": "⭐", "category": "全明星",
         "detail": "3× (2024-2026)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 一阵 (2026)"},
        {"icon": "🌟", "category": "ROY",
         "detail": "1× (2024 全票)"},
        {"icon": "🛡️", "category": "盖帽王",
         "detail": "2× (2024, 2026)"},
        {"icon": "📊", "category": "2026赛季",
         "detail": "率马刺62胜, 总决赛1-4负于尼克斯"},
        {"icon": "🏅", "category": "奥运",
         "detail": "银牌 (2024 巴黎)"},
    ],
    "Luka Doncic": [
        {"icon": "⭐", "category": "全明星",
         "detail": "6× (2020-2025)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "6× 一阵 (2020-2025) / 1× 一阵(2026)"},
        {"icon": "👑", "category": "得分王",
         "detail": "2× (2024, 2025 33.5分)"},
        {"icon": "🌟", "category": "ROY",
         "detail": "1× (2019)"},
    ],
    "Jayson Tatum": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "1× (2024 BOS)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "6× (2020-2025)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "3× 一阵 / 1× 一阵(2025) / 1× 三阵"},
        {"icon": "🏅", "category": "奥运",
         "detail": "2× 金牌 (2020, 2024)"},
    ],
    "Jalen Brunson": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "1× (2026 NYK, 4-1胜马刺)"},
        {"icon": "🌟", "category": "FMVP",
         "detail": "1× (2026)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "3× (2024-2026)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 二阵(2025) / 1× 二阵(2026)"},
        {"icon": "🏆", "category": "Clutch POY",
         "detail": "1× (2025)"},
    ],
    "Joel Embiid": [
        {"icon": "🥇", "category": "MVP",
         "detail": "1× (2023)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "7× (2018-2024)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 一阵 / 4× 二阵"},
        {"icon": "👑", "category": "得分王",
         "detail": "3× (2022-2024)"},
        {"icon": "🏅", "category": "奥运",
         "detail": "1× 金牌 (2024)"},
    ],
    "Anthony Davis": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "1× (2020 LAL)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "10× (2014-2025)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "4× 一阵 / 1× 二阵"},
        {"icon": "🏅", "category": "奥运",
         "detail": "2× 金牌 (2012, 2024)"},
    ],
    "Donovan Mitchell": [
        {"icon": "⭐", "category": "全明星",
         "detail": "6× (2020-2026)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 一阵(2025) / 1× 二阵(2023) / 1× 二阵(2026)"},
    ],

    # ============================================================
    # Tier 1 — 全明星
    # ============================================================
    "Anthony Edwards": [
        {"icon": "⭐", "category": "全明星",
         "detail": "4× (2023-2026)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 二阵 (2024)"},
        {"icon": "🏅", "category": "奥运",
         "detail": "1× 金牌 (2024)"},
    ],
    "Evan Mobley": [
        {"icon": "🛡️", "category": "DPOY",
         "detail": "1× (2025) — 击败 Daniels & Green"},
        {"icon": "⭐", "category": "全明星",
         "detail": "1× (2025)"},
    ],
    "Cade Cunningham": [
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 一阵 (2026) — 生涯首次"},
        {"icon": "⭐", "category": "全明星",
         "detail": "1× (2025)"},
    ],
    "Cooper Flagg": [
        {"icon": "🌟", "category": "ROY",
         "detail": "1× (2026) — 独行侠"},
        {"icon": "📋", "category": "新秀一阵",
         "detail": "1× (2026)"},
        {"icon": "🏆", "category": "选秀",
         "detail": "2025年状元 (DAL)"},
    ],
    "Stephon Castle": [
        {"icon": "🌟", "category": "ROY",
         "detail": "1× (2025) — 马刺"},
        {"icon": "📋", "category": "新秀一阵",
         "detail": "1× (2025)"},
    ],
    "Kawhi Leonard": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "2× (2014 SAS, 2019 TOR)"},
        {"icon": "🌟", "category": "FMVP",
         "detail": "2× (2014, 2019)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "6×"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "3× 一阵 / 2× 二阵 / 1× 二阵(2026)"},
        {"icon": "🛡️", "category": "DPOY",
         "detail": "2× (2015, 2016)"},
    ],
    "Jaylen Brown": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "1× (2024 BOS)"},
        {"icon": "🌟", "category": "FMVP",
         "detail": "1× (2024)"},
        {"icon": "⭐", "category": "全明星",
         "detail": "4× (2021-2024)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 二阵(2023) / 1× 二阵(2026)"},
    ],
    "Tyrese Maxey": [
        {"icon": "⭐", "category": "全明星",
         "detail": "2× (2024, 2025)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 三阵 (2026)"},
        {"icon": "📈", "category": "MIP",
         "detail": "1× (2024)"},
    ],
    "Chet Holmgren": [
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 三阵 (2026)"},
    ],
    "Jalen Duren": [
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 三阵 (2026)"},
    ],
    "Jalen Johnson": [
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 三阵 (2026)"},
    ],
    "Jamal Murray": [
        {"icon": "🏆", "category": "总冠军",
         "detail": "1× (2023 DEN)"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 三阵 (2026)"},
    ],
    "Dyson Daniels": [
        {"icon": "📈", "category": "MIP",
         "detail": "1× (2025) — 老鹰"},
    ],
    "Nickeil Alexander-Walker": [
        {"icon": "📈", "category": "MIP",
         "detail": "1× (2026) — 老鹰, 场均20.8分"},
    ],
    "Payton Pritchard": [
        {"icon": "📈", "category": "6MOY",
         "detail": "1× (2025) — 凯尔特人"},
    ],
    "Keldon Johnson": [
        {"icon": "📈", "category": "6MOY",
         "detail": "1× (2026) — 马刺, 63张第一选票"},
    ],
    "Damian Lillard": [
        {"icon": "⭐", "category": "全明星",
         "detail": "8×"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "1× 一阵 / 4× 二阵"},
        {"icon": "🌟", "category": "ROY",
         "detail": "1× (2013)"},
        {"icon": "🎯", "category": "NBA75大",
         "detail": "入选NBA75大球星"},
    ],

    # ============================================================
    # 老将
    # ============================================================
    "Chris Paul": [
        {"icon": "⭐", "category": "全明星", "detail": "12×"},
        {"icon": "📋", "category": "最佳阵容",
         "detail": "4× 一阵 / 5× 二阵 / 2× 三阵"},
        {"icon": "🤝", "category": "助攻王", "detail": "5×"},
    ],
    "Russell Westbrook": [
        {"icon": "🥇", "category": "MVP", "detail": "1× (2017)"},
        {"icon": "⭐", "category": "全明星", "detail": "9×"},
        {"icon": "📊", "category": "三双王", "detail": "NBA历史三双王"},
    ],
    "James Harden": [
        {"icon": "🥇", "category": "MVP", "detail": "1× (2018)"},
        {"icon": "⭐", "category": "全明星", "detail": "10×"},
        {"icon": "👑", "category": "得分王", "detail": "3× (2018-2020)"},
    ],
    "Jimmy Butler": [
        {"icon": "⭐", "category": "全明星", "detail": "6×"},
        {"icon": "📋", "category": "最佳阵容", "detail": "1× 二阵 / 4× 三阵"},
    ],
    "Kyrie Irving": [
        {"icon": "🏆", "category": "总冠军", "detail": "1× (2016 CLE)"},
        {"icon": "⭐", "category": "全明星", "detail": "8×"},
        {"icon": "🌟", "category": "ROY", "detail": "1× (2012)"},
    ],
    "Klay Thompson": [
        {"icon": "🏆", "category": "总冠军", "detail": "4× GSW"},
        {"icon": "⭐", "category": "全明星", "detail": "5×"},
    ],
    "Draymond Green": [
        {"icon": "🏆", "category": "总冠军", "detail": "4× GSW"},
        {"icon": "🛡️", "category": "DPOY", "detail": "1× (2017)"},
        {"icon": "⭐", "category": "全明星", "detail": "4×"},
    ],
    "Rudy Gobert": [
        {"icon": "🛡️", "category": "DPOY", "detail": "4× (2018-2024)"},
        {"icon": "⭐", "category": "全明星", "detail": "3×"},
    ],
    "DeMar DeRozan": [
        {"icon": "⭐", "category": "全明星", "detail": "6×"},
        {"icon": "📋", "category": "最佳阵容", "detail": "2× 二阵 / 1× 三阵"},
    ],
    "Paul George": [
        {"icon": "⭐", "category": "全明星", "detail": "9×"},
        {"icon": "📋", "category": "最佳阵容", "detail": "1× 一阵 / 5× 三阵"},
    ],

    # ============================================================
    # Tier 2+ 荣誉较少球员
    # ============================================================
    "Ja Morant": [
        {"icon": "⭐", "category": "全明星", "detail": "2× (2022, 2023)"},
        {"icon": "📋", "category": "最佳阵容", "detail": "1× 二阵 (2022)"},
        {"icon": "📈", "category": "MIP", "detail": "1× (2022)"},
        {"icon": "🌟", "category": "ROY", "detail": "1× (2020)"},
    ],
    "Zion Williamson": [
        {"icon": "⭐", "category": "全明星", "detail": "2× (2021, 2023)"},
    ],
    "Trae Young": [
        {"icon": "⭐", "category": "全明星", "detail": "4×"},
        {"icon": "📋", "category": "最佳阵容", "detail": "1× 三阵 (2022)"},
    ],
    "Devin Booker": [
        {"icon": "⭐", "category": "全明星", "detail": "4×"},
        {"icon": "📋", "category": "最佳阵容", "detail": "1× 一阵 (2022)"},
        {"icon": "🏅", "category": "奥运", "detail": "2× 金牌"},
    ],
    "Bam Adebayo": [
        {"icon": "⭐", "category": "全明星", "detail": "3×"},
        {"icon": "🏅", "category": "奥运", "detail": "2× 金牌"},
    ],
    "Tyrese Haliburton": [
        {"icon": "⭐", "category": "全明星", "detail": "3× (2023-2026)"},
        {"icon": "📋", "category": "最佳阵容", "detail": "1× 三阵 (2024)"},
        {"icon": "🤝", "category": "助攻王", "detail": "2× (2024, 2025)"},
    ],
    "LaMelo Ball": [
        {"icon": "⭐", "category": "全明星", "detail": "1× (2022)"},
        {"icon": "🌟", "category": "ROY", "detail": "1× (2021)"},
    ],
    "Paolo Banchero": [
        {"icon": "⭐", "category": "全明星", "detail": "2× (2024, 2025)"},
        {"icon": "🌟", "category": "ROY", "detail": "1× (2023)"},
    ],
    "Scottie Barnes": [
        {"icon": "⭐", "category": "全明星", "detail": "1× (2024)"},
        {"icon": "🌟", "category": "ROY", "detail": "1× (2022)"},
    ],
    "Tyrese Maxey": [
        {"icon": "⭐", "category": "全明星", "detail": "2× (2024, 2025)"},
        {"icon": "📋", "category": "最佳阵容", "detail": "1× 三阵 (2026)"},
    ],
    "Karl-Anthony Towns": [
        {"icon": "⭐", "category": "全明星", "detail": "4×"},
        {"icon": "🌟", "category": "ROY", "detail": "1× (2016)"},
    ],
    "Domantas Sabonis": [
        {"icon": "⭐", "category": "全明星", "detail": "3×"},
        {"icon": "🏀", "category": "篮板王", "detail": "2× (2023, 2024)"},
    ],
    "De'Aaron Fox": [
        {"icon": "⭐", "category": "全明星", "detail": "1× (2023)"},
        {"icon": "🏆", "category": "Clutch POY", "detail": "1× (2023)"},
    ],
    "Pascal Siakam": [
        {"icon": "🏆", "category": "总冠军", "detail": "1× (2019 TOR)"},
        {"icon": "⭐", "category": "全明星", "detail": "2×"},
        {"icon": "📈", "category": "MIP", "detail": "1× (2019)"},
    ],
    "Jaren Jackson Jr.": [
        {"icon": "🛡️", "category": "DPOY", "detail": "1× (2023)"},
        {"icon": "⭐", "category": "全明星", "detail": "1× (2023)"},
    ],
}


def get_player_honors(player_name: str) -> HonorList:
    if player_name in _PLAYER_HONORS:
        return _PLAYER_HONORS[player_name]
    for db_name, honors in _PLAYER_HONORS.items():
        if db_name.lower() == player_name.lower():
            return honors
    return []


def has_honors(player_name: str) -> bool:
    return len(get_player_honors(player_name)) > 0
