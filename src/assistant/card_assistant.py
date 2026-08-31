"""
AI 助手：本地数据表找不到 → 联网搜索
=====================================
两类能力（服务对象：Streamlit 前端 / FastAPI）：

1. resolve_player(name) —— 球员识别
   本地球员库(505人) → Wikipedia 联网识别(球队/位置/新秀年/tier) → 注册进球员库
   识别结果缓存到 data/player_extra.json，跨会话生效，后续启动自动加载。

2. search_price_reference(player_name) —— 价格参考
   本地 comps 数据库(卡淘真实成交) → 无命中时实时采集卡淘公开列表
   (拍卖/最新/即将结束)，按球员名过滤展示真实价格信号。

用法:
    from src.assistant.card_assistant import CardAssistant
    ai = CardAssistant()
    info = ai.resolve_player("James Bouknight")   # -> dict 或 None
    refs = ai.search_price_reference("James Bouknight")  # -> list[dict]
"""

import json
import os
import re
import sys
import time
from typing import Dict, List, Optional

import requests

# 项目根目录（src/assistant → 项目根）
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_EXTRA_PLAYERS_PATH = os.path.join(_PROJECT_ROOT, "data", "player_extra.json")

_REQUEST_TIMEOUT = 15
_HTTP_HEADERS = {"User-Agent": "StarCardAnalyzer/1.0 (personal card pricing tool)"}

# NBA 球队英文名（Wikipedia 摘要匹配用）
_NBA_TEAMS_EN = [
    "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets",
    "Chicago Bulls", "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets",
    "Detroit Pistons", "Golden State Warriors", "Houston Rockets",
    "Indiana Pacers", "LA Clippers", "Los Angeles Lakers", "Memphis Grizzlies",
    "Miami Heat", "Milwaukee Bucks", "Minnesota Timberwolves",
    "New Orleans Pelicans", "New York Knicks", "Oklahoma City Thunder",
    "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns", "Portland Trail Blazers",
    "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors", "Utah Jazz",
    "Washington Wizards",
]

# 位置关键词（英文 → 缩写）
_POSITION_KEYWORDS = [
    ("PG", ["point guard", "控球后卫"]),
    ("SG", ["shooting guard", "得分后卫"]),
    ("SF", ["small forward", "小前锋"]),
    ("PF", ["power forward", "大前锋"]),
    ("C",  ["center", "中锋"]),
]


class CardAssistant:
    """AI 助手：本地数据表 → 联网搜索 的兜底识别与参考价查询"""

    def __init__(self):
        self._cache = self._load_cache()

    # ============================================================
    # 1. 球员识别
    # ============================================================

    def resolve_player(self, name: str) -> Optional[Dict]:
        """
        识别球员信息：本地球员库 → 联网缓存 → Wikipedia 联网识别

        Returns:
            {name, team, jersey, rookie_year, tier, position, source}
            失败返回 None
        """
        name = (name or "").strip()
        if not name:
            return None

        # 1) 本地球员库（精确匹配）
        from src.data.player_db import get_player_by_name
        info = get_player_by_name(name)
        if info:
            return {**info, "source": "本地球员库"}

        # 2) 联网识别缓存（上次识别过的直接复用）
        if name in self._cache:
            cached = dict(self._cache[name])
            # 重新注册（防上次会话未持久化）
            from src.data.player_db import register_extra_player
            register_extra_player(**cached)
            return {**cached, "source": "联网缓存"}

        # 3) 联网识别（TheSportsDB 主源 → Wikipedia/Bing/百度百科兜底）
        found = self._thesportsdb_lookup(name) or self._wiki_lookup(name) \
            or self._search_bing(name) or self._baidu_baike_lookup(name)
        if found:
            info = {
                "name": found["name"],
                "team": found["team"],
                "jersey": 0,
                "rookie_year": found["rookie_year"],
                "tier": found["tier"],
                "position": found["position"],
                "avatar": found.get("avatar", ""),
            }
            self._cache[name] = info
            self._save_cache()
            from src.data.player_db import register_extra_player
            register_extra_player(**info)
            return {**info, "source": "联网搜索"}

        return None

    def _wiki_lookup(self, name: str) -> Optional[Dict]:
        """Wikipedia REST API 摘要识别：球队/位置/新秀年/tier"""
        for lang in ("en", "zh"):
            try:
                slug = requests.utils.quote(name.replace(" ", "_"))
                url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{slug}"
                resp = requests.get(url, timeout=_REQUEST_TIMEOUT,
                                    headers=_HTTP_HEADERS)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                extract = data.get("extract", "") or ""
                desc = data.get("description", "") or ""
                text = (extract + " " + desc).lower()
                # 必须与篮球相关（防止同名非篮球人物）
                if not re.search(r"basketball|nba|篮球", text):
                    continue
                return {
                    "name": data.get("title", name),
                    "team": self._parse_team(extract),
                    "position": self._parse_position(extract),
                    "rookie_year": self._parse_rookie_year(extract),
                    "tier": self._estimate_tier(extract),
                }
            except Exception:
                continue
        return None

    # TheSportsDB 位置文本 → 缩写
    _POSITION_TEXT_MAP = {
        "point guard": "PG", "shooting guard": "SG", "small forward": "SF",
        "power forward": "PF", "center": "C", "guard": "G", "forward": "F",
        "guard-forward": "GF", "forward-center": "FC",
    }

    def _thesportsdb_lookup(self, name: str) -> Optional[Dict]:
        """
        TheSportsDB 免费 API（国内可达，无 key）：结构化球员信息
        返回 {name, team, position, rookie_year, tier, avatar}
        """
        try:
            url = ("https://www.thesportsdb.com/api/v1/json/3/searchplayers.php?p="
                   + requests.utils.quote(name))
            resp = requests.get(url, timeout=10, headers=_HTTP_HEADERS)
            if resp.status_code != 200:
                return None
            players = resp.json().get("player") or []
            if not players:
                return None
            p = players[0]
            sport = str(p.get("strSport", "")).lower()
            if sport and "basket" not in sport:
                return None  # 非篮球球员
            position_text = str(p.get("strPosition", "")).lower()
            position = self._POSITION_TEXT_MAP.get(position_text, "")
            team = str(p.get("strTeam", ""))
            if team not in _NBA_TEAMS_EN:
                team = ""  # G 联赛/海外球队不纳入球队匹配
            # 选秀年：简介正则 → 生日估算
            desc = str(p.get("strDescriptionEN", "") or "")
            rookie_year = self._parse_rookie_year(desc)
            born = str(p.get("dateBorn", ""))
            if not rookie_year and re.match(r"\d{4}-\d{2}-\d{2}", born):
                rookie_year = int(born[:4]) + 21  # 估算：多数球员 21 岁参选
            return {
                "name": str(p.get("strPlayer", name)),
                "team": team,
                "position": position,
                "rookie_year": rookie_year,
                "tier": self._estimate_tier(desc),
                "avatar": str(p.get("strThumb", "") or ""),
            }
        except Exception:
            return None

    def _search_bing(self, name: str) -> Optional[Dict]:
        """Bing 搜索（国内可访问）：从搜索结果标题+摘要提取球员信息"""
        try:
            q = f"{name} NBA basketball player team draft"
            url = ("https://www.bing.com/search?q="
                   + requests.utils.quote(q) + "&setlang=zh-hans&count=10")
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0 Safari/537.36",
            })
            if resp.status_code != 200:
                return None
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            best = None
            for li in soup.select("li.b_algo")[:6]:
                h2 = li.find("h2")
                p = li.find("p") or li.find("div", class_="b_caption")
                if not h2:
                    continue
                text = h2.get_text(" ", strip=True) + " "
                text += p.get_text(" ", strip=True) if p else ""
                if not re.search(r"basketball|nba", text.lower()):
                    continue
                info = {
                    "name": name,
                    "team": self._parse_team(text),
                    "position": self._parse_position(text),
                    "rookie_year": self._parse_rookie_year(text),
                    "tier": self._estimate_tier(text),
                }
                # 至少命中球队或新秀年其一才算有效识别
                if info["team"] or info["rookie_year"]:
                    return info
                best = info
            return best
        except Exception:
            return None

    def _baidu_baike_lookup(self, name: str) -> Optional[Dict]:
        """百度百科兜底：搜索词条页并解析内容"""
        try:
            url = ("https://baike.baidu.com/search/word?word="
                   + requests.utils.quote(name))
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0 Safari/537.36",
            })
            if resp.status_code != 200:
                return None
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(" ", strip=True)[:8000]
            if not re.search(r"篮球|NBA|basketball", text, re.IGNORECASE):
                return None
            return {
                "name": name,
                "team": self._parse_team(text),
                "position": self._parse_position(text),
                "rookie_year": self._parse_rookie_year(text),
                "tier": self._estimate_tier(text),
            }
        except Exception:
            return None

    def _parse_team(self, extract: str) -> str:
        """从摘要提取球队：'for the Charlotte Hornets of the NBA' / '效力于夏洛特黄蜂'"""
        for team in _NBA_TEAMS_EN:
            if team.lower() in extract.lower():
                return team
        # 中文队名兜底：命中中文则返回英文名（此处简单返回空，由前端展示原名）
        return ""

    def _parse_position(self, extract: str) -> str:
        """从摘要提取位置：'point guard' → 'PG'"""
        low = extract.lower()
        for abbr, kws in _POSITION_KEYWORDS:
            for kw in kws:
                if kw in low:
                    return abbr
        return ""

    def _parse_rookie_year(self, extract: str) -> int:
        """从摘要提取新秀年：'selected in the 2021 NBA draft' / '2021年NBA选秀'"""
        m = re.search(r"(?:selected|drafted|pick).{0,40}?(20\d{2})\s*nba\s*draft",
                      extract, re.IGNORECASE)
        if m:
            return int(m.group(1))
        m = re.search(r"(20\d{2})\s*nba\s*draft", extract, re.IGNORECASE)
        if m:
            return int(m.group(1))
        m = re.search(r"(20\d{2})年\s*nba\s*选秀", extract, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return 0

    def _estimate_tier(self, extract: str) -> int:
        """按摘要关键词估算球星等级（用于未知球员的 star_power 兜底）"""
        low = extract.lower()
        if re.search(r"mvp|most valuable player", low):
            return 0
        if re.search(r"all[- ]star", low):
            return 1
        if re.search(r"starting (point guard|shooting guard|small forward|power forward|center)",
                     low):
            return 2
        if re.search(r"(20\d{2}) nba draft", low):
            return 2  # 近年代际新秀
        return 3

    # ============================================================
    # 2. 价格参考
    # ============================================================

    def search_price_reference(self, player_name: str,
                               max_pages: int = 3) -> List[Dict]:
        """
        查询球员真实成交参考：本地 comps 数据库 → 卡淘实时列表采集

        Returns:
            [ {title, price_cny, price_usd, bids, source, sold_date}, ... ]
        """
        name = (player_name or "").strip().lower()
        if not name:
            return []

        # 1) 本地真实成交数据库
        local = self._local_hits(name)
        if local:
            return local

        # 2) 卡淘实时采集（公开列表，无需登录）
        return self._cardhobby_live_hits(name, max_pages=max_pages)

    def _local_hits(self, name_lower: str) -> List[Dict]:
        import pandas as pd
        hits = []
        for path, src_label in [
            (os.path.join(_PROJECT_ROOT, "data", "cardhobby_comps_database.csv"), "卡淘数据库"),
        ]:
            if not os.path.exists(path):
                continue
            try:
                df = pd.read_csv(path)
                mask = df["player_name"].astype(str).str.lower().str.contains(
                    name_lower, na=False)
                for _, r in df[mask].head(5).iterrows():
                    hits.append({
                        "title": str(r.get("title", ""))[:60],
                        "price_cny": r.get("price_cny", None),
                        "price_usd": r.get("price_usd", r.get("price", None)),
                        "bids": r.get("bids", None),
                        "sold_date": r.get("sold_date", ""),
                        "source": src_label,
                    })
            except Exception:
                continue
        return hits

    def _cardhobby_live_hits(self, name_lower: str,
                             max_pages: int = 3) -> List[Dict]:
        """采集卡淘公开三列表（拍卖/最新/即将结束），按球员名过滤"""
        try:
            from src.scrapers.cardhobby_scraper import CardHobbyScraper
            scraper = CardHobbyScraper()
            items = scraper.scrape_all_lists(max_pages=max_pages)
        except Exception:
            return []
        hits = []
        for it in items:
            title = str(it.title or "")
            if name_lower in title.lower():
                hits.append({
                    "title": title[:60],
                    "price_cny": it.price_cny,
                    "price_usd": round(it.price_cny / 7.25, 2),
                    "bids": it.bids,
                    "sold_date": "",
                    "source": "卡淘实时采集",
                })
            if len(hits) >= 5:
                break
        return hits

    # ============================================================
    # 缓存持久化
    # ============================================================

    def _load_cache(self) -> Dict:
        try:
            if os.path.exists(_EXTRA_PLAYERS_PATH):
                with open(_EXTRA_PLAYERS_PATH, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    def _save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(_EXTRA_PLAYERS_PATH), exist_ok=True)
            with open(_EXTRA_PLAYERS_PATH, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


if __name__ == "__main__":
    # 简单自测：python src/assistant/card_assistant.py
    sys.path.insert(0, _PROJECT_ROOT)
    sys.stdout.reconfigure(encoding="utf-8")
    ai = CardAssistant()
    for test_name in ["James Bouknight", "Victor Wembanyama", "张三丰"]:
        info = ai.resolve_player(test_name)
        if info:
            print(f"[{test_name}] -> {info}")
        else:
            print(f"[{test_name}] -> 未识别")
