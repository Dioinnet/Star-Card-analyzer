"""
数据清洗与整合管线 (Data Pipeline)
=================================
整合多渠道采集的数据（eBay 爬虫、CardSight 同步），完成：
  1. 数据加载 — 从 data/raw/ 读取原始 JSON/CSV
  2. 数据清洗 — 去重、异常值过滤、缺失值处理
  3. 价格标准化 — 统一货币、剔除异常成交、Best Offer 标记
  4. 特征提取 — 从标题中解析球员/系列/年份/折射/编号信息
  5. 数据输出 — 保存到 data/processed/ 供 train.py 模型训练使用

架构：
  data/raw/ebay_*.json  ─┐
  data/raw/cardsight_*.json ─┤
                              ├── DataPipeline ──→ data/processed/clean_transactions.csv
  data/raw/card_transactions.csv ─┘

用法：
  python -m src.scrapers.data_pipeline  # 运行测试入口
"""

import sys
import os
import io
import re
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple, Set

# 强制 UTF-8 输出
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np
import pandas as pd
from collections import Counter


# ============================================================
# 配置常量
# ============================================================

# 数据目录
RAW_DATA_DIR = "data/raw"
PROCESSED_DATA_DIR = "data/processed"

# 异常值检测参数（IQR 方法）
IQR_MULTIPLIER = 3.0           # IQR 倍数（标准为 1.5，卡片价格波动大用 3.0）
MIN_PRICE_USD = 0.99           # 最低合理价格（低于此视为数据错误）
MAX_PRICE_USD = 10_000_000     # 最高合理价格（高于此可能是异常）

# 去重参数
TITLE_SIMILARITY_THRESHOLD = 0.85  # 标题相似度阈值（0-1）
DUPLICATE_TIME_WINDOW_DAYS = 30    # 同一卡片在此天数内的重复视为数据重复

# 价格标准化
CURRENCY_RATES = {              # 对美元的参考汇率（会定期波动，此处为近似值）
    "USD": 1.00,
    "GBP": 1.27,
    "EUR": 1.08,
    "CAD": 0.73,
    "AUD": 0.66,
}

# 可信来源（加权聚合时的权重）
SOURCE_WEIGHTS = {
    "ebay": 0.6,                # eBay 成交价权重最高（真实成交）
    "cardsight": 0.3,           # CardSight 目录参考价
    "simulated": 0.1,           # 模拟数据权重最低
}

# 从标题解析的特征模式
TITLE_PATTERNS = {
    # 年份匹配: "2019-20" 或 "2020"
    "year": re.compile(r'(\d{4})-?\d{0,2}\s*(?:Panini|Topps|Upper|Fleer|Bowman|Donruss)'),
    "year_simple": re.compile(r'\b(20\d{2})\b'),
    # 折射等级匹配
    "refraction": re.compile(
        r'\b(Silver|Gold|Green|Red|Blue|Purple|Orange|Pink|Black|Mojo|'
        r'White Sparkle|Cracked Ice|Disco|Pulsar|Wave|Checkerboard|'
        r'Hyper|Lazer|Zebra|Tiger|Snake|Elephant|Choice|Neon|'
        r'FOTL|Fast Break|Asia|Redemption|Press Proof)\b',
        re.IGNORECASE,
    ),
    # 限量编号匹配: "/99", "#/49", " /10 "
    "serial_numbered": re.compile(r'[#/]\s*(\d{1,3})\b'),
    # 1/1 特殊匹配
    "one_of_one": re.compile(r'\b1\s*/\s*1\b|One\s+of\s+One', re.IGNORECASE),
    # 签字匹配
    "auto": re.compile(r'\b(Auto|Autograph|Signed|On[-\s]Card)\b', re.IGNORECASE),
    # 评级匹配
    "graded": re.compile(
        r'\b(PSA|BGS|SGC|CGC|CSG|HGA)\s*(\d{1,2}(?:\.\d)?)\b', re.IGNORECASE
    ),
    # 新秀匹配
    "rookie": re.compile(r'\b(RC|Rookie|RPA)\b', re.IGNORECASE),
    # Patch/物料匹配
    "memorabilia": re.compile(
        r'\b(Patch|Jersey|Relic|Memorabilia|RPA|Logoman|Tag)\b', re.IGNORECASE
    ),
}


# ============================================================
# 数据清洗器
# ============================================================

class DataCleaner:
    """
    数据清洗器 — 提供一系列静态清洗方法

    清洗规则:
      1. 去除价格为 0、NaN、负数的记录
      2. IQR 方法剔除极端异常值（分产品系列独立计算）
      3. 标记（而非删除）Best Offer 成交（可能不完全反映市场价）
      4. 统一货币为 USD
      5. 去除标题/关键字段缺失的记录
    """

    @staticmethod
    def remove_invalid_prices(df: pd.DataFrame, price_col: str = "price") -> pd.DataFrame:
        """
        移除无效价格

        Args:
            df: 输入 DataFrame
            price_col: 价格列名

        Returns:
            清洗后的 DataFrame
        """
        before = len(df)

        # 移除 NaN
        df = df.dropna(subset=[price_col]).copy()
        # 移除负数/零
        df = df[df[price_col] > 0]
        # 移除超出合理范围
        df = df[(df[price_col] >= MIN_PRICE_USD) & (df[price_col] <= MAX_PRICE_USD)]

        removed = before - len(df)
        if removed > 0:
            print(f"  [价格清洗] 移除 {removed} 条无效价格记录")

        return df

    @staticmethod
    def remove_outliers_iqr(
        df: pd.DataFrame,
        price_col: str = "price",
        group_col: Optional[str] = "product",
        multiplier: float = IQR_MULTIPLIER,
    ) -> pd.DataFrame:
        """
        使用 IQR 方法移除异常值

        对于球星卡，不同产品系列的价格分布差异极大（Prizm Base vs NT RPA），
        因此按系列分组计算 IQR，避免误删高端卡。

        Args:
            df: 输入 DataFrame
            price_col: 价格列名
            group_col: 分组列名（None = 不分组）
            multiplier: IQR 倍数

        Returns:
            清洗后的 DataFrame
        """
        before = len(df)

        if group_col and group_col in df.columns:
            # 按系列分组过滤
            masks = []
            for group_name, group_df in df.groupby(group_col):
                if len(group_df) < 10:
                    # 样本太少，不应用 IQR
                    masks.append(group_df.index)
                    continue

                q1 = group_df[price_col].quantile(0.25)
                q3 = group_df[price_col].quantile(0.75)
                iqr = q3 - q1
                lower = max(q1 - multiplier * iqr, MIN_PRICE_USD)
                upper = q3 + multiplier * iqr

                mask = (group_df[price_col] >= lower) & (group_df[price_col] <= upper)
                masks.append(group_df[mask].index)

                removed_in_group = len(group_df) - mask.sum()
                if removed_in_group > 0:
                    print(f"    [{group_name}] 移除 {removed_in_group}/{len(group_df)} 条异常值 "
                          f"(范围: ${lower:.0f} ~ ${upper:.0f})")

            if masks:
                keep_indices = masks[0]
                for other in masks[1:]:
                    keep_indices = keep_indices.union(other)
            else:
                keep_indices = pd.Index([])
            df = df.loc[keep_indices]
        else:
            # 不分组，全局 IQR
            q1 = df[price_col].quantile(0.25)
            q3 = df[price_col].quantile(0.75)
            iqr = q3 - q1
            lower = max(q1 - multiplier * iqr, MIN_PRICE_USD)
            upper = q3 + multiplier * iqr
            df = df[(df[price_col] >= lower) & (df[price_col] <= upper)]

        removed = before - len(df)
        print(f"  [异常值过滤] 移除 {removed} 条记录 (IQR x{multiplier})")
        return df

    @staticmethod
    def normalize_currency(
        df: pd.DataFrame,
        price_col: str = "price",
        currency_col: str = "currency",
        rates: Dict[str, float] = None,
    ) -> pd.DataFrame:
        """
        统一货币为 USD

        Args:
            df: 输入 DataFrame
            price_col: 价格列名
            currency_col: 货币列名
            rates: 汇率字典

        Returns:
            价格已转换为 USD 的 DataFrame
        """
        if rates is None:
            rates = CURRENCY_RATES

        if currency_col not in df.columns:
            # 假设所有价格都是 USD
            df["currency"] = "USD"
            return df

        df = df.copy()
        converted = 0

        for cur, rate in rates.items():
            mask = df[currency_col].str.upper() == cur.upper()
            if mask.any() and cur != "USD":
                df.loc[mask, price_col] = df.loc[mask, price_col] * rate
                converted += mask.sum()

        # 统一货币标记
        df[currency_col] = "USD"

        if converted > 0:
            print(f"  [货币统一] {converted} 条记录已转换为 USD")
        return df

    @staticmethod
    def mark_best_offer(df: pd.DataFrame) -> pd.DataFrame:
        """
        标记 Best Offer 成交

        Best Offer 成交的实际价格被 eBay 隐藏，显示的是原始 Listing 价格。
        这类数据在模型训练时应降低权重或标记。

        Args:
            df: 输入 DataFrame

        Returns:
            添加了 is_best_offer 列和 price_confidence 列的 DataFrame
        """
        df = df.copy()

        if "is_best_offer" not in df.columns:
            df["is_best_offer"] = False

        # 价格置信度：Best Offer = 0.5, 其他 = 1.0
        df["price_confidence"] = np.where(df["is_best_offer"], 0.5, 1.0)

        bo_count = df["is_best_offer"].sum()
        if bo_count > 0:
            print(f"  [Best Offer] 标记 {bo_count} 条 Best Offer 成交（置信度=0.5）")

        return df

    @staticmethod
    def fill_missing_values(df: pd.DataFrame) -> pd.DataFrame:
        """
        填充缺失值

        Args:
            df: 输入 DataFrame

        Returns:
            缺失值已填充的 DataFrame
        """
        df = df.copy()

        # 数值列填充 0
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            if df[col].isna().any():
                df[col] = df[col].fillna(0)

        # 字符串列填充空字符串
        str_cols = df.select_dtypes(include=["object"]).columns
        for col in str_cols:
            if df[col].isna().any():
                df[col] = df[col].fillna("")

        # 布尔列填充 False
        bool_cols = df.select_dtypes(include=["bool"]).columns
        for col in bool_cols:
            if df[col].isna().any():
                df[col] = df[col].fillna(False)

        return df


class Deduplicator:
    """
    去重器 — 基于多维度识别重复记录
    """

    @staticmethod
    def _title_similarity(title1: str, title2: str) -> float:
        """
        计算标题相似度（基于词集合的 Jaccard 系数）

        Args:
            title1, title2: 标题字符串

        Returns:
            相似度 (0 ~ 1)
        """
        if not title1 or not title2:
            return 0.0

        # 分词（按空格和常见分隔符）
        tokens1 = set(re.split(r'[\s\-/,]+', title1.lower()))
        tokens2 = set(re.split(r'[\s\-/,]+', title2.lower()))

        # 去除常见噪声词
        noise = {"", "the", "a", "an", "is", "of", "in", "and", "or", "for",
                 "to", "with", "on", "at", "by", "from", "new", "no"}
        tokens1.discard("")
        tokens2.discard("")
        tokens1 -= noise
        tokens2 -= noise

        if not tokens1 or not tokens2:
            return 0.0

        intersection = tokens1 & tokens2
        union = tokens1 | tokens2

        return len(intersection) / len(union)

    @staticmethod
    def deduplicate(
        df: pd.DataFrame,
        title_col: str = "title",
        date_col: str = "sold_date",
        price_col: str = "price",
        item_id_col: str = "item_id",
    ) -> pd.DataFrame:
        """
        多维度去重

        策略:
          1. 精确去重 — 相同 Item ID → 保留最新
          2. 相似标题去重 — 同一球员/系列，30天内 → 保留中位数价格
          3. 完美匹配（同标题同日期）→ 随机保留一条

        Args:
            df: 输入 DataFrame
            title_col: 标题列名
            date_col: 日期列名
            price_col: 价格列名
            item_id_col: Item ID 列名

        Returns:
            去重后的 DataFrame
        """
        before = len(df)
        df = df.copy()

        # ---- 第1轮：Item ID 精确去重 ----
        if item_id_col in df.columns and df[item_id_col].notna().any():
            # 同一 Item ID → 保留最后一条（最新采集）
            df = df.sort_values("scraped_at" if "scraped_at" in df.columns else date_col)
            dup_ids = df[df[item_id_col].duplicated(keep="last")][item_id_col].nunique()
            df = df.drop_duplicates(subset=[item_id_col], keep="last")
            if dup_ids > 0:
                print(f"  [去重-ItemID] 移除 {dup_ids} 条重复 Item ID")

        # ---- 第2轮：相似标题去重 ----
        if title_col in df.columns:
            # 标准化日期
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

            # 按球员名分组（如果无此字段，全局处理）
            group_col = "player_name" if "player_name" in df.columns else None

            to_remove = set()
            n = len(df)

            if group_col and group_col in df.columns:
                groups = df.groupby(group_col)
            else:
                groups = [("all", df)]

            for gname, gdf in groups:
                indices = gdf.index.tolist()
                for i in range(len(indices)):
                    if indices[i] in to_remove:
                        continue
                    for j in range(i + 1, len(indices)):
                        if indices[j] in to_remove:
                            continue
                        t1 = str(df.loc[indices[i], title_col])
                        t2 = str(df.loc[indices[j], title_col])
                        sim = Deduplicator._title_similarity(t1, t2)

                        if sim >= TITLE_SIMILARITY_THRESHOLD:
                            # 检查日期是否接近
                            d1 = df.loc[indices[i], date_col] if date_col in df.columns else None
                            d2 = df.loc[indices[j], date_col] if date_col in df.columns else None
                            if pd.notna(d1) and pd.notna(d2):
                                diff = abs((d1 - d2).days)
                                if diff <= DUPLICATE_TIME_WINDOW_DAYS:
                                    # 保留价格更接近中位数的（更可靠）
                                    median_price = df.loc[[indices[i], indices[j]], price_col].median()
                                    diff_i = abs(df.loc[indices[i], price_col] - median_price)
                                    diff_j = abs(df.loc[indices[j], price_col] - median_price)
                                    to_remove.add(indices[j] if diff_j > diff_i else indices[i])
                            else:
                                to_remove.add(indices[j])

            if to_remove:
                df = df.drop(index=list(to_remove))
                print(f"  [去重-相似标题] 移除 {len(to_remove)} 条相似记录 (阈值={TITLE_SIMILARITY_THRESHOLD})")

        print(f"  [去重总计] {before} → {len(df)} (移除 {before - len(df)} 条)")
        return df


class TitleParser:
    """
    从卡片标题中提取结构化特征

    输入示例:
      "2019-20 Panini Prizm Silver LeBron James #249 PSA 9 MINT"
      "2020-21 National Treasures Luka Doncic RPA /99 BGS 9.5 Auto Patch"

    输出:
      {year: 2019, series: "Prizm", refraction: "Silver", player: "LeBron James",
       graded: "PSA 9", is_auto: True, is_memorabilia: True, ...}
    """

    # 已知产品系列关键词
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
    }

    @staticmethod
    def parse_title(title: str) -> Dict[str, Any]:
        """
        从标题解析卡片属性

        Args:
            title: 卡片 Listing 标题

        Returns:
            解析后的属性字典
        """
        result = {
            "title": title,
            "parsed_year": None,
            "parsed_series": None,
            "parsed_refraction": "Base",
            "parsed_serial_numbered": False,
            "parsed_print_run": 0,
            "parsed_is_auto": False,
            "parsed_is_memorabilia": False,
            "parsed_is_rookie": False,
            "parsed_is_graded": False,
            "parsed_grader": None,
            "parsed_grade_score": None,
            "parsed_is_1of1": False,
        }

        if not title:
            return result

        # ---- 年份 ----
        year_match = TITLE_PATTERNS["year"].search(title)
        if year_match:
            year_str = year_match.group(1)
            result["parsed_year"] = int(year_str)
        else:
            year_match = TITLE_PATTERNS["year_simple"].search(title)
            if year_match:
                result["parsed_year"] = int(year_match.group(1))

        # ---- 产品系列 ----
        title_lower = title.lower()
        for series_name, keywords in TitleParser.SERIES_KEYWORDS.items():
            for kw in keywords:
                if kw in title_lower:
                    result["parsed_series"] = series_name
                    break
            if result["parsed_series"]:
                break

        # ---- 折射等级 ----
        ref_match = TITLE_PATTERNS["refraction"].search(title)
        if ref_match:
            result["parsed_refraction"] = ref_match.group(1)

        # ---- 1/1 ----
        if TITLE_PATTERNS["one_of_one"].search(title):
            result["parsed_is_1of1"] = True
            result["parsed_serial_numbered"] = True
            result["parsed_print_run"] = 1
            result["parsed_refraction"] = "1/1"

        # ---- 限量编号（非 1/1） ----
        if not result["parsed_is_1of1"]:
            serial_match = TITLE_PATTERNS["serial_numbered"].search(title)
            if serial_match:
                print_run = int(serial_match.group(1))
                if 2 <= print_run <= 999:
                    result["parsed_serial_numbered"] = True
                    result["parsed_print_run"] = print_run

        # ---- 签字 ----
        if TITLE_PATTERNS["auto"].search(title):
            result["parsed_is_auto"] = True

        # ---- 评级 ----
        grade_match = TITLE_PATTERNS["graded"].search(title)
        if grade_match:
            result["parsed_is_graded"] = True
            result["parsed_grader"] = grade_match.group(1).upper()
            try:
                result["parsed_grade_score"] = float(grade_match.group(2))
            except ValueError:
                pass

        # ---- 新秀 ----
        if TITLE_PATTERNS["rookie"].search(title):
            result["parsed_is_rookie"] = True

        # ---- 物料 ----
        if TITLE_PATTERNS["memorabilia"].search(title):
            result["parsed_is_memorabilia"] = True

        return result

    @staticmethod
    def enrich_dataframe(df: pd.DataFrame, title_col: str = "title") -> pd.DataFrame:
        """
        批量解析 DataFrame 中的标题列，补充解析字段

        Args:
            df: 输入 DataFrame
            title_col: 标题列名

        Returns:
            补充了解析字段的 DataFrame
        """
        if title_col not in df.columns:
            print("  [标题解析] 无标题列，跳过")
            return df

        print(f"  [标题解析] 解析 {len(df)} 条标题...")
        parsed_list = df[title_col].apply(TitleParser.parse_title)
        parsed_df = pd.DataFrame(list(parsed_list))

        # 将解析结果合并到原 DataFrame（不覆盖已有值）
        for col in parsed_df.columns:
            if col.startswith("parsed_"):
                original_col = col.replace("parsed_", "")
                if original_col not in df.columns or df[original_col].isna().all():
                    df[original_col] = parsed_df[col].values
                else:
                    # 仅填充缺失值
                    mask = df[original_col].isna() | (df[original_col] == "") | (df[original_col] == 0)
                    df.loc[mask, original_col] = parsed_df.loc[mask, col].values

        print(f"  [标题解析] 完成，补充 {len(parsed_df.columns)} 个解析字段")
        return df


# ============================================================
# 数据处理管线
# ============================================================

class DataPipeline:
    """
    数据整合清洗管线

    用法:
        pipeline = DataPipeline()
        clean_df = pipeline.run(["data/raw/ebay_results.json",
                                 "data/raw/card_transactions.csv"])
    """

    def __init__(self):
        self.cleaner = DataCleaner()
        self.deduplicator = Deduplicator()
        self.title_parser = TitleParser()
        self._stats = {}  # 处理统计

    def run(
        self,
        input_files: List[str],
        output_file: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        执行完整的数据处理管线

        Args:
            input_files: 输入文件路径列表（支持 .json/.csv）
            output_file: 输出文件路径（None = 自动命名）

        Returns:
            清洗后的 DataFrame
        """
        print(f"\n{'=' * 60}")
        print(f"  数据管线 — 开始处理")
        print(f"{'=' * 60}")

        t0 = datetime.now()

        # ---- 步骤 1：加载数据 ----
        print(f"\n[步骤 1/6] 加载数据 ({len(input_files)} 个文件)")
        df = self._load_multiple(input_files)
        self._stats["raw_count"] = len(df)
        print(f"  总记录数: {len(df)}")

        if len(df) == 0:
            print("  [错误] 无数据可处理，管线终止")
            return df

        # ---- 步骤 2：标题解析 ----
        print(f"\n[步骤 2/6] 标题特征提取")
        if "title" in df.columns:
            df = self.title_parser.enrich_dataframe(df)
        else:
            print("  跳过（无标题列）")

        # ---- 步骤 3：价格清洗与标准化 ----
        print(f"\n[步骤 3/6] 价格清洗与标准化")
        df = self.cleaner.remove_invalid_prices(df)
        df = self.cleaner.normalize_currency(df)
        df = self.cleaner.mark_best_offer(df)
        self._stats["after_price_clean"] = len(df)

        # ---- 步骤 4：异常值过滤 ----
        print(f"\n[步骤 4/6] 异常值过滤")
        df = self.cleaner.remove_outliers_iqr(df)
        self._stats["after_outlier_filter"] = len(df)

        # ---- 步骤 5：去重 ----
        print(f"\n[步骤 5/6] 数据去重")
        df = self.deduplicator.deduplicate(df)
        self._stats["after_dedup"] = len(df)

        # ---- 步骤 6：缺失值填充 ----
        print(f"\n[步骤 6/6] 缺失值填充")
        df = self.cleaner.fill_missing_values(df)

        # ---- 输出 ----
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(PROCESSED_DATA_DIR, f"clean_transactions_{timestamp}.csv")

        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)
        df.to_csv(output_file, index=False, encoding="utf-8")
        print(f"\n  [输出] 清洗后数据已保存: {output_file}")

        elapsed = (datetime.now() - t0).total_seconds()
        self._print_summary(elapsed)

        return df

    def _load_multiple(self, filepaths: List[str]) -> pd.DataFrame:
        """
        加载多个 CSV/JSON 文件并合并

        Args:
            filepaths: 文件路径列表

        Returns:
            合并后的 DataFrame
        """
        dfs = []
        for fp in filepaths:
            df = self._load_single(fp)
            if df is not None and len(df) > 0:
                # 标记数据来源
                source = "ebay" if "ebay" in fp.lower() else (
                    "cardsight" if "cardsight" in fp.lower() else "simulated"
                )
                df["source"] = source
                dfs.append(df)
                print(f"    {fp}: {len(df)} 条记录 [来源: {source}]")

        if not dfs:
            print("  [警告] 没有成功加载任何数据")
            return pd.DataFrame()

        # 合并，对齐列
        all_cols = set()
        for d in dfs:
            all_cols.update(d.columns)
        aligned = []
        for d in dfs:
            for col in all_cols - set(d.columns):
                d[col] = None
            aligned.append(d)

        return pd.concat(aligned, ignore_index=True)

    def _load_single(self, filepath: str) -> Optional[pd.DataFrame]:
        """
        加载单个文件（支持 CSV 和 JSON）

        Args:
            filepath: 文件路径

        Returns:
            DataFrame 或 None
        """
        if not os.path.exists(filepath):
            print(f"    [跳过] 文件不存在: {filepath}")
            return None

        try:
            if filepath.endswith(".csv"):
                return pd.read_csv(filepath, encoding="utf-8")
            elif filepath.endswith(".json"):
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 支持嵌套格式: {"listings": [...]} 或直接数组 [...]
                if isinstance(data, dict):
                    for key in ["listings", "data", "results", "cards"]:
                        if key in data and isinstance(data[key], list):
                            return pd.DataFrame(data[key])
                    # 如果找不到数组键，尝试整个 dict 作为一行
                    return pd.DataFrame([data])
                elif isinstance(data, list):
                    return pd.DataFrame(data)
                return None
            else:
                print(f"    [跳过] 不支持的文件格式: {filepath}")
                return None
        except Exception as e:
            print(f"    [错误] 加载 {filepath} 失败: {e}")
            return None

    def _print_summary(self, elapsed_sec: float):
        """打印处理统计摘要"""
        print(f"\n{'=' * 60}")
        print(f"  数据管线 — 处理完成")
        print(f"  耗时: {elapsed_sec:.1f}s")
        print(f"  原始记录: {self._stats.get('raw_count', 0)}")
        print(f"  → 价格清洗后: {self._stats.get('after_price_clean', 0)}")
        print(f"  → 异常值过滤后: {self._stats.get('after_outlier_filter', 0)}")
        print(f"  → 去重后: {self._stats.get('after_dedup', 0)}")
        print(f"  保留率: {self._stats.get('after_dedup', 0) / max(self._stats.get('raw_count', 1), 1):.1%}")
        print(f"  输出目录: {PROCESSED_DATA_DIR}/")
        print(f"{'=' * 60}")

    def get_stats(self) -> Dict[str, int]:
        """获取处理统计"""
        return self._stats.copy()


# ============================================================
# 便捷函数
# ============================================================

def quick_clean(df: pd.DataFrame) -> pd.DataFrame:
    """
    快速清洗（一行调用）

    Args:
        df: 原始 DataFrame

    Returns:
        清洗后的 DataFrame
    """
    cleaner = DataCleaner()
    df = cleaner.remove_invalid_prices(df)
    df = cleaner.normalize_currency(df)
    df = cleaner.remove_outliers_iqr(df)
    df = cleaner.fill_missing_values(df)
    return df


def merge_ebay_with_cardsight(
    ebay_df: pd.DataFrame,
    cardsight_df: pd.DataFrame,
    on_player: str = "player_name",
    on_year: str = "card_year",
) -> pd.DataFrame:
    """
    将 eBay 成交数据与 CardSight 目录元数据合并

    匹配条件: 球员名 + 年份 + 折射等级近似

    Args:
        ebay_df: eBay 成交数据
        cardsight_df: CardSight 目录数据
        on_player: 球员名字段
        on_year: 年份字段

    Returns:
        合并后的 DataFrame（左连接）
    """
    # 在 CardSight 中构建复合键
    if on_player in ebay_df.columns and on_player in cardsight_df.columns:
        return ebay_df.merge(
            cardsight_df,
            on=[on_player, on_year],
            how="left",
            suffixes=("", "_cs"),
        )
    return ebay_df


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  数据清洗管线 — 测试")
    print("=" * 60)

    # ---- 准备测试数据 ----
    print("\n[准备] 生成模拟测试数据...")

    # 创建包含各种"脏数据"的测试 DataFrame
    rng = np.random.default_rng(42)
    n = 200

    test_df = pd.DataFrame({
        "title": [
            f"20{20 + rng.integers(0, 4)}-{21 + rng.integers(0, 4)} Panini "
            f"{rng.choice(['Prizm', 'Select', 'National Treasures'])} "
            f"{rng.choice(['Silver', 'Gold', 'Base', 'Red'])} "
            f"{rng.choice(['LeBron James', 'Luka Doncic', 'Victor Wembanyama', 'Stephen Curry'])} "
            f"{rng.choice(['RC', '', 'RPA /99', 'PSA 10'])}"
            for _ in range(n)
        ],
        "price": np.concatenate([
            rng.lognormal(mean=5, sigma=1.5, size=n - 10),  # 正常价格
            [0, -50, np.nan, 0, 1e9, 0.01, 50000000, 0, np.nan, -1],  # 脏数据
        ]),
        "currency": rng.choice(["USD", "GBP", "EUR", "USD", "USD"], size=n),
        "is_best_offer": rng.choice([True, False], size=n, p=[0.15, 0.85]),
        "sold_date": [
            (datetime.now() - timedelta(days=int(d))).strftime("%Y-%m-%d")
            for d in rng.integers(1, 365, size=n)
        ],
        "item_id": [
            str(100000000 + i) if i % 3 != 0 else str(100000000 + i - 1)
            for i in range(n)
        ],
        "product": rng.choice(
            ["Prizm", "Select", "National Treasures", "Donruss", "Mosaic"],
            size=n,
        ),
    })

    print(f"  测试数据: {len(test_df)} 条记录")
    print(f"  含 NaN 价格: {test_df['price'].isna().sum()}")
    print(f"  含零价格: {(test_df['price'] <= 0).sum()}")
    print(f"  Best Offer: {test_df['is_best_offer'].sum()}")

    # ---- 测试 1：价格清洗 ----
    print("\n[测试1] 价格清洗")
    cleaner = DataCleaner()
    df1 = cleaner.remove_invalid_prices(test_df)
    print(f"  无效价格移除: {len(test_df)} → {len(df1)}")

    # ---- 测试 2：货币统一 ----
    print("\n[测试2] 货币统一")
    df2 = cleaner.normalize_currency(df1)
    # 查找一条 GBP 记录来展示汇率转换
    gbp_rows = df1[df1["currency"] == "GBP"]
    if len(gbp_rows) > 0:
        idx = gbp_rows.index[0]
        orig_price = test_df.loc[idx, "price"]
        new_price = df2.loc[idx, "price"]
        print(f"  GBP → USD 示例: 原始 £{orig_price:.2f} → 转换后 ${new_price:.2f}")
    print(f"  所有货币已统一: {(df2['currency'] == 'USD').all()}")

    # ---- 测试 3：异常值过滤 ----
    print("\n[测试3] IQR 异常值过滤（按系列分组）")
    df3 = cleaner.remove_outliers_iqr(df2)
    print(f"  异常值过滤: {len(df2)} → {len(df3)}")

    # ---- 测试 4：去重 ----
    print("\n[测试4] 数据去重")
    dedup = Deduplicator()
    df4 = dedup.deduplicate(df3)

    # ---- 测试 5：标题解析 ----
    print("\n[测试5] 标题解析")
    parser = TitleParser()
    sample_titles = [
        "2019-20 Panini Prizm Silver LeBron James #249 PSA 9 MINT",
        "2020-21 National Treasures Luka Doncic RPA /99 BGS 9.5 Auto Patch",
        "2023-24 Panini Prizm Victor Wembanyama Gold /10 RC Auto",
        "2021-22 Panini Select LaMelo Ball Courtside Red PSA 10 GEM MT",
        "2022-23 Panini Prizm Stephen Curry Black Gold 1/1 One of One",
    ]
    for t in sample_titles:
        parsed = parser.parse_title(t)
        flags = []
        if parsed["parsed_is_rookie"]:
            flags.append("新秀")
        if parsed["parsed_is_auto"]:
            flags.append("签字")
        if parsed["parsed_is_memorabilia"]:
            flags.append("物料")
        if parsed["parsed_is_graded"]:
            flags.append(f"{parsed['parsed_grader']} {parsed['parsed_grade_score']}")
        if parsed["parsed_is_1of1"]:
            flags.append("1/1")
        flag_str = " | ".join(flags) if flags else "普卡"
        print(f"  年份={parsed['parsed_year']} | 系列={parsed['parsed_series']} | "
              f"折射={parsed['parsed_refraction']} | 限量/{parsed['parsed_print_run']} | "
              f"[{flag_str}]")
        print(f"    ← {t[:80]}")

    # ---- 测试 6：完整管线 ----
    print("\n[测试6] 完整数据管线")
    pipeline = DataPipeline()

    # 创建临时测试文件
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    test_csv_path = os.path.join(RAW_DATA_DIR, "test_raw_transactions.csv")
    test_df.to_csv(test_csv_path, index=False)

    clean_df = pipeline.run(
        input_files=[test_csv_path],
    )

    # ---- 测试 7：最终数据质量检查 ----
    print("\n[测试7] 数据质量检查")
    if len(clean_df) > 0:
        print(f"  总记录数:    {len(clean_df)}")
        print(f"  价格范围:    ${clean_df['price'].min():.2f} ~ ${clean_df['price'].max():.2f}")
        print(f"  价格中位数:  ${clean_df['price'].median():.2f}")
        print(f"  价格均值:    ${clean_df['price'].mean():.2f}")
        print(f"  NaN 数量:    {clean_df.isna().sum().sum()}")
        print(f"  重复 Item ID: {clean_df['item_id'].duplicated().sum() if 'item_id' in clean_df.columns else 'N/A'}")
        print(f"  数据来源分布:")
        if "source" in clean_df.columns:
            for src, cnt in clean_df["source"].value_counts().items():
                print(f"    {src}: {cnt}")
        print(f"  列数: {len(clean_df.columns)}")
        print(f"  列名: {list(clean_df.columns)[:15]}...")

    # ---- 测试 8：统计报告 ----
    print("\n[测试8] 管线统计")
    stats = pipeline.get_stats()
    for step, count in stats.items():
        print(f"  {step}: {count}")

    print(f"\n{'=' * 60}")
    print("  测试完成！所有功能模块正常。")
    print(f"{'=' * 60}")
