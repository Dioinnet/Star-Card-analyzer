"""
构建真实数据驱动的 eBay + CardHobby 可比成交数据库
============================================
从真实网站采集成交/在拍数据，解析卡片特征，输出 train.py 可用的训练数据。

数据源 (2026-08 实测可用):
  * eBay:     https://www.ebay.com/sch/i.html?_nkw=...&LH_Sold=1&LH_Complete=1
              (已售出成交记录；三层后端: curl_cffi → playwright)
  * CardHobby: https://www.cardhobby.com.cn/market/auction?page=N
              (卡淘官方域名已从 .com 变更为 .com.cn；
               在拍拍卖列表公开可见，成交记录需登录)

特征解析:
  * eBay 标题为英文 → TitleParser + 英文正则
  * CardHobby 标题为中英混合 → 中文关键词（新秀/签字/物料/折种/评级）+ 英文正则

用法:
    python scripts/build_comps_db.py                      # 默认 15 名球星, eBay + CardHobby
    python scripts/build_comps_db.py --players 30         # 采集 30 名球星
    python scripts/build_comps_db.py --skip-ebay          # 仅 CardHobby
    python scripts/build_comps_db.py --skip-cardhobby     # 仅 eBay
    python scripts/build_comps_db.py --ebay-pages 2 --cardhobby-pages 5

输出:
    data/ebay_comps_database.csv          — eBay 真实成交记录
    data/cardhobby_comps_database.csv     — CardHobby 真实在拍数据
    data/raw/ebay_raw_*.json              — eBay 原始 JSON 缓存
    data/raw/cardhobby_raw_*.json         — CardHobby 原始 JSON 缓存
"""

import sys
import os
import io
import re
import time
import json
import argparse
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

# 强制UTF-8编码，避免Windows GBK兼容问题
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.data.player_db import get_all_players
from src.scrapers.ebay_scraper import EbayScraper, EbayListingItem
from src.scrapers.cardhobby_scraper import CardHobbyScraper, CardHobbyListing


# ============================================================
# 卡片特征解析（真实标题 → 结构化字段）
# ============================================================

# 产品系列关键词（与 data_pipeline.TitleParser.SERIES_KEYWORDS 对齐）
SERIES_KEYWORDS = {
    "Prizm": ["prizm"],
    "Select": ["select"],
    "National Treasures": ["national treasures", "nt "],
    "Donruss": ["donruss"],
    "Mosaic": ["mosaic"],
    "Optic": ["optic"],
    "Hoops": ["hoops"],
    "Flawless": ["flawless"],
    "Immaculate": ["immaculate"],
    "Noir": ["noir"],
    "Contenders": ["contenders"],
    "Crusade": ["crusade"],
    "Spectra": ["spectra"],
    "One and One": ["one and one", "one & one"],
    "Chronicles": ["chronicles"],
    "Recon": ["recon"],
    "Origins": ["origins"],
    "Elite": [" elite "],
    "Certified": ["certified"],
    "Topps Chrome": ["topps chrome", "chrome"],
    "Topps Finest": ["finest"],
    "Topps Dynasty": ["dynasty"],
}

# 折射/平行: 英文关键词 → (折射等级 0-5, 标准名)
REFRACTION_MAP = [
    (5, "1of1", ["1/1", "one of one", "one-of-one", "独编", "限量1张"]),
    (4, "Black", ["black", "黑折", "黑金"]),
    (4, "Gold", ["gold", "金折", "金标", "金色"]),
    (3, "Mojo", ["mojo", "魔彩"]),
    (3, "Red", ["red", "红折", "红波纹"]),
    (3, "Pink", ["pink", "粉折", "粉"]),
    (3, "Purple", ["purple", "紫折"]),
    (3, "Blue", ["blue", "蓝折"]),
    (3, "Green", ["green", "绿折"]),
    (3, "Orange", ["orange", "橙折"]),
    (2, "Silver", ["silver", "银折", "银标", "银子"]),
    (2, "White Sparkle", ["white sparkle", "白折"]),
    (2, "Cracked Ice", ["cracked ice", "冰折"]),
    (2, "Disco", ["disco"]),
    (2, "Pulsar", ["pulsar"]),
    (2, "Wave", ["wave", "波纹"]),
    (2, "Checkerboard", ["checkerboard", "棋盘"]),
    (2, "Hyper", ["hyper"]),
    (2, "Lazer", ["lazer", "laser"]),
    (2, "Zebra", ["zebra", "斑马"]),
    (2, "Tiger", ["tiger"]),
    (2, "Snake", ["snake", "蛇皮"]),
    (2, "Elephant", ["elephant"]),
    (2, "Choice", ["choice"]),
    (2, "Neon", ["neon"]),
    (2, "FOTL", ["fotl", "首日"]),
    (2, "Fast Break", ["fast break"]),
    (2, "Asia", ["asia"]),
    (2, "Redemption", ["redemption", "兑换"]),
    (2, "Press Proof", ["press proof"]),
    (1, "Blue Prizm", ["blue prizm"]),
    (1, "Red Prizm", ["red prizm"]),
    (0, "Base", []),
]

AUTO_KEYWORDS_EN = ["auto", "autograph", "signed", "on-card", "on card", "rpa", "rps"]
AUTO_KEYWORDS_CN = ["签字", "亲签", "签名", "贴签"]
MATERIAL_KEYWORDS_EN = ["patch", "jersey", "relic", "memorabilia", "logoman", "tag", "rpa", "pants", "shoe"]
MATERIAL_KEYWORDS_CN = ["球衣", "物料", "球票", "球裤", "球鞋", "patch", "pa", "logoman"]
GRADER_MAP = {"PSA": 1, "BGS": 2, "SGC": 3, "CGC": 4, "CSG": 5, "HGA": 6}

# 中国评级公司
CN_GRADERS = {"保粹": 1, "中评": 2, "金卡": 3, "CCG": 4, "源评": 5}


def parse_card_title(title: str, fallback_player: str = "") -> Dict[str, Any]:
    """
    从真实 listing 标题解析卡片特征（兼容英文与中英混合标题）

    Args:
        title: listing 标题
        fallback_player: 搜索上下文中的球员名（eBay 按球员搜索时使用）

    Returns:
        结构化特征字典（与旧 build_comps_db 输出的字段一致）
    """
    feat = {
        "player_name": fallback_player or "Unknown Player",
        "product": "Prizm",           # 默认
        "card_year": 0,
        "is_rookie": 0,
        "refraction_level": 0,
        "refraction_name": "Base",
        "serial_number": 0,
        "serial_max": 0,
        "has_auto": 0,
        "auto_type": 0,
        "auto_type_name": "None",
        "has_material": 0,
        "material_windows": 0,
        "material_colors": 0,
        "is_logoman": 0,
        "is_tag": 0,
        "has_grade": 0,
        "grade_score": 0.0,
        "grade_grader": 0,
        "grade_grader_name": "None",
    }
    if not title:
        return feat

    t = title
    t_lower = t.lower()

    # ---- 年份: "2019-20" / "2020-21" / "2020" ----
    m = re.search(r'\b(20\d{2})\s*[-–]\s*\d{0,2}', t)
    if m:
        feat["card_year"] = int(m.group(1))
    else:
        m = re.search(r'\b(20\d{2})\b', t)
        if m:
            feat["card_year"] = int(m.group(1))

    # ---- 产品系列 ----
    for series_name, keywords in SERIES_KEYWORDS.items():
        for kw in keywords:
            if kw in t_lower:
                feat["product"] = series_name
                break
        if feat["product"] != "Prizm" or "prizm" in t_lower:
            pass
    # 校正: 若实际没匹配到 Prizm 但默认了 Prizm → 保持默认（模型可接受）

    # ---- 折射/平行 ----
    for level, name, keywords in REFRACTION_MAP:
        for kw in keywords:
            if kw in t_lower or (kw.isalpha() and re.search(rf'\b{re.escape(kw)}\b', t_lower)):
                feat["refraction_level"] = level
                feat["refraction_name"] = name
                break
        if feat["refraction_level"] > 0:
            break

    # ---- 1/1 ----
    if re.search(r'\b1\s*/\s*1\b|one\s+of\s+one|独编', t, re.IGNORECASE):
        feat["refraction_level"] = 5
        feat["refraction_name"] = "1of1"
        feat["serial_max"] = 1

    # ---- 限量编号: "/99", "#/49", "限量99张", "/149编" ----
    # 注意: 标题中的 "#276" 通常是 checklist 卡号而非限量，
    # 限量一般写作 "/149"、"/149编"、"#/149"、"限量149张"
    # 优先级: "限量N张" > "/N编" > "#/N" > "/N"(与 # 无关联)
    m = re.search(r'限量\s*(\d{1,3})\s*张', t)
    if m and not feat["serial_max"]:
        print_run = int(m.group(1))
        if 2 <= print_run <= 999:
            feat["serial_max"] = print_run
    m = re.search(r'/\s*(\d{1,3})\s*编', t)
    if m and not feat["serial_max"]:
        print_run = int(m.group(1))
        if 2 <= print_run <= 999:
            feat["serial_max"] = print_run
    m = re.search(r'#\s*/\s*(\d{1,3})\b', t)
    if m and not feat["serial_max"]:
        print_run = int(m.group(1))
        if 2 <= print_run <= 999:
            feat["serial_max"] = print_run
            feat["serial_number"] = 0  # 序列号未知，置 0（对 scarcity 特征无影响）
    # 兜底: 裸 "/N"（前面没有 # 卡号干扰）
    m = re.search(r'(?<![#])\/\s*(\d{1,3})\b', t)
    if m and not feat["serial_max"]:
        print_run = int(m.group(1))
        if 2 <= print_run <= 999:
            feat["serial_max"] = print_run

    # ---- 签字 ----
    is_auto = any(kw in t_lower for kw in AUTO_KEYWORDS_EN) or \
              any(kw in t for kw in AUTO_KEYWORDS_CN)
    if is_auto:
        feat["has_auto"] = 1
        if any(kw in t_lower for kw in ["on-card", "on card", "卡签", "板签"]):
            feat["auto_type"] = 2
            feat["auto_type_name"] = "On-Card"
        elif any(kw in t_lower for kw in ["inscription"]):
            feat["auto_type"] = 3
            feat["auto_type_name"] = "Inscription"
        else:
            feat["auto_type"] = 1
            feat["auto_type_name"] = "Sticker"

    # ---- 物料 ----
    is_mat = any(kw in t_lower for kw in MATERIAL_KEYWORDS_EN) or \
             any(kw in t for kw in MATERIAL_KEYWORDS_CN)
    if is_mat:
        feat["has_material"] = 1
        # 窗数: 从 "2-Color Patch" / "三窗" / "1/1 Patch" 等提取
        m = re.search(r'(\d)\s*-?\s*(?:Color|Clr|色)', t, re.IGNORECASE)
        if m:
            feat["material_colors"] = int(m.group(1))
            feat["material_windows"] = min(int(m.group(1)), 3)
        m = re.search(r'(\d)\s*(?:窗|Window)', t)
        if m:
            feat["material_windows"] = int(m.group(1))
        if re.search(r'logoman|logo\s*man', t_lower) or "logo" in t_lower and "man" in t_lower:
            feat["is_logoman"] = 1
        if re.search(r'\btag\b|tag卡|队标', t, re.IGNORECASE):
            feat["is_tag"] = 1

    # ---- 新秀 ----
    if re.search(r'\b(rc|rookie|rpa|rpas|auto rc)\b', t_lower) or any(
            kw in t for kw in ["新秀", "新秀卡", "元年"]):
        feat["is_rookie"] = 1

    # ---- 评级 ----
    m = re.search(r'\b(PSA|BGS|SGC|CGC|CSG|HGA)\s*(\d{1,2}(?:\.\d)?)', t, re.IGNORECASE)
    if m:
        feat["has_grade"] = 1
        feat["grade_grader"] = GRADER_MAP.get(m.group(1).upper(), 1)
        feat["grade_grader_name"] = m.group(1).upper()
        try:
            feat["grade_score"] = float(m.group(2))
        except ValueError:
            feat["grade_score"] = 9.0
    else:
        # 中文评级
        for g_name, g_code in CN_GRADERS.items():
            if g_name in t:
                feat["has_grade"] = 1
                feat["grade_grader"] = g_code
                feat["grade_grader_name"] = g_name
                m = re.search(r'(\d(?:\.\d)?)\s*分', t)
                feat["grade_score"] = float(m.group(1)) if m else 9.0
                break

    # ---- 球员名（优先用球员库 505 人名单做子串匹配，比启发式可靠） ----
    # 修复: "Hoops Kobe Bryant" 等标题会把系列名 Hoops 泄漏进球员名 → 库匹配优先
    db_name = _extract_player_name(t)
    if db_name:
        feat["player_name"] = db_name
    elif fallback_player:
        feat["player_name"] = fallback_player
    else:
        # 兜底启发式：提取最长连续英文词串（跳过系列/折射/卡种术语词）
        skip_words = {"panini", "topps", "prizm", "select", "mosaic", "donruss",
                      "chrome", "finest", "national", "treasures", "basketball",
                      "football", "hockey", "baseball", "hoops", "silver", "gold",
                      "black", "green", "blue", "red", "pink", "purple", "base",
                      "rookie", "auto", "patch", "psa", "bgs", "sgc", "rc", "rpa",
                      "rpas", "card", "cards", "nba", "mlb", "nfl", "nhl", "tc",
                      "the", "and", "of", "with", "c", "p", "限量", "新秀", "签字",
                      # 2025-26 Topps 系列名/卡种术语（防 "Signature Class Xxx" 混入球员名）
                      "signature", "class", "flagship", "bowman", "chronicles",
                      "instant", "court", "kings", "crown", "royale", "origins",
                      "manuscripts", "manuscript", "handwritten", "handwriting",
                      "penstroke", "ink", "ink签", "arrivals", "loading", "arrival",
                      "dynasty", "match", "attax", "futera", "unique", "eternal",
                      "shard", "fansmall", "light", "best", "stadium", "club",
                      "premier", "league", "champions", "ucca", "ucc", "ucb",
                      "euro", "road", "world", "cup", "soccer", "game", "worn"}
        name_candidates = re.findall(r"[A-Za-z][A-Za-z\s'\-\.]{2,40}", t)
        best = ""
        best_len = 0
        for cand in name_candidates:
            words = [w for w in cand.split() if w.lower() not in skip_words and len(w) > 1]
            joined = " ".join(words).strip()
            score = len(joined)
            is_upper = joined.isupper()
            # 允许全大写球员名（CardHobby 标题常见），但要求 ≥6 字符且 ≥2 个单词
            if is_upper and (len(joined) < 6 or len(words) < 2):
                continue
            if score > best_len and 3 <= score <= 30:
                best_len = score
                best = joined.title() if is_upper else joined
        if best:
            feat["player_name"] = best

    return feat


# 球员库名称（长名优先，用于标题子串匹配）
_ALL_PLAYER_NAMES = None


def _extract_player_name(title: str) -> str:
    """
    用 505 人球员库（现役+退役）对标题做子串匹配，返回完整球员名

    标题如 "2020-21 Panini NBA Hoops Kobe Bryant H湖人 名宿..." → "Kobe Bryant"
    匹配失败返回 ""
    """
    global _ALL_PLAYER_NAMES
    if _ALL_PLAYER_NAMES is None:
        from src.data.player_db import get_all_players
        names = {p[0] for p in get_all_players()}
        # 长名优先（"Jaren Jackson Jr." 不会被 "Jackson" 抢占）
        _ALL_PLAYER_NAMES = sorted(names, key=lambda n: (-len(n), n))
    if not title:
        return ""
    t_lower = title.lower()
    for name in _ALL_PLAYER_NAMES:
        if len(name) >= 3 and name.lower() in t_lower:
            return name
    return ""


# 货币换算率（近似，与 data_pipeline.CURRENCY_RATES 对齐）
CURRENCY_TO_USD = {
    "USD": 1.0,
    "CNY": 1.0 / 7.25,
    "GBP": 1.27,
    "EUR": 1.08,
    "CAD": 0.73,
    "AUD": 0.66,
    "JPY": 1.0 / 150.0,
}


def ebay_item_to_record(item: EbayListingItem, fallback_player: str = "") -> Dict[str, Any]:
    """eBay listing → 训练记录（非 USD 货币自动换算为 USD）"""
    feat = parse_card_title(item.title, fallback_player)
    raw_price = item.total_price or item.price
    rate = CURRENCY_TO_USD.get(item.currency, 1.0)
    price_usd = round(raw_price * rate, 2)
    rec = {
        "source": "ebay",
        "item_id": item.item_id,
        "title": item.title,
        "player_name": feat["player_name"],
        "product": feat["product"],
        "card_year": feat["card_year"],
        "is_rookie": feat["is_rookie"],
        "refraction_level": feat["refraction_level"],
        "refraction_name": feat["refraction_name"],
        "serial_number": feat["serial_number"],
        "serial_max": feat["serial_max"],
        "has_auto": feat["has_auto"],
        "auto_type": feat["auto_type"],
        "auto_type_name": feat["auto_type_name"],
        "has_material": feat["has_material"],
        "material_windows": feat["material_windows"],
        "material_colors": feat["material_colors"],
        "is_logoman": feat["is_logoman"],
        "is_tag": feat["is_tag"],
        "has_grade": feat["has_grade"],
        "grade_score": feat["grade_score"],
        "grade_grader": feat["grade_grader"],
        "grade_grader_name": feat["grade_grader_name"],
        "listing_type": item.listing_type,
        "sold_date": item.sold_date,
        "seller": item.seller_name,
        "currency": item.currency,
        "price": price_usd,
        "price_usd": price_usd,
        "is_sold": 1 if item.is_sold else 0,
    }
    return rec


def cardhobby_item_to_record(item: CardHobbyListing) -> Dict[str, Any]:
    """CardHobby listing → 训练记录"""
    feat = parse_card_title(item.title)
    rec = {
        "source": "cardhobby",
        "item_id": item.item_id,
        "title": item.title,
        "player_name": feat["player_name"],
        "product": feat["product"],
        "card_year": feat["card_year"],
        "is_rookie": feat["is_rookie"],
        "refraction_level": feat["refraction_level"],
        "refraction_name": feat["refraction_name"],
        "serial_number": feat["serial_number"],
        "serial_max": feat["serial_max"],
        "has_auto": feat["has_auto"],
        "auto_type": feat["auto_type"],
        "auto_type_name": feat["auto_type_name"],
        "has_material": feat["has_material"],
        "material_windows": feat["material_windows"],
        "material_colors": feat["material_colors"],
        "is_logoman": feat["is_logoman"],
        "is_tag": feat["is_tag"],
        "has_grade": feat["has_grade"],
        "grade_score": feat["grade_score"],
        "grade_grader": feat["grade_grader"],
        "grade_grader_name": feat["grade_grader_name"],
        "listing_type": item.listing_type,
        "sold_date": item.end_time[:10] if item.end_time else "",
        "seller": item.seller_name,
        "currency": "CNY",
        # 训练集统一用 USD（模型以美元计价，混入 CNY 会扭曲价格信号）
        "price": item.price_usd,
        "price_cny": item.price_cny,
        "price_usd": item.price_usd,
        "bids": item.bids,
    }
    return rec


# ============================================================
# 采集流程
# ============================================================

def collect_ebay(players: List[Tuple], max_pages: int, backend: str,
                 search_delay: float = 5.0) -> List[Dict]:
    """
    采集 eBay 真实市场数据（按球员 × 系列模板搜索）

    说明 (2026-08 实测):
      * eBay 对 LH_Sold=1 (已售出过滤) 的请求在部分网络（如中国区 IP）会
        强制登录或触发 Akamai 质询
      * 降级策略: 先尝试 sold 搜索；若被拦截（登录墙/质询），自动降级为
        常规搜索（在售商品价格 = 真实市场信号，训练模型足够）
      * 登录后（--ebay-login 一次即可）sold 数据可用，自动优先
    """
    from src.scrapers.ebay_scraper import CARD_SEARCH_TEMPLATES, _PlaywrightBackend

    records = []
    # 有登录态 → 优先用 Playwright 抓 sold 数据
    storage_state = os.path.join("data", ".ebay_storage_state.json")
    if os.path.exists(storage_state):
        print("[eBay] 检测到登录态，使用 Playwright 采集已售出数据")
        backend = "playwright"
    scraper = EbayScraper(region="us", backend=backend)
    print(f"\n{'='*60}")
    print(f"  [eBay采集] {len(players)} 名球员 × {len(CARD_SEARCH_TEMPLATES)} 个系列模板")
    print(f"{'='*60}")

    for idx, (name, jersey, rc_year, tier, pos, team) in enumerate(players):
        # 根据球员热度决定搜索次数：tier 0-1 全系列，其余只搜 2 个系列
        templates = CARD_SEARCH_TEMPLATES if tier <= 1 else CARD_SEARCH_TEMPLATES[:2]
        for brand, series, template in templates:
            keyword = template.format(player=name, year=rc_year)
            try:
                items = scraper.search(keyword, max_pages=max_pages)
                n_sold = sum(1 for it in items if it.is_sold)
                for it in items:
                    rec = ebay_item_to_record(it, fallback_player=name)
                    rec["player_name"] = name  # 搜索上下文球员名优先
                    rec["product"] = series    # 模板确定的系列优先
                    records.append(rec)
                tag = f" ({n_sold} 条已售出)" if n_sold else " (在售)"
                print(f"  [eBay] {name} | {series}: {len(items)} 条{tag}")
            except Exception as e:
                print(f"  [eBay] {name} {series} 采集失败: {str(e)[:100]}")
            # 每次搜索之间留间隔，降低触发 eBay 限流风险
            time.sleep(search_delay)
        print(f"  [eBay] 进度 {idx+1}/{len(players)}: {name} 累计 {len(records)} 条")

    return records


def collect_cardhobby(max_pages: int) -> List[Dict]:
    """
    采集 CardHobby 真实市场数据

    策略说明 (2026-08 实测):
      * 卡淘公开的在拍列表大部分是 ¥1 起拍 0 出价的商品（占 ~95%，无价格信号）
      * 有出价(>0)或价格较高(>¥5)的商品才是真实市场信号
      * 成交记录(soldlog)需要登录，匿名不可见
      * 卡淘为全品类平台（足球/F1/漫威等混排）→ 只保留篮球卡（is_basketball_card_title）
    """
    from src.data.player_db import is_basketball_card_title

    records = []
    scraper = CardHobbyScraper()
    print(f"\n{'='*60}")
    print(f"  [CardHobby采集] 三列表混合 {max_pages} 页/列表 (过滤无出价商品 + 非篮球品类)")
    print(f"{'='*60}")

    items = scraper.scrape_all_lists(max_pages=max_pages)
    kept = 0
    n_basketball = 0
    for it in items:
        # 过滤1: 无出价且低价(≤¥5)的商品 → 无真实价格信号，剔除
        if it.bids <= 0 and it.price_cny <= 5:
            continue
        # 过滤2: 非篮球卡（足球/F1/漫威/TCG 等）→ 剔除
        if not is_basketball_card_title(it.title):
            continue
        n_basketball += 1
        records.append(cardhobby_item_to_record(it))
        kept += 1

    print(f"[CardHobby] 有出价商品 {len(items)} 条 | 其中篮球卡 {n_basketball} 条")
    print(f"[CardHobby] 过滤后保留 {kept} 条篮球数据")
    return records


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="构建真实 eBay + CardHobby 成交数据库")
    parser.add_argument("--players", type=int, default=15,
                        help="参与采集的顶级球星数量（按 tier 排序），默认 15")
    parser.add_argument("--ebay-pages", type=int, default=2, help="每个关键词 eBay 翻页数")
    parser.add_argument("--search-delay", type=float, default=5.0,
                        help="eBay 每次搜索之间的间隔秒数（降低触发限流风险），默认 5")
    parser.add_argument("--cardhobby-pages", type=int, default=30,
                        help="CardHobby '即将结束'列表页数（约5%有出价信号，30页≈50条有效）")
    parser.add_argument("--backend", type=str, default="auto",
                        choices=["auto", "requests", "curl_cffi", "playwright"],
                        help="eBay 采集后端")
    parser.add_argument("--skip-ebay", action="store_true", help="跳过 eBay 采集")
    parser.add_argument("--skip-cardhobby", action="store_true", help="跳过 CardHobby 采集")
    parser.add_argument("--ebay-login", action="store_true",
                        help="打开浏览器登录 eBay 并保存登录态（解锁已售出数据），随后退出")
    parser.add_argument("--backup-fake", action="store_true",
                        help="保留旧模拟数据作为备份（不删除）")
    args = parser.parse_args()

    print("=" * 60)
    print("  球星卡真实成交数据库构建")
    print("=" * 60)

    # ---- 登录模式 ----
    if args.ebay_login:
        from src.scrapers.ebay_scraper import _PlaywrightBackend
        backend = _PlaywrightBackend(delay=0, headless=False)
        ok = backend.login()
        print("登录完成 ✅" if ok else "登录未完成，可再次运行 --ebay-login")
        return

    all_players = get_all_players()
    # 按 tier（p[3]，0=顶级球星）排序取前 N 名球星
    players = sorted(all_players, key=lambda p: p[3])[:args.players]
    print(f"  参与球员 ({len(players)}): {', '.join(p[0] for p in players[:8])} ...")

    # ---- 备份旧模拟数据 ----
    os.makedirs("data", exist_ok=True)
    for f in ["data/ebay_comps_database.csv", "data/cardhobby_comps_database.csv"]:
        if os.path.exists(f) and not args.backup_fake:
            bak = f.replace(".csv", "_backup.csv")
            # Windows 下 os.rename 不覆盖已存在文件 → 备份文件重名时追加时间戳
            if os.path.exists(bak):
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                bak = f.replace(".csv", f"_backup_{ts}.csv")
            os.rename(f, bak)
            print(f"  旧模拟数据已备份: {f} → {bak}")

    # ---- 采集 eBay ----
    ebay_records: List[Dict] = []
    if not args.skip_ebay:
        ebay_records = collect_ebay(players, args.ebay_pages, args.backend,
                                    args.search_delay)
    else:
        print("\n[跳过] eBay 采集")

    # ---- 采集 CardHobby ----
    ch_records: List[Dict] = []
    if not args.skip_cardhobby:
        ch_records = collect_cardhobby(args.cardhobby_pages)
    else:
        print("\n[跳过] CardHobby 采集")

    # ---- 保存原始缓存 ----
    os.makedirs("data/raw", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if ebay_records:
        with open(f"data/raw/ebay_raw_{ts}.json", "w", encoding="utf-8") as f:
            json.dump(ebay_records, f, ensure_ascii=False, indent=2)
        print(f"[缓存] eBay 原始记录 → data/raw/ebay_raw_{ts}.json")
    if ch_records:
        with open(f"data/raw/cardhobby_raw_{ts}.json", "w", encoding="utf-8") as f:
            json.dump(ch_records, f, ensure_ascii=False, indent=2)
        print(f"[缓存] CardHobby 原始记录 → data/raw/cardhobby_raw_{ts}.json")

    # ---- 构建训练数据库 ----
    print("\n" + "=" * 60)
    print("  构建训练数据库")
    print("=" * 60)

    n_saved = 0
    if ebay_records:
        df_e = pd.DataFrame(ebay_records)
        # 去重
        df_e = df_e.drop_duplicates(subset=["item_id", "price"], keep="first")
        df_e.to_csv("data/ebay_comps_database.csv", index=False)
        n_saved += len(df_e)
        print(f"  [eBay] {len(df_e)} 条真实成交记录 → data/ebay_comps_database.csv")
        if len(df_e) > 0:
            print(f"    价格范围: ${df_e['price'].min():.2f} ~ ${df_e['price'].max():.2f} | "
                  f"中位数 ${df_e['price'].median():.2f}")

    if ch_records:
        df_c = pd.DataFrame(ch_records)
        df_c = df_c.drop_duplicates(subset=["item_id", "price"], keep="first")
        df_c.to_csv("data/cardhobby_comps_database.csv", index=False)
        n_saved += len(df_c)
        print(f"  [CardHobby] {len(df_c)} 条真实在拍数据 → data/cardhobby_comps_database.csv")
        if len(df_c) > 0:
            print(f"    价格范围: ¥{df_c['price'].min():.2f} ~ ¥{df_c['price'].max():.2f} | "
                  f"中位数 ¥{df_c['price'].median():.2f}")

    print(f"\n{'='*60}")
    if n_saved == 0:
        print("  ⚠️  未采集到任何数据！")
        print("     检查网络/代理，或尝试: python scripts/build_comps_db.py --backend playwright")
    else:
        print(f"  ✅ 完成！共 {n_saved} 条真实数据")
        print("  现在可以运行: python train.py 使用真实数据训练模型")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
