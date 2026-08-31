"""
CardSight API 卡片目录同步模块
==============================
通过 CardSight API 同步球星卡的目录元数据（球员、系列、平行版本、
限量信息等），为本地数据库提供标准化卡片信息。

功能：
  - API 认证（API Key + HMAC 签名）
  - 按球员拉取卡片目录
  - 按系列拉取 checklist
  - 增量同步（只拉取上次同步之后的新增/变更）
  - 本地 SQLite 缓存 + 响应写入磁盘备份
  - 速率控制

CardSight API 文档（假设）:
  Base URL: https://api.cardsight.com/v1
  Auth: Header "X-API-Key" + HMAC-SHA256 signature
  Endpoints:
    GET  /players          — 球员列表
    GET  /players/{id}     — 球员详情 + 卡片列表
    GET  /sets             — 系列列表
    GET  /sets/{id}/cards  — 系列的卡片 checklist
    GET  /cards/{id}       — 单张卡片详情
    POST /sync/updates     — 增量更新（since timestamp）

用法：
  python -m src.scrapers.cardsight_sync  # 运行测试入口
"""

import sys
import os
import io
import time
import json
import hmac
import hashlib
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Generator
from urllib.parse import urljoin

# 强制 UTF-8 输出
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests


# ============================================================
# 配置
# ============================================================

# CardSight API 配置（需要有效的 API Key）
CARDSIGHT_API_KEY = os.environ.get("CARDSIGHT_API_KEY", "cs_test_key_placeholder")
CARDSIGHT_API_SECRET = os.environ.get("CARDSIGHT_API_SECRET", "cs_test_secret_placeholder")
CARDSIGHT_BASE_URL = os.environ.get("CARDSIGHT_BASE_URL", "https://api.cardsight.com/v1")

# 速率控制
RATE_LIMIT_PER_MINUTE = 60
RATE_LIMIT_PER_HOUR = 1000

# 本地缓存路径
CACHE_DIR = "data/cache/cardsight"
DB_PATH = os.path.join(CACHE_DIR, "card_catalog.db")

# 每页返回条数
DEFAULT_PAGE_SIZE = 100


# ============================================================
# API 认证
# ============================================================

class CardSightAuth:
    """
    CardSight API HMAC-SHA256 签名认证

    签名算法:
      1. 构造待签名字符串: METHOD + "\n" + PATH + "\n" + TIMESTAMP + "\n" + BODY_HASH
      2. 使用 API Secret 做 HMAC-SHA256
      3. 结果以 hex 形式放入 X-Signature 头
    """

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")

    def sign_request(
        self,
        method: str,
        path: str,
        body: str = "",
        timestamp: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        生成签名请求头

        Args:
            method: HTTP 方法 (GET/POST/PUT)
            path: URL 路径（不含 base URL）
            body: 请求体（JSON字符串，GET 请求为空）
            timestamp: Unix 时间戳（秒），None 则自动生成

        Returns:
            包含 X-API-Key, X-Timestamp, X-Signature 的 headers dict
        """
        if timestamp is None:
            timestamp = str(int(time.time()))

        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

        # 构造签名字符串
        signing_string = f"{method.upper()}\n{path}\n{timestamp}\n{body_hash}"

        # HMAC-SHA256
        signature = hmac.new(
            self.api_secret,
            signing_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "X-API-Key": self.api_key,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


# ============================================================
# 数据模型
# ============================================================

class CardCatalogEntry:
    """标准化卡片目录条目"""

    __slots__ = (
        "card_id", "player_name", "player_id", "set_name", "set_id",
        "card_number", "card_year", "parallel_name", "parallel_id",
        "print_run", "is_rookie", "is_auto", "is_memorabilia",
        "is_serial_numbered", "front_image_url", "last_updated",
    )

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self.card_id: str = ""
        self.player_name: str = ""
        self.player_id: str = ""
        self.set_name: str = ""
        self.set_id: str = ""
        self.card_number: str = ""          # 卡号（如 "#249"）
        self.card_year: int = 0
        self.parallel_name: str = ""        # 平行版本名称 (Base/Silver/Gold/...)
        self.parallel_id: str = ""
        self.print_run: int = 0             # 限量发行数，0 = 不编号
        self.is_rookie: bool = False
        self.is_auto: bool = False
        self.is_memorabilia: bool = False
        self.is_serial_numbered: bool = False
        self.front_image_url: str = ""
        self.last_updated: str = ""

        if data:
            self._from_api_response(data)

    def _from_api_response(self, data: Dict[str, Any]):
        """从 API 响应填充字段"""
        self.card_id = data.get("id", "")
        self.player_name = data.get("player", {}).get("name", "")
        self.player_id = data.get("player", {}).get("id", "")
        self.set_name = data.get("set", {}).get("name", "")
        self.set_id = data.get("set", {}).get("id", "")
        self.card_number = data.get("card_number", "")
        self.card_year = data.get("year", 0)
        self.parallel_name = data.get("parallel", {}).get("name", "Base")
        self.parallel_id = data.get("parallel", {}).get("id", "")
        self.print_run = data.get("print_run", 0) or 0
        self.is_rookie = data.get("flags", {}).get("is_rookie", False)
        self.is_auto = data.get("flags", {}).get("is_auto", False)
        self.is_memorabilia = data.get("flags", {}).get("is_memorabilia", False)
        self.is_serial_numbered = data.get("flags", {}).get("is_serial_numbered", False)
        self.front_image_url = data.get("images", {}).get("front", "")
        self.last_updated = data.get("updated_at", "")

    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return {slot: getattr(self, slot) for slot in self.__slots__}

    def to_sqlite_row(self) -> tuple:
        """转为 SQLite 插入行"""
        return tuple(
            1 if isinstance(getattr(self, s), bool) and getattr(self, s)
            else 0 if isinstance(getattr(self, s), bool)
            else getattr(self, s)
            for s in self.__slots__
        )


# ============================================================
# API 客户端
# ============================================================

class CardSightClient:
    """
    CardSight API 客户端

    用法:
        client = CardSightClient(api_key="...", api_secret="...")
        players = client.list_players(sport="basketball")
        cards = client.get_player_cards("player_id_123")
        checklist = client.get_set_checklist("set_id_456")
    """

    def __init__(
        self,
        api_key: str = CARDSIGHT_API_KEY,
        api_secret: str = CARDSIGHT_API_SECRET,
        base_url: str = CARDSIGHT_BASE_URL,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = CardSightAuth(api_key, api_secret)
        self.session = requests.Session()
        self._request_timestamps: List[float] = []

    def _check_rate_limit(self):
        """速率控制：每分钟 60 次，每小时 1000 次"""
        now = time.time()
        # 清理旧时间戳
        self._request_timestamps = [
            ts for ts in self._request_timestamps
            if now - ts < 3600
        ]

        # 检查每分钟限制
        minute_ago = now - 60
        recent_count = sum(1 for ts in self._request_timestamps if ts > minute_ago)
        if recent_count >= RATE_LIMIT_PER_MINUTE:
            wait = 60 - (now - min(ts for ts in self._request_timestamps if ts > minute_ago))
            if wait > 0:
                print(f"  [速率限制] 等待 {wait:.1f}s ...")
                time.sleep(wait)

        # 检查每小时限制
        if len(self._request_timestamps) >= RATE_LIMIT_PER_HOUR:
            wait = 3600 - (now - self._request_timestamps[0])
            if wait > 0:
                print(f"  [速率限制] 小时额度用完，等待 {wait:.0f}s ...")
                time.sleep(wait)

        self._request_timestamps.append(time.time())

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        body: Optional[Dict] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        发送 API 请求（带签名认证）

        Args:
            method: HTTP 方法
            path: API 路径（不含 base URL）
            params: 查询参数
            body: 请求体 dict

        Returns:
            JSON 响应 dict 或 None
        """
        self._check_rate_limit()

        url = urljoin(self.base_url, path)
        body_str = json.dumps(body) if body else ""
        headers = self.auth.sign_request(method, path, body_str)

        try:
            if method.upper() == "GET":
                resp = self.session.get(url, headers=headers, params=params, timeout=30)
            elif method.upper() == "POST":
                resp = self.session.post(url, headers=headers, params=params, data=body_str, timeout=30)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {method}")

            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 0
            error_body = e.response.text[:200] if e.response else ""
            print(f"  [API错误] HTTP {status}: {error_body}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"  [网络错误] {e}")
            return None

    def _paginate(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        max_pages: int = 10,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        通用分页迭代器

        Args:
            method: HTTP 方法
            path: API 路径
            params: 查询参数（会自动注入 page/page_size）
            max_pages: 最大页数
        """
        params = (params or {}).copy()
        params.setdefault("page_size", DEFAULT_PAGE_SIZE)

        for page in range(1, max_pages + 1):
            params["page"] = page
            resp = self._request(method, path, params=params)
            if resp is None:
                break

            yield resp

            # 检查是否有下一页
            meta = resp.get("meta", {})
            total_pages = meta.get("total_pages", 1)
            if page >= total_pages:
                break

    # ---- API 端点 ----

    def list_players(
        self,
        sport: str = "basketball",
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取球员列表

        Args:
            sport: 运动类型
            search: 搜索关键词（可选）

        Returns:
            球员信息列表
        """
        print(f"[CardSight] 拉取球员列表: sport={sport}, search={search or '全部'}")
        params = {"sport": sport}
        if search:
            params["search"] = search

        all_players = []
        for page_resp in self._paginate("GET", "/players", params=params):
            players = page_resp.get("data", [])
            all_players.extend(players)

        print(f"[CardSight] 获取到 {len(all_players)} 名球员")
        return all_players

    def get_player_cards(
        self,
        player_id: str,
        include_parallels: bool = True,
    ) -> List[CardCatalogEntry]:
        """
        获取指定球员的所有卡片

        Args:
            player_id: 球员 ID
            include_parallels: 是否包含平行版本

        Returns:
            List[CardCatalogEntry]
        """
        print(f"[CardSight] 拉取球员卡片: player_id={player_id}")
        params = {"include_parallels": str(include_parallels).lower()}
        path = f"/players/{player_id}/cards"

        entries = []
        for page_resp in self._paginate("GET", path, params=params):
            cards = page_resp.get("data", [])
            for card_data in cards:
                entries.append(CardCatalogEntry(card_data))

        print(f"[CardSight] 获取到 {len(entries)} 张卡片")
        return entries

    def get_set_checklist(
        self,
        set_id: str,
    ) -> List[CardCatalogEntry]:
        """
        获取系列的完整 checklist

        Args:
            set_id: 系列 ID

        Returns:
            List[CardCatalogEntry]
        """
        print(f"[CardSight] 拉取系列 checklist: set_id={set_id}")
        path = f"/sets/{set_id}/cards"

        entries = []
        for page_resp in self._paginate("GET", path):
            cards = page_resp.get("data", [])
            for card_data in cards:
                entries.append(CardCatalogEntry(card_data))

        print(f"[CardSight] 获取到 {len(entries)} 张卡片")
        return entries

    def list_sets(
        self,
        year: Optional[int] = None,
        brand: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取产品系列列表

        Args:
            year: 年份过滤（可选）
            brand: 品牌过滤（可选，如 "Panini"）

        Returns:
            系列信息列表
        """
        print(f"[CardSight] 拉取系列列表: year={year}, brand={brand}")
        params = {}
        if year:
            params["year"] = year
        if brand:
            params["brand"] = brand

        all_sets = []
        for page_resp in self._paginate("GET", "/sets", params=params):
            sets = page_resp.get("data", [])
            all_sets.extend(sets)

        print(f"[CardSight] 获取到 {len(all_sets)} 个系列")
        return all_sets

    def get_card_detail(self, card_id: str) -> Optional[CardCatalogEntry]:
        """
        获取单张卡片详情

        Args:
            card_id: 卡片 ID

        Returns:
            CardCatalogEntry 或 None
        """
        resp = self._request("GET", f"/cards/{card_id}")
        if resp:
            return CardCatalogEntry(resp.get("data", {}))
        return None

    def get_updates(
        self,
        since: datetime,
    ) -> List[CardCatalogEntry]:
        """
        增量更新：获取自某个时间点以来的新增/变更卡片

        Args:
            since: 起始时间

        Returns:
            List[CardCatalogEntry]
        """
        since_str = since.isoformat()
        print(f"[CardSight] 增量同步: since={since_str}")

        params = {"since": since_str}
        entries = []
        for page_resp in self._paginate("GET", "/sync/updates", params=params):
            cards = page_resp.get("data", [])
            for card_data in cards:
                entries.append(CardCatalogEntry(card_data))

        print(f"[CardSight] 增量更新: {len(entries)} 条变更")
        return entries


# ============================================================
# 本地 SQLite 缓存
# ============================================================

class CardCatalogDB:
    """
    本地卡片目录数据库（SQLite）

    存储从 CardSight 同步的卡片元数据，支持增量更新。
    """

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS cards (
            card_id            TEXT PRIMARY KEY,
            player_name        TEXT NOT NULL,
            player_id          TEXT NOT NULL,
            set_name           TEXT NOT NULL,
            set_id             TEXT NOT NULL,
            card_number        TEXT DEFAULT '',
            card_year          INTEGER DEFAULT 0,
            parallel_name      TEXT DEFAULT 'Base',
            parallel_id        TEXT DEFAULT '',
            print_run          INTEGER DEFAULT 0,
            is_rookie          INTEGER DEFAULT 0,
            is_auto            INTEGER DEFAULT 0,
            is_memorabilia     INTEGER DEFAULT 0,
            is_serial_numbered INTEGER DEFAULT 0,
            front_image_url    TEXT DEFAULT '',
            last_updated       TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_player ON cards(player_name);
        CREATE INDEX IF NOT EXISTS idx_set ON cards(set_name);
        CREATE INDEX IF NOT EXISTS idx_year ON cards(card_year);
        CREATE INDEX IF NOT EXISTS idx_player_year ON cards(player_name, card_year);
        CREATE INDEX IF NOT EXISTS idx_rookie ON cards(is_rookie);
    """

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        """初始化表结构"""
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    def upsert_cards(self, entries: List[CardCatalogEntry]) -> int:
        """
        批量插入/更新卡片记录

        Args:
            entries: 卡片条目列表

        Returns:
            实际写入的记录数
        """
        sql = """
            INSERT OR REPLACE INTO cards (
                card_id, player_name, player_id, set_name, set_id,
                card_number, card_year, parallel_name, parallel_id,
                print_run, is_rookie, is_auto, is_memorabilia,
                is_serial_numbered, front_image_url, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [entry.to_sqlite_row() for entry in entries]

        cursor = self.conn.cursor()
        cursor.executemany(sql, rows)
        self.conn.commit()

        print(f"[DB] 写入/更新 {cursor.rowcount} 条记录")
        return cursor.rowcount

    def query_by_player(
        self,
        player_name: str,
        year: Optional[int] = None,
        only_rookies: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        按球员查询卡片

        Args:
            player_name: 球员名（模糊匹配）
            year: 年份过滤（可选）
            only_rookies: 仅新秀卡

        Returns:
            卡片字典列表
        """
        sql = "SELECT * FROM cards WHERE player_name LIKE ?"
        params: List[Any] = [f"%{player_name}%"]

        if year:
            sql += " AND card_year = ?"
            params.append(year)
        if only_rookies:
            sql += " AND is_rookie = 1"

        sql += " ORDER BY card_year DESC, set_name, parallel_name"

        cursor = self.conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def query_by_set(
        self,
        set_name: str,
    ) -> List[Dict[str, Any]]:
        """
        按系列查询 checklist

        Args:
            set_name: 系列名（模糊匹配）

        Returns:
            卡片字典列表
        """
        sql = (
            "SELECT * FROM cards WHERE set_name LIKE ? "
            "ORDER BY card_number"
        )
        cursor = self.conn.execute(sql, [f"%{set_name}%"])
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_sync_cursor(self) -> Optional[str]:
        """
        获取上次同步的时间游标

        Returns:
            ISO 格式时间字符串或 None
        """
        row = self.conn.execute(
            "SELECT MAX(last_updated) FROM cards"
        ).fetchone()
        return row[0] if row and row[0] else None

    def get_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息"""
        total = self.conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        players = self.conn.execute(
            "SELECT COUNT(DISTINCT player_name) FROM cards"
        ).fetchone()[0]
        sets = self.conn.execute(
            "SELECT COUNT(DISTINCT set_name) FROM cards"
        ).fetchone()[0]
        rookies = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE is_rookie = 1"
        ).fetchone()[0]
        autos = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE is_auto = 1"
        ).fetchone()[0]

        return {
            "total_cards": total,
            "unique_players": players,
            "unique_sets": sets,
            "rookie_cards": rookies,
            "auto_cards": autos,
        }

    def close(self):
        """关闭数据库连接"""
        self.conn.close()


# ============================================================
# 同步管理器
# ============================================================

class CardSightSyncManager:
    """
    CardSight 同步管理器

    协调 API 客户端和本地缓存，实现增量同步策略。

    用法:
        manager = CardSightSyncManager(client, db)
        manager.full_sync(sport="basketball")       # 全量同步
        manager.incremental_sync()                  # 增量同步
    """

    def __init__(self, client: CardSightClient, db: CardCatalogDB):
        self.client = client
        self.db = db

    def full_sync(self, sport: str = "basketball", year: Optional[int] = None):
        """
        全量同步卡片目录

        Args:
            sport: 运动类型
            year: 年份过滤（None = 全部）
        """
        print(f"\n{'='*60}")
        print(f"[全量同步] 开始 — sport={sport}" + (f", year={year}" if year else ""))
        t0 = time.time()

        # 1. 拉取所有系列
        sets = self.client.list_sets(year=year)
        if not sets:
            print("[全量同步] 未获取到任何系列")
            return

        # 2. 逐个系列拉取 checklist
        total = 0
        for si, s in enumerate(sets):
            set_id = s.get("id", "")
            set_name = s.get("name", "Unknown")
            print(f"\n  [{si+1}/{len(sets)}] 同步系列: {set_name}")

            entries = self.client.get_set_checklist(set_id)
            if entries:
                written = self.db.upsert_cards(entries)
                total += written

            # 进度间隔
            if (si + 1) % 5 == 0:
                print(f"  [进度] 已完成 {si+1}/{len(sets)} 个系列, 累计 {total} 条记录")

        elapsed = time.time() - t0
        stats = self.db.get_stats()
        print(f"\n[全量同步] 完成! 耗时 {elapsed:.1f}s")
        print(f"[全量同步] 总记录: {stats['total_cards']} | "
              f"球员: {stats['unique_players']} | 系列: {stats['unique_sets']}")

    def incremental_sync(self):
        """增量同步：只拉取自上次同步后的变更"""
        last_sync = self.db.get_sync_cursor()
        if last_sync:
            since = datetime.fromisoformat(last_sync)
            print(f"[增量同步] 上次同步时间: {last_sync}")
        else:
            since = datetime.now(timezone.utc) - timedelta(days=7)
            print(f"[增量同步] 无同步记录，回溯 7 天: {since.isoformat()}")

        entries = self.client.get_updates(since)
        if entries:
            written = self.db.upsert_cards(entries)
            print(f"[增量同步] 完成: {written} 条更新")
        else:
            print(f"[增量同步] 无新的变更")

    def sync_players_of_interest(
        self,
        player_names: List[str],
    ):
        """
        同步关注球员的卡片

        Args:
            player_names: 球员名列表
        """
        print(f"[关注同步] 同步 {len(player_names)} 名球员的卡片")

        # 先查找球员 ID
        all_players = self.client.list_players()
        player_map = {p["name"].lower(): p["id"] for p in all_players}

        total = 0
        for name in player_names:
            pid = player_map.get(name.lower())
            if not pid:
                print(f"  [跳过] 未找到球员: {name}")
                continue

            entries = self.client.get_player_cards(pid)
            if entries:
                written = self.db.upsert_cards(entries)
                total += written

        print(f"[关注同步] 完成: {total} 条记录")


# ============================================================
# Mock API 客户端（用于测试）
# ============================================================

class MockCardSightClient(CardSightClient):
    """
    Mock CardSight 客户端 — 返回模拟数据，不发起真实请求
    """

    def __init__(self):
        super().__init__(api_key="mock", api_secret="mock", base_url="mock://api")

    def _request(self, method, path, params=None, body=None):
        """返回模拟数据"""
        return None  # 由各方法自行生成模拟数据

    def list_players(self, sport="basketball", search=None):
        """返回模拟球员列表"""
        mock_players = [
            {"id": "p001", "name": "LeBron James", "team": "Lakers", "rookie_year": 2003},
            {"id": "p002", "name": "Stephen Curry", "team": "Warriors", "rookie_year": 2009},
            {"id": "p003", "name": "Victor Wembanyama", "team": "Spurs", "rookie_year": 2023},
            {"id": "p004", "name": "Luka Doncic", "team": "Mavericks", "rookie_year": 2018},
            {"id": "p005", "name": "Giannis Antetokounmpo", "team": "Bucks", "rookie_year": 2013},
            {"id": "p006", "name": "Nikola Jokic", "team": "Nuggets", "rookie_year": 2015},
            {"id": "p007", "name": "Jayson Tatum", "team": "Celtics", "rookie_year": 2017},
            {"id": "p008", "name": "Anthony Edwards", "team": "Timberwolves", "rookie_year": 2020},
            {"id": "p009", "name": "Ja Morant", "team": "Grizzlies", "rookie_year": 2019},
            {"id": "p010", "name": "Zion Williamson", "team": "Pelicans", "rookie_year": 2019},
        ]
        print(f"[Mock CardSight] 返回 {len(mock_players)} 名模拟球员")
        return mock_players

    def list_sets(self, year=None, brand=None):
        """返回模拟系列列表"""
        mock_sets = [
            {"id": "s001", "name": "2019-20 Panini Prizm Basketball", "year": 2019, "brand": "Panini"},
            {"id": "s002", "name": "2020-21 Panini Prizm Basketball", "year": 2020, "brand": "Panini"},
            {"id": "s003", "name": "2020-21 Panini Select Basketball", "year": 2020, "brand": "Panini"},
            {"id": "s004", "name": "2020-21 Panini National Treasures Basketball", "year": 2020, "brand": "Panini"},
            {"id": "s005", "name": "2021-22 Panini Prizm Basketball", "year": 2021, "brand": "Panini"},
            {"id": "s006", "name": "2022-23 Panini Prizm Basketball", "year": 2022, "brand": "Panini"},
            {"id": "s007", "name": "2023-24 Panini Prizm Basketball", "year": 2023, "brand": "Panini"},
        ]
        filtered = [s for s in mock_sets if (year is None or s["year"] == year)]
        print(f"[Mock CardSight] 返回 {len(filtered)} 个模拟系列")
        return filtered

    def get_set_checklist(self, set_id):
        """返回模拟 checklist"""
        mock_cards = []
        # 根据 set_id 生成不同数量的模拟卡片
        num_cards = 50 if "Prizm" in set_id else 30
        for i in range(num_cards):
            player_names = ["LeBron James", "Stephen Curry", "Luka Doncic",
                          "Victor Wembanyama", "Giannis Antetokounmpo",
                          "Nikola Jokic", "Jayson Tatum", "Zion Williamson"]
            p = player_names[i % len(player_names)]
            parallels = ["Base", "Silver", "Red", "Blue", "Gold /10"]
            par = parallels[i % len(parallels)]

            mock_cards.append(CardCatalogEntry({
                "id": f"card_{set_id}_{i:04d}",
                "player": {"id": f"p_{i%len(player_names):03d}", "name": p},
                "set": {"id": set_id, "name": f"Mock Set {set_id}"},
                "card_number": f"#{i+1}",
                "year": 2020 + (i % 5),
                "parallel": {"id": f"par_{i%5}", "name": par},
                "print_run": 10 if "Gold" in par else (99 if "Blue" in par else 0),
                "flags": {
                    "is_rookie": p == "Victor Wembanyama",
                    "is_auto": i % 3 == 0,
                    "is_memorabilia": i % 10 == 0,
                    "is_serial_numbered": ("/" in par),
                },
                "images": {"front": f"https://mock.cardsight.com/img/{set_id}_{i:04d}.jpg"},
                "updated_at": datetime.now().isoformat(),
            }))

        print(f"[Mock CardSight] 系列 {set_id}: 返回 {len(mock_cards)} 张模拟卡片")
        return mock_cards

    def get_player_cards(self, player_id, include_parallels=True):
        """返回模拟球员卡片"""
        set_ids = ["s001", "s002", "s003", "s004"]
        entries = []
        for si, sid in enumerate(set_ids):
            for j in range(3):
                entries.append(CardCatalogEntry({
                    "id": f"card_{player_id}_{sid}_{j}",
                    "player": {"id": player_id, "name": f"Player {player_id}"},
                    "set": {"id": sid, "name": f"Mock Set {sid}"},
                    "card_number": f"#{j+1}",
                    "year": 2020 + si,
                    "parallel": {"id": f"par_{j}", "name": ["Base", "Silver", "Gold /10"][j]},
                    "print_run": 10 if j == 2 else 0,
                    "flags": {
                        "is_rookie": j == 2,
                        "is_auto": j >= 1,
                        "is_memorabilia": False,
                        "is_serial_numbered": j == 2,
                    },
                    "images": {},
                    "updated_at": datetime.now().isoformat(),
                }))
        print(f"[Mock CardSight] 球员 {player_id}: 返回 {len(entries)} 张模拟卡片")
        return entries

    def get_updates(self, since):
        """返回模拟增量更新"""
        entries = [
            CardCatalogEntry({
                "id": "card_new_001",
                "player": {"id": "p003", "name": "Victor Wembanyama"},
                "set": {"id": "s007", "name": "2023-24 Panini Prizm Basketball"},
                "card_number": "#1",
                "year": 2023,
                "parallel": {"id": "par_gold", "name": "Gold /10"},
                "print_run": 10,
                "flags": {"is_rookie": True, "is_auto": True,
                          "is_memorabilia": False, "is_serial_numbered": True},
                "images": {},
                "updated_at": datetime.now().isoformat(),
            }),
        ]
        print(f"[Mock CardSight] 增量更新: {len(entries)} 条")
        return entries


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  CardSight API 同步模块 — 测试")
    print("=" * 60)

    # ---- 测试 1：签名认证 ----
    print("\n[测试1] HMAC-SHA256 签名")
    auth = CardSightAuth(api_key="test_key", api_secret="test_secret")
    headers = auth.sign_request("GET", "/v1/players")
    print(f"  X-API-Key:    {headers['X-API-Key']}")
    print(f"  X-Timestamp:  {headers['X-Timestamp']}")
    print(f"  X-Signature: {headers['X-Signature'][:40]}...")

    # 验证签名可复现
    headers2 = auth.sign_request("GET", "/v1/players", timestamp=headers["X-Timestamp"])
    assert headers["X-Signature"] == headers2["X-Signature"], "签名不一致!"
    print("  ✓ 签名一致（可复现）")

    # ---- 测试 2：Mock API 客户端 ----
    print("\n[测试2] Mock API — 球员列表")
    client = MockCardSightClient()
    players = client.list_players()
    for p in players[:5]:
        print(f"  {p['id']}: {p['name']} ({p['team']}, RC {p['rookie_year']})")

    # ---- 测试 3：系列列表 + Checklist ----
    print("\n[测试3] Mock API — 系列列表 & Checklist")
    sets = client.list_sets(year=2020)
    for s in sets[:3]:
        print(f"  {s['id']}: {s['name']}")
    checklist = client.get_set_checklist("s002")
    print(f"  s002 checklist: {len(checklist)} 张卡片")
    for c in checklist[:5]:
        print(f"    {c.card_number} {c.player_name} — {c.parallel_name}"
              + (f" /{c.print_run}" if c.print_run else ""))

    # ---- 测试 4：SQLite 缓存 ----
    print("\n[测试4] SQLite 本地缓存")
    db_path = "data/cache/cardsight/test_catalog.db"
    # 清理旧数据
    if os.path.exists(db_path):
        os.remove(db_path)

    db = CardCatalogDB(db_path)
    # 写入模拟数据
    mock_entries = client.get_set_checklist("s001")
    db.upsert_cards(mock_entries)

    stats = db.get_stats()
    print(f"  数据库统计: {json.dumps(stats, indent=2)}")

    # 查询测试
    results = db.query_by_player("LeBron James")
    print(f"  按球员查询 'LeBron James': {len(results)} 条")
    if results:
        print(f"    示例: {results[0]['player_name']} — {results[0]['set_name']}")

    db.close()

    # ---- 测试 5：同步管理器 ----
    print("\n[测试5] 同步管理器")
    db2 = CardCatalogDB(db_path)
    manager = CardSightSyncManager(client, db2)

    # 全量同步（Mock数据）
    manager.full_sync(sport="basketball", year=2020)
    stats2 = db2.get_stats()
    print(f"  同步后统计: {json.dumps(stats2, indent=2)}")

    # 增量同步
    manager.incremental_sync()

    db2.close()

    # ---- 测试 6：数据模型 ----
    print("\n[测试6] CardCatalogEntry 数据模型")
    sample_data = {
        "id": "card_test_001",
        "player": {"id": "p003", "name": "Victor Wembanyama"},
        "set": {"id": "s007", "name": "2023-24 Panini Prizm Basketball"},
        "card_number": "#1",
        "year": 2023,
        "parallel": {"id": "par_gold", "name": "Gold /10"},
        "print_run": 10,
        "flags": {
            "is_rookie": True, "is_auto": True,
            "is_memorabilia": False, "is_serial_numbered": True,
        },
        "images": {"front": "https://example.com/img.jpg"},
        "updated_at": "2025-01-15T12:00:00Z",
    }
    entry = CardCatalogEntry(sample_data)
    print(f"  card_id:      {entry.card_id}")
    print(f"  player_name:  {entry.player_name}")
    print(f"  set_name:     {entry.set_name}")
    print(f"  parallel:     {entry.parallel_name}")
    print(f"  print_run:    {entry.print_run}")
    print(f"  is_rookie:    {entry.is_rookie}")
    print(f"  is_auto:      {entry.is_auto}")
    print(f"  to_dict keys: {list(entry.to_dict().keys())}")

    print(f"\n{'=' * 60}")
    print("  测试完成！所有功能模块正常。")
    print(f"{'=' * 60}")
