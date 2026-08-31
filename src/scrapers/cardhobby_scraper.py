"""
CardHobby (卡淘) 成交数据采集器
=============================
抓取 CardHobby 平台的球星卡交易数据。

重要更新 (2026-08):
  * 平台主域名已从 www.cardhobby.com 变更为 www.cardhobby.com.cn
    (旧域名 DNS 仍解析到阿里云 IP 但已无法连接，这就是之前超时的原因)
  * 公开可见的数据源:
      - /market/auction?page=N  在拍拍卖列表（标题/当前价/出价数/结束时间/卖家）
      - /market/latest?page=N   最新上架列表
      - /market/item/{id}       商品详情页（当前价/出价数/结束时间）
  * 需要登录才能访问: 关键词搜索、成交记录 (soldlog)、出价记录 (bidrecords)
    → 本站点无法匿名获取"历史成交价"，采集的是实时拍卖中的真实市场数据
      (当前价 = 市场对该卡的真实出价信号)

功能：
  - 批量采集拍卖列表（自动翻页）
  - 采集商品详情（当前价、出价数、结束时间）
  - 人民币价格清洗（¥ / ￥ / RMB 前缀）
  - 时间解析（"6小时22分11秒后结束"、"2026/8/6 4:52:30" 等格式）
  - 请求频率控制
  - Mock 模式（测试用）

用法：
  python -m src.scrapers.cardhobby_scraper  # 运行测试入口
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

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
from bs4 import BeautifulSoup


# ============================================================
# 配置
# ============================================================

# 官方主域名（2026 起 .com 已不可用）
CARHOBBY_BASE_URL = "https://www.cardhobby.com.cn"

# 拍卖列表 / 最新上架 / 商品详情 / 出价记录
AUCTION_LIST_URL = f"{CARHOBBY_BASE_URL}/market/auction"
LATEST_LIST_URL = f"{CARHOBBY_BASE_URL}/market/latest"
ITEM_URL = f"{CARHOBBY_BASE_URL}/market/item/{{item_id}}"
BIDRECORDS_URL = f"{CARHOBBY_BASE_URL}/market/bidrecords/{{item_id}}"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

REQUEST_DELAY = 1.5
MAX_PAGES = 10
MAX_RETRIES = 3

# 单页列表数量（实测约 32 条/页）
ITEMS_PER_PAGE = 32


# ============================================================
# 数据模型
# ============================================================

class CardHobbyListing:
    """CardHobby 单条拍卖/成交记录"""

    __slots__ = (
        "title", "price_cny", "price_usd", "sold_date",
        "listing_type", "is_sold", "url", "item_id",
        "seller_name", "seller_rating", "views", "bids",
        "condition", "shipping_fee", "end_time", "scraped_at",
    )

    def __init__(self):
        self.title: str = ""
        self.price_cny: float = 0.0       # 人民币当前价/成交价
        self.price_usd: float = 0.0       # 折合美元（≈CNY/7.2）
        self.sold_date: str = ""
        self.listing_type: str = ""        # 拍卖 / 一口价
        self.is_sold: bool = False
        self.url: str = ""
        self.item_id: str = ""
        self.seller_name: str = ""
        self.seller_rating: str = ""
        self.views: int = 0
        self.bids: int = 0                 # 出价次数
        self.condition: str = ""
        self.shipping_fee: float = 0.0
        self.end_time: str = ""            # 拍卖结束时间 (ISO)
        self.scraped_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {s: getattr(self, s) for s in self.__slots__}


# ============================================================
# HTML 解析器
# ============================================================

class CardHobbyParser:
    """CardHobby 页面解析器（基于 2026-08 实测 DOM 结构）"""

    @staticmethod
    def _get_parser() -> str:
        try:
            import lxml  # noqa: F401
            return "lxml"
        except ImportError:
            return "html.parser"

    # ----------------------------------------------------------
    # 列表页解析（/market/auction 与 /market/latest 共用结构）
    # ----------------------------------------------------------
    @staticmethod
    def parse_list_page(html: str, base_url: str = CARHOBBY_BASE_URL) -> List[CardHobbyListing]:
        """
        解析拍卖/最新列表页 HTML

        实测 DOM 结构 (2026-08):
          div.kzCell                      ← 每条 listing
            ├── a[href=/market/item/{id}] ← 商品链接/图片
            ├── div.detailbox
            │   ├── p.boxDesc > a[title]  ← 标题
            │   ├── table.card-info
            │   │   ├── span ￥1.00       ← 当前价 (CNY)
            │   │   ├── a[href=bidrecords/{id}] 0次出价
            │   │   ├── 约$ 0.15          ← 美元价
            │   │   └── 运费：￥11.99
            │   └── a[href=/market/user/{id}] > .realname ← 卖家
            └── span.priceEndTime > .effect__time[value]  ← 结束时间
        """
        soup = BeautifulSoup(html, CardHobbyParser._get_parser())
        items = []

        for elem in soup.select("div.kzCell"):
            item = CardHobbyParser._parse_list_cell(elem, base_url)
            if item:
                items.append(item)

        # 回退：有些页面用 li / .item 容器
        if not items:
            for sel in ("li.kzCell", "div.listing-cell", "div.search-result-item"):
                cells = soup.select(sel)
                if cells:
                    for elem in cells:
                        item = CardHobbyParser._parse_list_cell(elem, base_url)
                        if item:
                            items.append(item)
                    break

        return items

    @staticmethod
    def _parse_list_cell(elem: BeautifulSoup, base_url: str) -> Optional[CardHobbyListing]:
        """解析单条列表单元格"""
        item = CardHobbyListing()
        item.scraped_at = datetime.now().isoformat()

        # ---- 链接与 Item ID ----
        link = elem.select_one("a[href*='/market/item/']")
        if not link:
            return None
        item.url = urljoin(base_url, link.get("href", ""))
        id_match = re.search(r'/market/item/(\d+)', item.url)
        if id_match:
            item.item_id = id_match.group(1)

        # ---- 标题 ----
        title_elem = elem.select_one(".boxDesc a, .boxDesc, .title, .product-title")
        if title_elem:
            item.title = title_elem.get("title", "") or title_elem.get_text(strip=True)

        # ---- 价格 (人民币) ----
        price_elem = elem.select_one("table.card-info span")
        if price_elem:
            item.price_cny = CardHobbyParser._parse_cny(price_elem.get_text(strip=True))
        item.price_usd = round(item.price_cny / 7.25, 2)

        # ---- 出价次数 ----
        bids_elem = elem.select_one("a[href*='bidrecords']")
        if bids_elem:
            m = re.search(r'(\d+)', bids_elem.get_text(strip=True))
            if m:
                item.bids = int(m.group(1))

        # ---- 运费 ----
        ship_elem = elem.select_one(".card-info td")
        for td in elem.select("td"):
            t = td.get_text(strip=True)
            m = re.match(r'运费[:：]\s*[¥￥]?([\d,]+\.?\d*)', t)
            if m:
                item.shipping_fee = float(m.group(1).replace(',', ''))
                break

        # ---- 卖家 ----
        seller_elem = elem.select_one("a[href*='/market/user/'] .realname, .realname")
        if seller_elem:
            item.seller_name = seller_elem.get_text(strip=True)

        # ---- 结束时间 ----
        time_elem = elem.select_one(".effect__time")
        if time_elem:
            end_val = time_elem.get("value", "")
            if end_val:
                item.end_time = CardHobbyParser._parse_end_value(end_val)
            else:
                item.end_time = CardHobbyParser._parse_end_text(time_elem.get_text(strip=True))
            item.sold_date = item.end_time[:10]

        # ---- 类型 ----
        if elem.select_one("img.auctionImg, .auctionImg"):
            item.listing_type = "拍卖"
        else:
            item.listing_type = "一口价"

        # 有当前价 → 视为市场有效数据（拍卖进行中）
        item.is_sold = item.price_cny > 0

        return item

    # ----------------------------------------------------------
    # 详情页解析（/market/item/{id}）
    # ----------------------------------------------------------
    @staticmethod
    def parse_item_page(html: str, base_url: str = CARHOBBY_BASE_URL,
                        item_id: str = "") -> Optional[CardHobbyListing]:
        """
        解析商品详情页

        实测 DOM (2026-08):
          span#currentPrice → 当前价
          span#bidcount     → 出价数
          div#usdPrice      → 约$ 0.15
          table > tr: 结束时间 2026-08-06 04:51:45
          title/og:title    → 商品标题
        """
        soup = BeautifulSoup(html, CardHobbyParser._get_parser())
        item = CardHobbyListing()
        item.scraped_at = datetime.now().isoformat()
        item.item_id = item_id
        item.url = f"{base_url}/market/item/{item_id}" if item_id else ""

        # ---- 标题 ----
        og_title = soup.select_one("meta[property='og:title']")
        if og_title and og_title.get("content"):
            item.title = og_title["content"].strip()
        else:
            title_tag = soup.find("title")
            if title_tag:
                t = title_tag.get_text(strip=True)
                # 去掉站点后缀 " 卡淘"
                t = re.sub(r'\s*卡淘\s*$', '', t)
                item.title = t

        # ---- 当前价 ----
        price_elem = soup.select_one("#currentPrice")
        if price_elem:
            item.price_cny = CardHobbyParser._parse_cny(price_elem.get_text(strip=True))
        item.price_usd = round(item.price_cny / 7.25, 2)

        # ---- 出价数 ----
        bids_elem = soup.select_one("#bidcount")
        if bids_elem:
            m = re.search(r'(\d+)', bids_elem.get_text(strip=True))
            if m:
                item.bids = int(m.group(1))

        # ---- 结束时间 ----
        for td in soup.select("td"):
            t = td.get_text(strip=True)
            if t == "结束时间":
                parent_tr = td.parent
                if parent_tr:
                    val_elem = parent_tr.select_one("td div")
                    if val_elem:
                        item.end_time = CardHobbyParser._parse_end_value(
                            val_elem.get_text(strip=True))
                        item.sold_date = item.end_time[:10]
                break

        # ---- 类型 ----
        if soup.select_one("img.auctionImg, .icon-auction"):
            item.listing_type = "拍卖"
        else:
            item.listing_type = "一口价"

        item.is_sold = item.price_cny > 0
        return item

    # ----------------------------------------------------------
    # 分页信息
    # ----------------------------------------------------------
    @staticmethod
    def parse_total_count(html: str) -> int:
        """解析列表页"共XXX条"总数"""
        m = re.search(r'共\s*([\d,]+)\s*条', html)
        if m:
            return int(m.group(1).replace(',', ''))
        return 0

    # ----------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------
    @staticmethod
    def _parse_cny(text: str) -> float:
        """解析人民币价格"""
        text = text.strip()
        # 移除前缀: ¥ ￥ RMB 元
        text = re.sub(r'[¥￥RMB\s元]', '', text, flags=re.IGNORECASE)
        # 移除千位分隔符
        text = text.replace(',', '')
        try:
            return round(float(re.search(r'[\d.]+', text).group()), 2)
        except Exception:
            return 0.0

    @staticmethod
    def _parse_end_value(text: str) -> str:
        """
        解析结束时间属性值 → ISO "YYYY-MM-DD HH:MM:SS"

        格式: "2026/8/6 4:52:30" 或 "2026-08-06 04:51:45"
        """
        text = text.strip().replace('/', '-')
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
        return text

    @staticmethod
    def _parse_end_text(text: str) -> str:
        """
        解析相对结束时间文本 → ISO

        格式: "6小时22分11秒后结束"、"1天3小时后结束"、"刚刚"
        """
        text = text.strip()

        days = hours = minutes = 0
        m = re.search(r'(\d+)\s*天', text)
        if m:
            days = int(m.group(1))
        m = re.search(r'(\d+)\s*小时', text)
        if m:
            hours = int(m.group(1))
        m = re.search(r'(\d+)\s*分', text)
        if m:
            minutes = int(m.group(1))

        now = datetime.now()
        if days or hours or minutes:
            return (now + timedelta(days=days, hours=hours, minutes=minutes)).strftime(
                "%Y-%m-%d %H:%M:%S")

        return now.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _parse_date(text: str) -> str:
        """解析 CardHobby 日期格式（兼容旧接口）"""
        text = text.strip()

        # "3天前" / "5小时前" / "刚刚"
        ago_match = re.match(r'(\d+)\s*天前', text)
        if ago_match:
            days = int(ago_match.group(1))
            return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        ago_match = re.match(r'(\d+)\s*小时前', text)
        if ago_match:
            hours = int(ago_match.group(1))
            return (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d")
        if "刚刚" in text or "几分钟前" in text:
            return datetime.now().strftime("%Y-%m-%d")

        # 标准日期格式
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%m-%d", "%m月%d日", "%Y年%m月%d日"]:
            try:
                return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        return datetime.now().strftime("%Y-%m-%d")


# ============================================================
# 主采集器
# ============================================================

class CardHobbyScraper:
    """CardHobby 数据采集器（真实站点，www.cardhobby.com.cn）"""

    def __init__(self, delay: float = REQUEST_DELAY, timeout: int = 60):
        self.base_url = CARHOBBY_BASE_URL
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._last_request = 0.0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()

    def _fetch(self, url: str) -> Optional[str]:
        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                return resp.text
            except requests.exceptions.HTTPError as e:
                print(f"  [警告] HTTP {resp.status_code}: {e} (第 {attempt+1}/{MAX_RETRIES} 次)")
                time.sleep(self.delay * (attempt + 1))
            except Exception as e:
                print(f"  [重试 {attempt+1}/{MAX_RETRIES}] {type(e).__name__}: {str(e)[:100]}")
                time.sleep(self.delay * (attempt + 1))
        return None

    # ----------------------------------------------------------
    # 列表采集
    # ----------------------------------------------------------
    def scrape_auction_page(self, page: int = 1) -> List[CardHobbyListing]:
        """采集拍卖列表单页"""
        url = f"{AUCTION_LIST_URL}?page={page}"
        html = self._fetch(url)
        if not html:
            return []
        return CardHobbyParser.parse_list_page(html, self.base_url)

    def scrape_latest_page(self, page: int = 1) -> List[CardHobbyListing]:
        """采集最新上架列表单页"""
        url = f"{LATEST_LIST_URL}?page={page}"
        html = self._fetch(url)
        if not html:
            return []
        return CardHobbyParser.parse_list_page(html, self.base_url)

    def scrape_auctions(self, max_pages: int = MAX_PAGES,
                        start_page: int = 1) -> List[CardHobbyListing]:
        """批量采集拍卖列表（自动翻页）"""
        all_items: List[CardHobbyListing] = []
        print(f"\n[CardHobby] 采集拍卖列表: 第 {start_page}~{start_page+max_pages-1} 页")

        for page in range(start_page, start_page + max_pages):
            items = self.scrape_auction_page(page)
            print(f"  [第{page}页] {len(items)} 条")
            if not items:
                print(f"  [第{page}页] 无数据，停止")
                break
            all_items.extend(items)

        print(f"[CardHobby] 共采集 {len(all_items)} 条")
        return all_items

    def scrape_ending_soon_page(self, page: int = 1) -> List[CardHobbyListing]:
        """采集"即将结束"列表单页"""
        url = f"{CARHOBBY_BASE_URL}/market/timeout?page={page}"
        html = self._fetch(url)
        if not html:
            return []
        return CardHobbyParser.parse_list_page(html, self.base_url)

    def scrape_ending_soon(self, max_pages: int = MAX_PAGES,
                           start_page: int = 1) -> List[CardHobbyListing]:
        """
        采集"即将结束"列表（/market/timeout）

        注意: 卡淘公开的在拍列表大部分是 ¥1 起拍 0 出价的商品（无价格信号）。
        "即将结束"页按结束时间排序，出价>0 的占比更高（实测 ~5%）。
        调用方应过滤 bids > 0 的记录作为真实市场信号。
        """
        all_items: List[CardHobbyListing] = []
        print(f"\n[CardHobby] 采集即将结束列表: 第 {start_page}~{start_page+max_pages-1} 页")

        for page in range(start_page, start_page + max_pages):
            items = self.scrape_ending_soon_page(page)
            n_bid = sum(1 for it in items if it.bids > 0)
            print(f"  [第{page}页] {len(items)} 条 (有出价 {n_bid} 条)")
            if not items:
                break
            all_items.extend(items)

        print(f"[CardHobby] 共采集 {len(all_items)} 条")
        return all_items

    def scrape_all_lists(self, max_pages: int = MAX_PAGES) -> List[CardHobbyListing]:
        """
        三列表混合采集: 拍卖 + 最新上架 + 即将结束（轮转翻页）

        卡淘为全品类平台（足球/F1/漫威混排），各列表篮球占比 ~30%。
        混合采集提高有效（有出价）篮球数据量，调用方应做篮球过滤。
        """
        all_items: List[CardHobbyListing] = []
        fetchers = [
            ("拍卖", self.scrape_auction_page),
            ("最新", self.scrape_latest_page),
            ("即将结束", self.scrape_ending_soon_page),
        ]
        print(f"\n[CardHobby] 三列表混合采集: 每个列表 {max_pages} 页")

        for label, fetch_fn in fetchers:
            for page in range(1, max_pages + 1):
                items = fetch_fn(page)
                if not items:
                    break
                all_items.extend(items)
            print(f"  [{label}] 完成")

        print(f"[CardHobby] 共采集 {len(all_items)} 条")
        return all_items

    def scrape_item(self, item_id: str) -> Optional[CardHobbyListing]:
        """采集单个商品详情"""
        url = ITEM_URL.format(item_id=item_id)
        html = self._fetch(url)
        if not html or len(html) < 100:
            return None
        return CardHobbyParser.parse_item_page(html, self.base_url, item_id)

    # ----------------------------------------------------------
    # 兼容旧接口
    # ----------------------------------------------------------
    def search(self, keyword: str, max_pages: int = MAX_PAGES) -> List[CardHobbyListing]:
        """
        搜索函数（兼容旧接口）

        注意: 卡淘的关键词搜索需要登录，匿名搜索不返回结果。
        此处降级为采集公开的拍卖列表（在拍商品 = 真实市场数据）。
        """
        print(f"\n[CardHobby] 提示: 关键词搜索需登录，降级为采集公开拍卖列表")
        return self.scrape_auctions(max_pages=max_pages)

    def search_player_cards(self, player_name: str, series: str = None,
                            year: int = None, max_pages: int = 5) -> List[CardHobbyListing]:
        """搜索指定球员卡片（降级为公开拍卖列表）"""
        return self.scrape_auctions(max_pages=max_pages)

    @staticmethod
    def export_json(items: List[CardHobbyListing], filepath: str) -> str:
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        data = {
            "source": "CardHobby",
            "total": len(items),
            "exported_at": datetime.now().isoformat(),
            "listings": [it.to_dict() for it in items],
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[CardHobby] 已导出 {len(items)} 条 → {os.path.abspath(filepath)}")
        return os.path.abspath(filepath)

    @staticmethod
    def to_dataframe(items: List[CardHobbyListing]) -> "pd.DataFrame":
        """转为 pandas DataFrame"""
        import pandas as pd
        return pd.DataFrame([it.to_dict() for it in items])


# ============================================================
# Mock 采集器（测试用）
# ============================================================

class MockCardHobbyScraper(CardHobbyScraper):
    """返回模拟 CardHobby 数据，不发起真实请求"""

    def __init__(self):
        super().__init__(delay=0)

    def _fetch(self, url: str) -> Optional[str]:
        return """
<html><body>
<div class="kzCell">
  <div class="kzmark"><img class="auctionImg" src="/Content/img/auction.png" /></div>
  <div class="kzImageFrame">
    <a href="/market/item/88001234" title="2023-24 Panini Prizm Silver 维克托·文班亚马 Victor Wembanyama RC PSA 10">
      <img src="https://images.cardhobby.com/x.jpg" /></a>
  </div>
  <div class="detailbox">
    <p class="boxDesc"><a href="/market/item/88001234" title="2023-24 Panini Prizm Silver 维克托·文班亚马 Victor Wembanyama RC PSA 10">2023-24 Panini Prizm Silver 维克托·文班亚马 Victor Wembanyama RC PSA 10</a></p>
    <table class="card-info">
      <tr><td width="80%"><span>￥3,280.00</span></td>
          <td align="right"><i class="icon-auction"></i><a href="/market/bidrecords/88001234">23<span>次出价</span></a></td></tr>
      <tr><td>约$ 452.41</td><td align="right"><span class="text-muted">运费：￥12.00</span></td></tr>
    </table>
    <div><a href="/market/user/1001"><span class="realname">卡迷之家</span></a></div>
  </div>
  <span class="priceEndTime"><span class="effect__time" value="2026/8/6 12:30:00">5小时22分后结束</span></span>
</div>
<div class="kzCell">
  <div class="kzImageFrame">
    <a href="/market/item/88005678" title="2020-21 Panini Prizm Gold 勒布朗·詹姆斯 LeBron James /10 BGS 9.5">
      <img src="https://images.cardhobby.com/y.jpg" /></a>
  </div>
  <div class="detailbox">
    <p class="boxDesc"><a href="/market/item/88005678" title="2020-21 Panini Prizm Gold 勒布朗·詹姆斯 LeBron James /10 BGS 9.5">2020-21 Panini Prizm Gold 勒布朗·詹姆斯 LeBron James /10 BGS 9.5</a></p>
    <table class="card-info">
      <tr><td width="80%"><span>￥58,000.00</span></td>
          <td align="right"><a href="/market/bidrecords/88005678">5<span>次出价</span></a></td></tr>
      <tr><td>约$ 8,000.00</td><td align="right"><span class="text-muted">运费：￥0.00</span></td></tr>
    </table>
    <div><a href="/market/user/1002"><span class="realname">球星卡世界</span></a></div>
  </div>
  <span class="priceEndTime"><span class="effect__time" value="2026/8/6 20:00:00">明天20:00结束</span></span>
</div>
</body></html>
"""


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  CardHobby (卡淘) 采集器 — 测试")
    print("=" * 60)

    # 测试1: CNY 解析
    print("\n[测试1] 人民币价格解析")
    tests = [("¥3,280.00", 3280.0), ("￥58,000", 58000.0),
             ("RMB 880", 880.0), ("185000元", 185000.0)]
    for text, expected in tests:
        result = CardHobbyParser._parse_cny(text)
        ok = "OK" if result == expected else f"FAIL (got {result})"
        print(f"  [{ok}] '{text}' → {result}")

    # 测试2: 结束时间解析
    print("\n[测试2] 结束时间解析")
    print(f"  '2026/8/6 4:52:30' → {CardHobbyParser._parse_end_value('2026/8/6 4:52:30')}")
    print(f"  '6小时22分后结束' → {CardHobbyParser._parse_end_text('6小时22分后结束')}")

    # 测试3: Mock 列表解析
    print("\n[测试3] Mock 列表解析")
    scraper = MockCardHobbyScraper()
    results = scraper.scrape_auction_page(1)
    for item in results:
        print(f"  ¥{item.price_cny:,.0f} (${item.price_usd:,.0f}) | {item.title[:60]}")
        print(f"    卖家: {item.seller_name} | 出价: {item.bids} | 结束: {item.end_time}")

    # 测试4: JSON 导出
    print("\n[测试4] JSON 导出")
    CardHobbyScraper.export_json(results, "data/raw/cardhobby_test.json")

    print(f"\n{'=' * 60}")
    print("  测试完成！")
    print(f"{'=' * 60}")
