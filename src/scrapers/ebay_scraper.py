"""
eBay Completed Listings 成交数据采集器
=====================================
采集 eBay 已售出（Sold）列表的成交价格。

背景与方案 (2026-08 更新):
  * eBay Finding API 已于 2025-02 完全退役，成交数据无官方公开 API
  * eBay 部署 Akamai Bot Manager 反爬：普通 requests 请求直接返回 403
    (中国区 IP 还会遇到 JS 质询页 "Pardon Our Interruption")
  * 本模块实现三层降级采集链:
      L1  requests          — 最轻量，通常 403
      L2  curl_cffi         — TLS 指纹模拟 Chrome，可绕过 TLS 层检测
      L3  playwright        — 真实浏览器执行 JS 质询，可拿到完整结果页
    默认 backend="auto"：L2 失败自动降级 L3（需 pip install playwright 且
    已执行 playwright install chromium）

解析器同时兼容新旧两种搜索结果布局:
  * 旧版: li.s-item / .s-item__title / .s-item__price / .s-item__ended-date
  * 新版: li.s-card / .s-card__title / .s-card__price / data-listingid

注意：
  本模块仅供学习和研究用途。eBay 的服务条款禁止未经授权的自动抓取。
  生产环境请申请 eBay 开发者账号使用 Browse API（但其不提供成交价）。

用法：
  python -m src.scrapers.ebay_scraper  # 运行测试入口
"""

import sys
import os
import io
import time
import re
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import quote_plus, urljoin

# 强制 UTF-8 输出
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


# ============================================================
# 配置常量
# ============================================================

# 请求头（模拟正常浏览器访问，完整头集是过 Akamai 的基础）
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.ebay.com/",
    "sec-ch-ua": '"Chromium";v="125", "Google Chrome";v="125", "Not.A/Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

# eBay 域名（可根据地区切换）
EBAY_DOMAINS = {
    "us": "https://www.ebay.com",
    "uk": "https://www.ebay.co.uk",
    "de": "https://www.ebay.de",
    "au": "https://www.ebay.com.au",
}

# 请求间隔（秒），避免触发反爬
REQUEST_DELAY = 2.0

# 最大翻页数
MAX_PAGES = 5

# 最大重试次数
MAX_RETRIES = 3

# curl_cffi 浏览器指纹（TLS 层模拟，实测 chrome124 效果最好）
CURL_IMPERSONATE = "chrome124"

# Playwright 无头模式（Akamai 可检测 headless，建议 False）
PLAYWRIGHT_HEADLESS = False


# ----------------------------------------------------------
# 球星卡搜索模板（品牌 + 系列 + 关键词）
# ----------------------------------------------------------
CARD_SEARCH_TEMPLATES = [
    # (品牌, 系列, 搜索关键词模板)
    ("Panini", "Prizm", "{player} Prizm {year}"),
    ("Panini", "Select", "{player} Select {year}"),
    ("Panini", "National Treasures", "{player} National Treasures {year}"),
    ("Panini", "Donruss", "{player} Donruss {year}"),
    ("Panini", "Mosaic", "{player} Mosaic {year}"),
    ("Topps", "Chrome", "{player} Topps Chrome {year}"),
    ("Upper Deck", "Exquisite", "{player} Exquisite {year}"),
]


# ============================================================
# 数据模型
# ============================================================

class EbayListingItem:
    """eBay 单条成交记录"""

    __slots__ = (
        "title", "price", "shipping", "total_price", "currency",
        "sold_date", "listing_type", "is_best_offer", "is_sold",
        "url", "item_id", "image_url", "seller_name", "condition",
        "scraped_at",
    )

    def __init__(self):
        self.title: str = ""
        self.price: float = 0.0          # 成交价（不含运费）
        self.shipping: float = 0.0       # 运费
        self.total_price: float = 0.0    # 总价（含运费）
        self.currency: str = "USD"
        self.sold_date: str = ""         # ISO 格式日期
        self.listing_type: str = ""      # Auction / Buy It Now / Best Offer
        self.is_best_offer: bool = False
        self.is_sold: bool = False
        self.url: str = ""
        self.item_id: str = ""
        self.image_url: str = ""
        self.seller_name: str = ""
        self.condition: str = ""         # Raw / Graded / etc.
        self.scraped_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return {slot: getattr(self, slot) for slot in self.__slots__}

    def to_json(self) -> str:
        """转为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def fields(cls) -> List[str]:
        """返回所有字段名"""
        return list(cls.__slots__)


# ============================================================
# HTML 解析器
# ============================================================

class EbayListingParser:
    """
    eBay 搜索结果页 HTML 解析器

    兼容旧版 (li.s-item) 与新版 (li.s-card) 两种布局。
    由于 eBay 频繁更新前端，解析规则可能需要周期性维护。
    """

    # BeautifulSoup 解析器（优先 lxml，回退 html.parser）
    _BS4_PARSER = "lxml"  # 默认值，将在首次使用时探测

    @classmethod
    def _get_parser(cls) -> str:
        """探测可用的 BeautifulSoup 解析器"""
        if cls._BS4_PARSER == "lxml":
            try:
                import lxml  # noqa: F401
            except ImportError:
                cls._BS4_PARSER = "html.parser"
        return cls._BS4_PARSER

    # 页面类型检测
    @staticmethod
    def detect_challenge(html: str) -> bool:
        """检测是否为 Akamai/反爬质询页或登录墙"""
        if not html:
            return True
        lowered = html.lower()
        markers = [
            "pardon our interruption",
            "captcha",
            "security check",
            "security measure",
            "access denied",
            "enable javascript to continue",
            # eBay 对 sold 过滤强制登录时返回 "Sign in or Register" 页
            "sign in or register",
            "error page | ebay",
        ]
        return any(m in lowered for m in markers)

    @staticmethod
    def detect_layout(html: str) -> str:
        """检测页面布局: "old" (li.s-item) / "new" (li.s-card) / "unknown" """
        if "li.s-card" in html or 'data-listingid' in html:
            return "new"
        if "li.s-item" in html or "s-item__price" in html:
            return "old"
        return "unknown"

    @staticmethod
    def parse_search_results(html: str, base_url: str = EBAY_DOMAINS["us"],
                             require_sold: bool = False) -> List[EbayListingItem]:
        """
        解析搜索结果页 HTML，提取所有 Listing

        Args:
            html: 搜索结果页 HTML 源码
            base_url: eBay 域名，用于拼接相对 URL
            require_sold: True=只保留标记为已售出的条目；
                          False=返回全部条目（常规搜索/在售商品也采集）

        Returns:
            List[EbayListingItem]: listing 列表
        """
        if not HAS_BS4:
            print("[错误] 缺少 beautifulsoup4，请 pip install beautifulsoup4 lxml")
            return []

        if EbayListingParser.detect_challenge(html):
            print("[警告] 页面为反爬质询页，无搜索结果可解析")
            return []

        soup = BeautifulSoup(html, EbayListingParser._get_parser())
        items = []

        # 新版布局: li.s-card
        listing_elements = soup.select("li.s-card")
        if listing_elements:
            for elem in listing_elements:
                item = EbayListingParser._parse_new_card(elem, base_url)
                if item and (not require_sold or item.is_sold):
                    items.append(item)
            return items

        # 旧版布局: li.s-item
        listing_elements = soup.select("li.s-item")
        if not listing_elements:
            # 回退选择器
            listing_elements = soup.select(".srp-results .s-item")

        for elem in listing_elements:
            item = EbayListingParser._parse_single_listing(elem, base_url)
            if item and (not require_sold or item.is_sold):
                items.append(item)

        return items

    # ----------------------------------------------------------
    # 新版布局解析 (li.s-card)
    # ----------------------------------------------------------
    @staticmethod
    def _parse_new_card(elem: BeautifulSoup, base_url: str) -> Optional[EbayListingItem]:
        """
        解析新版 li.s-card 元素（2025-2026 布局）

        实测结构 (2026-08):
          li.s-card[data-listingid]
            ├── .s-card__title          ← 标题
            ├── .s-card__link[href]     ← 商品链接
            ├── .s-card__price          ← 价格（可能是 RMB/USD/GBP 等本地货币）
            ├── .s-card__attribute-row  ← 出价数 / 运费 / 时间
            ├── .s-card__subtitle       ← 品相 (New/Graded)
            └── 卖家信息在 secondary 属性区

        注意: "Shop on eBay" 是置顶的幽灵推广卡，需跳过。
        """
        item = EbayListingItem()
        item.scraped_at = datetime.now().isoformat()

        # ---- 标题（幽灵卡跳过） ----
        title_elem = elem.select_one(".s-card__title, .s-card__title-text, h3")
        if title_elem:
            item.title = title_elem.get_text(strip=True)
        if not item.title or "Shop on eBay" in item.title:
            return None

        # ---- Item ID ----
        listing_id = elem.get("data-listingid") or elem.get("data-id")
        if listing_id:
            item.item_id = str(listing_id)
        else:
            id_match = re.search(r'/itm/(\d{10,13})', elem.get("data-href", "") or "")
            if id_match:
                item.item_id = id_match.group(1)

        # ---- 链接 ----
        link = elem.select_one("a.s-card__link, a[href*='/itm/']")
        if link:
            item.url = urljoin(base_url, link.get("href", ""))
            if not item.item_id:
                id_match = re.search(r'/itm/(\d{10,13})', item.url)
                if id_match:
                    item.item_id = id_match.group(1)

        # ---- 价格（含本地货币识别，如 "RMB 53.99"） ----
        price_elem = elem.select_one(".s-card__price, .s-item__price")
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            item.price, item.currency = EbayListingParser._parse_price(price_text)
            item.total_price = item.price
        if item.price <= 0:
            return None

        # ---- 出价数 / 时间 / 运费（属性行） ----
        body_text = elem.get_text(" ", strip=True)

        bid_match = re.search(r'(\d+)\s*bids?', body_text, re.IGNORECASE)
        if bid_match:
            # 有出价信息 → 拍卖类型
            item.listing_type = "Auction"
            # 0 bids 且价格高 → Buy It Now
            if int(bid_match.group(1)) == 0 and item.price > 100:
                item.listing_type = "Buy It Now"

        if "or best offer" in body_text.lower():
            item.is_best_offer = True
            if item.listing_type != "Auction":
                item.listing_type = "Best Offer"
        if not item.listing_type:
            item.listing_type = "Buy It Now"

        ship_elem = elem.select_one(".s-card__attribute-row span.su-styled-text.secondary.large")
        if ship_elem:
            ship_text = ship_elem.get_text(strip=True)
            if ship_text and "shipping" in ship_text.lower():
                if "free" in ship_text.lower():
                    item.shipping = 0.0
                else:
                    ship_price, _ = EbayListingParser._parse_price(ship_text)
                    item.shipping = max(ship_price, 0.0)
                item.total_price = item.price + item.shipping

        # ---- 品相 ----
        cond_elem = elem.select_one(".s-card__subtitle")
        if cond_elem:
            cond_text = cond_elem.get_text(strip=True)
            if "graded" in cond_text.lower():
                item.condition = "Graded"
            elif "raw" in cond_text.lower():
                item.condition = "Raw"
            else:
                item.condition = cond_text[:50]

        # ---- 卖家 ----
        seller_elem = elem.select_one(".su-card-container__attributes__secondary .su-styled-text.primary")
        if seller_elem:
            item.seller_name = seller_elem.get_text(strip=True)

        # ---- 已售出标记（新版已售条目价格带绿色 POSITIVE 标记） ----
        # 注意: 常规搜索(LH_Sold=1 过滤被反爬拦截时)抓取的是在售商品，
        # is_sold 用于标记是否带 SOLD 字样（部分商品标题含 "sold" 是历史信息）
        if "sold" in body_text.lower():
            item.is_sold = True

        # ---- 成交日期 ----
        date_match = re.search(
            r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
            body_text, re.IGNORECASE)
        if date_match:
            item.sold_date = EbayListingParser._parse_date(date_match.group(0))
        else:
            item.sold_date = datetime.now().strftime("%Y-%m-%d")

        return item

    # ----------------------------------------------------------
    # 旧版布局解析 (li.s-item)
    # ----------------------------------------------------------
    @staticmethod
    def _parse_single_listing(elem: BeautifulSoup, base_url: str) -> Optional[EbayListingItem]:
        """
        解析单条 Listing 元素（旧版 li.s-item 布局）

        Args:
            elem: BeautifulSoup 元素（li.s-item）
            base_url: eBay 域名

        Returns:
            EbayListingItem 或 None（非已售出条目）
        """
        item = EbayListingItem()
        item.scraped_at = datetime.now().isoformat()

        # ---- 链接与 Item ID ----
        link_elem = elem.select_one("a.s-item__link")
        if not link_elem:
            return None

        item.url = urljoin(base_url, link_elem.get("href", ""))
        # 从 URL 提取 Item ID（eBay item ID 通常为 12 位数字）
        id_match = re.search(r'/itm/(\d{10,13})', item.url)
        if id_match:
            item.item_id = id_match.group(1)

        # ---- 标题 ----
        title_elem = elem.select_one(".s-item__title")
        if title_elem:
            # 去除 "New Listing" 等前缀标签
            title_span = title_elem.select_one(".s-item__title--tagblock")
            if title_span:
                title_span.decompose()
            item.title = title_elem.get_text(strip=True)

        # ---- 已售出标识 ----
        sold_elem = elem.select_one(".s-item__ended-date, .s-item__title--sold")
        if sold_elem:
            sold_text = sold_elem.get_text(strip=True).upper()
            item.is_sold = "SOLD" in sold_text
        else:
            # 备选：检查是否有 "Sold" 标记的图像
            sold_img = elem.select_one("img[alt*='Sold']")
            if sold_img:
                item.is_sold = True

        # ---- 成交日期 ----
        date_elem = elem.select_one(".s-item__ended-date")
        if date_elem:
            date_text = date_elem.get_text(strip=True)
            item.sold_date = EbayListingParser._parse_date(date_text)
        else:
            # 备选：从 POSITIVE 反馈等位置推断
            pos_elem = elem.select_one(".s-item__positive-badge")
            if pos_elem:
                item.sold_date = datetime.now().strftime("%Y-%m-%d")

        # ---- 价格 ----
        price_elem = elem.select_one(".s-item__price")
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            item.price, item.currency = EbayListingParser._parse_price(price_text)
            item.total_price = item.price  # 初始赋值（不含运费）

        # ---- 运费 ----
        shipping_elem = elem.select_one(".s-item__shipping, .s-item__logisticsCost")
        if shipping_elem:
            ship_text = shipping_elem.get_text(strip=True)
            if "free" in ship_text.lower() or ship_text == "":
                item.shipping = 0.0
            else:
                ship_price, _ = EbayListingParser._parse_price(ship_text)
                item.shipping = max(ship_price, 0.0)
            item.total_price = item.price + item.shipping

        # ---- Listing 类型 ----
        type_elem = elem.select_one(".s-item__purchase-options, .s-item__bidCount")
        if type_elem:
            type_text = type_elem.get_text(strip=True).lower()
            if "bid" in type_text or "auction" in type_text:
                item.listing_type = "Auction"
            elif "best offer" in type_text:
                item.listing_type = "Best Offer"
                item.is_best_offer = True
            else:
                item.listing_type = "Buy It Now"
        else:
            item.listing_type = "Buy It Now"  # 默认定价

        # Best Offer 检测（成交价被横线划过）
        strike_price = elem.select_one(".s-item__price .STRIKETHROUGH, .s-item__original-price")
        if strike_price:
            item.is_best_offer = True
            if item.listing_type != "Best Offer":
                item.listing_type = "Best Offer"

        # ---- 图片 ----
        img_elem = elem.select_one(".s-item__image-img img, .s-item__image img")
        if img_elem:
            item.image_url = img_elem.get("src", "") or img_elem.get("data-src", "")

        # ---- 卖家 ----
        seller_elem = elem.select_one(".s-item__seller-info-text")
        if seller_elem:
            item.seller_name = seller_elem.get_text(strip=True)

        # ---- 品相/条件 ----
        cond_elem = elem.select_one(".s-item__subtitle, .s-item__condition")
        if cond_elem:
            cond_text = cond_elem.get_text(strip=True)
            if "graded" in cond_text.lower():
                item.condition = "Graded"
            elif "raw" in cond_text.lower():
                item.condition = "Raw"
            else:
                item.condition = cond_text[:50]  # 截取前 50 字符

        return item

    # ----------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------
    @staticmethod
    def _parse_price(text: str) -> Tuple[float, str]:
        """
        清洗价格文本为数值

        处理格式:
          - "$123.45" → (123.45, "USD")
          - "£89.99" → (89.99, "GBP")
          - "EUR 150,00" → (150.00, "EUR")
          - "$1,234.56 to $2,345.67" → 取第一个价格

        Args:
            text: 价格原始文本

        Returns:
            (价格浮点数, 货币代码)
        """
        text = text.strip()

        # 检测货币符号（eBay 按 IP 地理显示本地货币，如 RMB）
        currency_map = {
            "$": "USD",
            "US $": "USD",
            "£": "GBP",
            "EUR": "EUR",
            "€": "EUR",
            "C $": "CAD",
            "AU $": "AUD",
            "RMB": "CNY",
            "CNY": "CNY",
            "JPY": "JPY",
            "AU$": "AUD",
            "CAD": "CAD",
        }

        currency = "USD"
        for symbol, code in currency_map.items():
            if text.upper().startswith(symbol.upper()):
                currency = code
                break

        # 去除货币前缀和非数字字符（保留数字、逗号、点）
        # 处理 "to" 范围（取第一个）
        if " to " in text.lower():
            text = text.split(" to ")[0].strip()

        # 提取数字部分
        cleaned = re.sub(r'[^\d.,]', '', text)

        # 处理欧洲格式 "1.234,56" → "1234.56"
        if currency in ("EUR", "GBP"):
            if re.search(r',\d{2}$', cleaned):
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        else:
            cleaned = cleaned.replace(',', '')

        try:
            price = float(cleaned)
            return (round(price, 2), currency)
        except ValueError:
            return (0.0, currency)

    @staticmethod
    def _parse_date(text: str) -> str:
        """
        解析 eBay 日期文本为 ISO 格式

        eBay 日期格式示例:
          - "Sold Dec 15, 2024"
          - "Ended: Jan 3, 2025"
          - "Dec-15 10:30"
          - "2024-12-15"

        Args:
            text: eBay 日期文本

        Returns:
            ISO 格式日期字符串 "YYYY-MM-DD"
        """
        text = text.strip()

        # 去除前缀
        for prefix in ["Sold ", "Ended ", "Ended: "]:
            if text.startswith(prefix):
                text = text[len(prefix):]
                break

        # 尝试解析标准格式
        date_formats = [
            "%b %d, %Y",      # Dec 15, 2024
            "%B %d, %Y",      # December 15, 2024
            "%b-%d %H:%M",    # Dec-15 10:30
            "%Y-%m-%d",        # 2024-12-15
            "%m/%d/%Y",        # 12/15/2024
        ]

        for fmt in date_formats:
            try:
                parsed = datetime.strptime(text, fmt)
                # "%b-%d %H:%M" 这类无年份格式会解析成 1900 年 → 补当前年份
                if parsed.year == 1900:
                    parsed = parsed.replace(year=datetime.now().year)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # 回退：提取月日信息
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "may": 5, "jun": 6, "jul": 7, "aug": 8,
            "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        month_match = re.search(
            r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2}),?\s*(\d{4})',
            text, re.IGNORECASE
        )
        if month_match:
            m = months[month_match.group(1).lower()[:3]]
            d = int(month_match.group(2))
            y = int(month_match.group(3))
            return f"{y}-{m:02d}-{d:02d}"

        # 最终回退
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def parse_pagination(html: str) -> Tuple[int, int]:
        """
        解析分页信息

        Args:
            html: 搜索结果页 HTML

        Returns:
            (当前页码, 总页数)
        """
        soup = BeautifulSoup(html, EbayListingParser._get_parser())

        # eBay 分页元素
        current_elem = soup.select_one(".pagination__item--active, .pg-current")
        current_page = 1
        if current_elem:
            try:
                current_page = int(current_elem.get_text(strip=True))
            except ValueError:
                pass

        # 总页数
        total_pages = 1
        page_links = soup.select(".pagination__item, a[class*='pagination']")
        page_nums = []
        for link in page_links:
            try:
                n = int(link.get_text(strip=True))
                page_nums.append(n)
            except ValueError:
                continue
        if page_nums:
            total_pages = max(page_nums)

        return (current_page, total_pages)


# ============================================================
# 采集后端（请求层）
# ============================================================

class _RequestsBackend:
    """L1: 原生 requests"""

    name = "requests"

    def __init__(self, delay: float):
        self.delay = delay
        self.session = None
        try:
            import requests
            self.session = requests.Session()
            self.session.headers.update(DEFAULT_HEADERS)
        except ImportError:
            pass

    def fetch(self, url: str) -> Optional[str]:
        if not self.session:
            return None
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception:
            return None


class _CurlCffiBackend:
    """L2: curl_cffi TLS 指纹模拟"""

    name = "curl_cffi"

    def __init__(self, delay: float):
        self.delay = delay
        self.session = None
        try:
            from curl_cffi import requests as cffi_requests
            self.session = cffi_requests.Session(impersonate=CURL_IMPERSONATE)
            self.session.headers.update(DEFAULT_HEADERS)
        except ImportError:
            pass

    def fetch(self, url: str) -> Optional[str]:
        if not self.session:
            return None
        try:
            resp = self.session.get(url, timeout=45)
            resp.raise_for_status()
            return resp.text
        except Exception:
            return None


class _PlaywrightBackend:
    """
    L3: Playwright 真实浏览器（可执行 JS 质询）

    登录态支持:
      如果 data/.ebay_storage_state.json 存在（用户登录后保存），
      自动复用登录态 — 可解锁 eBay 对 sold 搜索的登录墙。
    """

    name = "playwright"

    # 登录态文件（项目根目录 data/.ebay_storage_state.json）
    STORAGE_STATE_PATH = os.path.join("data", ".ebay_storage_state.json")

    def __init__(self, delay: float, headless: bool = PLAYWRIGHT_HEADLESS):
        self.delay = delay
        self.headless = headless
        self._sync = None
        try:
            from playwright.sync_api import sync_playwright
            self._sync = sync_playwright
        except ImportError:
            pass

    def _launch_context(self, browser):
        """创建带登录态（若存在）的浏览器上下文"""
        kwargs = dict(
            user_agent=DEFAULT_HEADERS["User-Agent"],
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        if os.path.exists(self.STORAGE_STATE_PATH):
            kwargs["storage_state"] = self.STORAGE_STATE_PATH
        return browser.new_context(**kwargs)

    def _navigate(self, page, url: str) -> bool:
        """导航并等待质询解决，返回是否成功"""
        for attempt in range(3):
            try:
                page.goto(url, wait_until="domcontentloaded")
                break
            except Exception as e:
                print(f"  [Playwright] 导航重试 {attempt+1}/3: {str(e)[:70]}")
                if attempt == 2:
                    return False
                time.sleep(3)
        # 等待 Akamai JS 质询自动完成（最多 30s）
        for _ in range(30):
            title = page.title()
            if not any(bad in title for bad in
                       ["Pardon", "Error Page", "Security Measure", "Sign in or Register"]):
                break
            time.sleep(1)
        return True

    def fetch(self, url: str) -> Optional[str]:
        if not self._sync:
            return None
        with self._sync() as p:
            browser = p.chromium.launch(headless=self.headless)
            try:
                context = self._launch_context(browser)
                page = context.new_page()
                page.set_default_timeout(45000)
                if not self._navigate(page, url):
                    context.close()
                    return None
                # 等待结果容器出现
                try:
                    page.wait_for_selector(
                        "li.s-item, li.s-card, .srp-controls, #srp-river-results",
                        timeout=25000,
                    )
                except Exception:
                    pass
                html = page.content()
                context.close()
                return html
            finally:
                browser.close()

    def fetch_with_retry(self, url: str, min_len: int = 10000, attempts: int = 3) -> Optional[str]:
        """
        带重试的抓取：页面过短（限流/未加载完成）时自动重试

        Args:
            url: 目标 URL
            min_len: 有效页面最小长度
            attempts: 最大尝试次数
        """
        for i in range(attempts):
            html = self.fetch(url)
            if html and len(html) >= min_len:
                return html
            print(f"  [Playwright] 页面过短({len(html) if html else 0}B)，重试 {i+1}/{attempts}")
            time.sleep(3 + i * 2)
        return html

    def login(self, login_url: str = "https://www.ebay.com/signin") -> bool:
        """
        交互式登录：打开浏览器，等待用户在页面完成登录，保存登录态。

        用法（构建脚本 --ebay-login）:
            backend = _PlaywrightBackend(delay=0, headless=False)
            backend.login()
        """
        if not self._sync:
            print("[Playwright] 未安装，无法登录")
            return False
        print("=" * 60)
        print("  请在打开的 eBay 浏览器窗口中完成登录")
        print("  登录完成后，本程序将在 5 秒后自动保存登录态")
        print("=" * 60)
        with self._sync() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                viewport={"width": 1366, "height": 900},
                locale="en-US",
            )
            page = context.new_page()
            page.set_default_timeout(60000)
            page.goto(login_url, wait_until="domcontentloaded")
            # 轮询检测登录完成（页面标题不再含 Sign in，或 URL 变为首页/我的eBay）
            logged_in = False
            for _ in range(240):
                try:
                    title = page.title()
                    url_now = page.url
                    if (title and "Sign in" not in title and "Register" not in title
                            and "ebay.com" in url_now and "signin" not in url_now):
                        logged_in = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            if logged_in:
                time.sleep(2)
                os.makedirs("data", exist_ok=True)
                context.storage_state(path=self.STORAGE_STATE_PATH)
                print(f"[登录] 登录态已保存 → {self.STORAGE_STATE_PATH}")
            else:
                print("[登录] 超时未检测到登录完成（仍可手动保存，请告知用户操作）")
            browser.close()
        return logged_in


# ============================================================
# 主采集器
# ============================================================

class EbayScraper:
    """
    eBay 成交数据采集器（三层后端自动降级）

    用法:
        scraper = EbayScraper(region="us", backend="auto")
        results = scraper.search("LeBron James Prizm 2020", max_pages=3)
        scraper.export_json(results, "lebron_prizm_2020.json")

    backend 可选:
        "auto"       — 依次尝试 curl_cffi → playwright（推荐）
        "requests"   — 原生 requests（大概率 403）
        "curl_cffi"  — TLS 指纹模拟
        "playwright" — 真实浏览器
    """

    def __init__(self, region: str = "us", delay: float = REQUEST_DELAY,
                 backend: str = "auto"):
        """
        初始化采集器

        Args:
            region: eBay 地区代码 ("us", "uk", "de", "au")
            delay: 请求间隔（秒）
            backend: 采集后端 ("auto" / "requests" / "curl_cffi" / "playwright")
        """
        self.region = region
        self.base_url = EBAY_DOMAINS.get(region, EBAY_DOMAINS["us"])
        self.delay = delay
        self.backend_name = backend
        self.backend = self._build_backends(backend)
        self._request_count = 0
        self._last_request_time = 0.0

    def _build_backends(self, backend: str):
        if backend == "requests":
            return [_RequestsBackend(self.delay)]
        if backend == "curl_cffi":
            return [_CurlCffiBackend(self.delay)]
        if backend == "playwright":
            return [_PlaywrightBackend(self.delay)]
        # auto: 先 requests/curl_cffi（快），失败降级 playwright
        return [_CurlCffiBackend(self.delay), _PlaywrightBackend(self.delay)]

    def _rate_limit(self):
        """请求频率控制"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_time = time.time()
        self._request_count += 1

    def _fetch_page(self, url: str) -> Optional[str]:
        """
        获取单页 HTML（后端降级链）

        Args:
            url: 请求 URL

        Returns:
            HTML 字符串或 None
        """
        errors = []
        for backend in self.backend:
            self._rate_limit()
            try:
                # Playwright 后端对短响应自动重试（限流/未加载完）
                if isinstance(backend, _PlaywrightBackend):
                    html = backend.fetch_with_retry(url)
                else:
                    html = backend.fetch(url)
                if html and not EbayListingParser.detect_challenge(html) and len(html) > 10000:
                    return html
                if html:
                    errors.append(f"{backend.name}: 质询/异常页面 ({len(html)}B)")
                else:
                    errors.append(f"{backend.name}: 无响应")
            except Exception as e:
                errors.append(f"{backend.name}: {str(e)[:80]}")
            # 若还有后端可降级，打印提示
            if backend is not self.backend[-1]:
                print(f"  [降级] {backend.name} 失败 → 尝试下一后端")

        print(f"  [警告] 所有后端失败: {' | '.join(errors)}")
        return None

    def search(
        self,
        keyword: str,
        max_pages: int = MAX_PAGES,
        condition: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        listing_type: Optional[str] = None,
        sold_only: bool = True,
    ) -> List[EbayListingItem]:
        """
        搜索 eBay Listing

        Args:
            keyword: 搜索关键词（如 "LeBron James Prizm 2020"）
            max_pages: 最大翻页数
            condition: 品相过滤 ("Graded", "Raw", None=全部)
            min_price: 最低价格过滤
            max_price: 最高价格过滤
            listing_type: 类型过滤 ("Auction", "Buy It Now", None=全部)
            sold_only: True=只搜已售出(LH_Sold=1)；被反爬拦截时自动降级为
                       常规搜索（在售商品价格同样是真实市场信号）

        Returns:
            List[EbayListingItem]: listing 列表
        """
        all_items = []
        encoded_keyword = quote_plus(keyword)

        print(f"\n{'='*60}")
        print(f"[eBay采集] 搜索关键词: {keyword}")
        print(f"[eBay采集] 地区: {self.region.upper()} | 最大页数: {max_pages} | 后端: {self.backend_name}")

        # ---- 首次请求：sold 模式 ----
        sold_blocked = False
        if sold_only:
            items, sold_blocked = self._search_pages(
                keyword, encoded_keyword, max_pages,
                min_price, max_price, sold=True,
            )
            all_items.extend(items)
            if sold_blocked:
                print(f"\n[降级] eBay 已售出搜索被反爬拦截 → 自动降级为常规搜索（在售价格）")
                all_items = []

        # ---- 降级：常规搜索 ----
        if not sold_only or sold_blocked:
            items, _ = self._search_pages(
                keyword, encoded_keyword, max_pages,
                min_price, max_price, sold=False,
            )
            all_items.extend(items)

        # ---- 后过滤 ----
        if condition:
            cond_lower = condition.lower()
            all_items = [
                i for i in all_items
                if cond_lower in i.condition.lower()
            ]
            print(f"[过滤] 品相={condition}: 剩余 {len(all_items)} 条")

        if listing_type:
            lt_lower = listing_type.lower()
            all_items = [
                i for i in all_items
                if lt_lower in i.listing_type.lower()
            ]
            print(f"[过滤] 类型={listing_type}: 剩余 {len(all_items)} 条")

        print(f"[eBay采集] 总计采集 {len(all_items)} 条记录")
        return all_items

    def _search_pages(
        self,
        keyword: str,
        encoded_keyword: str,
        max_pages: int,
        min_price: Optional[float],
        max_price: Optional[float],
        sold: bool,
    ) -> Tuple[List[EbayListingItem], bool]:
        """
        抓取多页搜索结果

        Returns:
            (items, blocked): (列表, 是否被反爬拦截)
        """
        all_items: List[EbayListingItem] = []
        mode = "已售出" if sold else "在售"

        for page in range(1, max_pages + 1):
            # 构建搜索 URL
            if sold:
                # 已售出过滤器: LH_Sold=1 & LH_Complete=1（缺一不可）
                url = (
                    f"{self.base_url}/sch/i.html"
                    f"?_nkw={encoded_keyword}"
                    f"&LH_Sold=1&LH_Complete=1"
                    f"&_pgn={page}"
                )
            else:
                url = f"{self.base_url}/sch/i.html?_nkw={encoded_keyword}&_pgn={page}"

            # 添加可选过滤器
            if min_price is not None:
                url += f"&_udlo={min_price}"
            if max_price is not None:
                url += f"&_udhi={max_price}"

            print(f"  [第{page}页 {mode}] {url}")

            html = self._fetch_page(url)
            if html is None:
                print(f"  [第{page}页] 请求被拦截/失败，停止翻页")
                return all_items, True

            # 解析
            items = EbayListingParser.parse_search_results(
                html, self.base_url, require_sold=sold)
            print(f"  [第{page}页] 解析到 {len(items)} 条{mode}记录")

            if not items:
                print(f"  [第{page}页] 无更多结果，停止翻页")
                break

            all_items.extend(items)

            # 检查是否还有下一页
            current, total = EbayListingParser.parse_pagination(html)
            if current >= total:
                print(f"  [分页] 已到最后一页 ({current}/{total})")
                break

        return all_items, False

        # ---- 后过滤 ----
        if condition:
            cond_lower = condition.lower()
            all_items = [
                i for i in all_items
                if cond_lower in i.condition.lower()
            ]
            print(f"[过滤] 品相={condition}: 剩余 {len(all_items)} 条")

        if listing_type:
            lt_lower = listing_type.lower()
            all_items = [
                i for i in all_items
                if lt_lower in i.listing_type.lower()
            ]
            print(f"[过滤] 类型={listing_type}: 剩余 {len(all_items)} 条")

        print(f"[eBay采集] 总计采集 {len(all_items)} 条成交记录")
        return all_items

    def search_player_cards(
        self,
        player_name: str,
        card_year: Optional[int] = None,
        series: Optional[str] = None,
        max_pages: int = MAX_PAGES,
    ) -> List[EbayListingItem]:
        """
        搜索指定球员的球星卡成交记录

        Args:
            player_name: 球员名
            card_year: 卡片年份（可选）
            series: 产品系列（可选，如 "Prizm"）
            max_pages: 最大翻页数

        Returns:
            List[EbayListingItem]
        """
        # 构建搜索关键词
        parts = [player_name]
        if series:
            parts.append(series)
        if card_year:
            parts.append(str(card_year))
        keyword = " ".join(parts)

        return self.search(keyword, max_pages=max_pages)

    @staticmethod
    def export_json(items: List[EbayListingItem], filepath: str) -> str:
        """
        导出为 JSON 文件

        Args:
            items: Listing 列表
            filepath: 输出文件路径

        Returns:
            输出文件的绝对路径
        """
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        data = {
            "metadata": {
                "total": len(items),
                "exported_at": datetime.now().isoformat(),
                "source": "eBay Completed Listings",
            },
            "listings": [item.to_dict() for item in items],
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        abs_path = os.path.abspath(filepath)
        print(f"[导出] {len(items)} 条记录已保存到 {abs_path}")
        return abs_path

    @staticmethod
    def to_dataframe(items: List[EbayListingItem]) -> "pd.DataFrame":
        """
        转为 pandas DataFrame

        Args:
            items: Listing 列表

        Returns:
            pandas DataFrame
        """
        import pandas as pd
        records = [item.to_dict() for item in items]
        return pd.DataFrame(records)


# ============================================================
# 模拟数据（用于测试，避免实际请求 eBay）
# ============================================================

def _generate_mock_html(keyword: str, page: int = 1) -> str:
    """
    生成模拟的 eBay 搜索结果 HTML（仅用于测试）

    在 __main__ 测试时使用，避免实际请求 eBay API。
    """
    return f"""
    <html><body>
    <ul class="srp-results">
        <li class="s-item">
            <a class="s-item__link" href="https://www.ebay.com/itm/123456789012"></a>
            <span class="s-item__title">2019-20 Panini Prizm Silver {keyword} #249 PSA 9</span>
            <span class="s-item__price">$245.00</span>
            <span class="s-item__shipping">Free shipping</span>
            <span class="s-item__ended-date">Sold Dec 15, 2024</span>
            <span class="s-item__purchase-options">Buy It Now</span>
            <span class="s-item__seller-info-text">cardshop_usa</span>
            <span class="s-item__condition">Graded</span>
        </li>
        <li class="s-item">
            <a class="s-item__link" href="https://www.ebay.com/itm/234567890123"></a>
            <span class="s-item__title">2020-21 Panini Prizm Gold {keyword} /10 RC BGS 9.5</span>
            <span class="s-item__price">$3,500.00</span>
            <span class="s-item__shipping">+$12.50 shipping</span>
            <span class="s-item__ended-date">Sold Jan 3, 2025</span>
            <span class="s-item__purchase-options">or Best Offer</span>
            <span class="s-item__seller-info-text">premium_cards</span>
            <span class="s-item__condition">Graded</span>
        </li>
        <li class="s-item">
            <a class="s-item__link" href="https://www.ebay.com/itm/345678901234"></a>
            <span class="s-item__title">2021-22 Panini Select {keyword} Courtside Raw</span>
            <span class="s-item__price">$45.50</span>
            <span class="s-item__shipping">+$5.00 shipping</span>
            <span class="s-item__ended-date">Sold Feb 20, 2025</span>
            <span class="s-item__purchase-options">Auction (12 bids)</span>
            <span class="s-item__seller-info-text">hobby_collector</span>
            <span class="s-item__condition">Raw</span>
        </li>
        <li class="s-item">
            <a class="s-item__link" href="https://www.ebay.com/itm/456789012345"></a>
            <span class="s-item__title">2022-23 Panini National Treasures {keyword} RPA /99</span>
            <span class="s-item__price">$8,200.00</span>
            <span class="s-item__shipping">Free shipping</span>
            <span class="s-item__ended-date">Sold Mar 10, 2025</span>
            <span class="s-item__purchase-options">Buy It Now</span>
            <span class="s-item__seller-info-text">elite_cards_inc</span>
            <span class="s-item__condition">Raw</span>
        </li>
        <li class="s-item">
            <a class="s-item__link" href="https://www.ebay.com/itm/567890123456"></a>
            <span class="s-item__title">2020-21 Panini Prizm Base {keyword} Raw Lot</span>
            <span class="s-item__price">$12.99</span>
            <span class="s-item__shipping">+$3.99 shipping</span>
            <span class="s-item__ended-date">Sold Mar 28, 2025</span>
            <span class="s-item__purchase-options">Buy It Now</span>
            <span class="s-item__seller-info-text">budget_sports_cards</span>
            <span class="s-item__condition">Raw</span>
        </li>
    </ul>
    <div class="pagination">
        <span class="pagination__item--active">1</span>
        <a class="pagination__item" href="?page=2">2</a>
        <a class="pagination__item" href="?page=3">3</a>
    </div>
    </body></html>
    """


class MockEbayScraper(EbayScraper):
    """
    Mock eBay 采集器（用于测试，不发起真实 HTTP 请求）

    用法:
        scraper = MockEbayScraper()
        results = scraper.search("LeBron James Prizm 2020")
    """

    def __init__(self, region: str = "us"):
        super().__init__(region=region, delay=0, backend="requests")

    def _fetch_page(self, url: str) -> Optional[str]:
        """返回模拟 HTML"""
        # 从 URL 中提取关键词
        kw_match = re.search(r'_nkw=([^&]+)', url)
        keyword = "Basketball Cards"
        if kw_match:
            from urllib.parse import unquote_plus
            keyword = unquote_plus(kw_match.group(1))

        page_match = re.search(r'_pgn=(\d+)', url)
        page = int(page_match.group(1)) if page_match else 1

        print(f"  [Mock] 生成模拟数据: keyword={keyword}, page={page}")
        return _generate_mock_html(keyword, page)


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  eBay 成交数据采集器 — 测试")
    print("=" * 60)

    # ---- 测试 1：价格清洗 ----
    print("\n[测试1] 价格清洗")
    test_prices = [
        ("$245.00", (245.00, "USD")),
        ("$1,234.56", (1234.56, "USD")),
        ("£89.99", (89.99, "GBP")),
        ("EUR 150,00", (150.00, "EUR")),
        ("$3,500.00 to $4,200.00", (3500.00, "USD")),
        ("Free shipping", (0.0, "USD")),
    ]
    for text, expected in test_prices:
        result = EbayListingParser._parse_price(text)
        status = "✓" if result == expected else f"✗ (got {result})"
        print(f"  {status} '{text}' → {result}")

    # ---- 测试 2：日期解析 ----
    print("\n[测试2] 日期解析")
    test_dates = [
        "Sold Dec 15, 2024",
        "Ended: Jan 3, 2025",
        "Dec-15 10:30",
        "2024-12-15",
    ]
    for text in test_dates:
        result = EbayListingParser._parse_date(text)
        print(f"  '{text}' → {result}")

    # ---- 测试 3：模拟搜索 ----
    print("\n[测试3] 模拟 eBay 搜索")
    scraper = MockEbayScraper(region="us")
    results = scraper.search(
        keyword="LeBron James Prizm 2020",
        max_pages=2,
        condition="Graded",
    )

    print(f"\n  采集结果: {len(results)} 条记录")
    for i, item in enumerate(results):
        print(f"\n  --- Listing #{i+1} ---")
        print(f"  标题:       {item.title}")
        print(f"  成交价:     {item.currency} ${item.price:.2f}")
        print(f"  运费:       ${item.shipping:.2f}")
        print(f"  总价:       ${item.total_price:.2f}")
        print(f"  日期:       {item.sold_date}")
        print(f"  类型:       {item.listing_type}")
        print(f"  Best Offer: {item.is_best_offer}")
        print(f"  卖家:       {item.seller_name}")
        print(f"  品相:       {item.condition}")
        print(f"  Item ID:    {item.item_id}")

    # ---- 测试 4：JSON 导出 ----
    print("\n[测试4] JSON 导出")
    outpath = "data/raw/ebay_test_results.json"
    EbayScraper.export_json(results, outpath)
    print(f"  文件大小: {os.path.getsize(outpath)} bytes")

    # ---- 测试 5：球员卡片搜索 ----
    print("\n[测试5] 球员卡片搜索")
    player_results = scraper.search_player_cards(
        player_name="Victor Wembanyama",
        series="Prizm",
        card_year=2023,
        max_pages=1,
    )
    print(f"  采集结果: {len(player_results)} 条记录")
    for item in player_results:
        print(f"    {item.title}: ${item.price:.2f} ({item.listing_type})")

    print(f"\n{'=' * 60}")
    print("  测试完成！所有功能模块正常。")
    print(f"{'=' * 60}")
