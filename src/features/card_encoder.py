"""
球星卡特征编码器
===============
将卡片属性字典转化为机器学习特征向量（36维）。

编码维度说明：
  - 球星效应(1) + 基础特征(6) + 物料特征(6) + 评级特征(3)
  - 产品系列One-Hot(5) + 年份特征(3) + 交互特征(12) = 36维
"""

import numpy as np
import pandas as pd
import joblib
import os

# 特征名称列表（用于SHAP归因展示）
FEATURE_NAMES = [
    # 球星效应 (1维)
    "star_power_log",

    # 基础特征 (6维)
    "is_rookie",
    "refraction_level",
    "serial_scarcity",
    "is_jersey_match",
    "auto_type",
    "is_auto",

    # 物料特征 (6维)
    "material_windows",
    "material_colors",
    "is_logoman",
    "is_tag",
    "material_source",
    "has_material",

    # 评级特征 (3维)
    "has_grade",
    "grade_score",
    "grade_grader",

    # 产品系列 One-Hot (5维)
    "product_Prizm",
    "product_Select",
    "product_NT",
    "product_Donruss",
    "product_Mosaic",

    # 年份特征 (3维)
    "card_year_norm",
    "is_vintage",
    "is_modern_rc",

    # 交互特征 (12维)
    "rpa_effect",
    "logoman_1of1",
    "rookie_refraction",
    "rookie_auto",
    "rookie_grade",
    "auto_material",
    "logoman_grade",
    "jersey_auto",
    "star_rookie",
    "scarcity_refraction",
    "high_grade_rc",
    "superfractor_effect",
]

# 常量
PRODUCT_NAMES = ["Prizm", "Select", "National Treasures", "Donruss", "Mosaic"]
MIN_YEAR = 2012
MAX_YEAR = 2024


class CardEncoder:
    """
    球星卡特征编码器

    用法:
        encoder = CardEncoder()
        encoder.fit(df)           # 学习球星效应(各球员Base卡均价)
        X = encoder.transform(df) # 编码为特征矩阵
    """

    def __init__(self):
        self.star_power_map = {}  # 球员名 -> log(base_card_avg_price)
        self.is_fitted = False

    def fit(self, df):
        """
        拟合编码器：从数据中学习球星效应

        Args:
            df: DataFrame, 需包含 player_name, price, refraction_level, is_rookie 列

        Returns:
            self
        """
        # 球星效应：用该球员的Base卡（非新秀、无折射溢价）均价来量化
        base_mask = (df["refraction_level"] == 0) & (df["is_rookie"] == 0)
        base_data = df[base_mask].copy()

        if len(base_data) == 0:
            # 如果没有纯Base卡，回退到全部非新秀卡
            base_data = df[df["is_rookie"] == 0].copy()

        if len(base_data) > 0:
            player_avg = base_data.groupby("player_name")["price"].median()
            for name, avg_price in player_avg.items():
                self.star_power_map[name] = np.log(max(avg_price, 0.5))
        else:
            # 极端情况：用全量数据估算
            player_avg = df.groupby("player_name")["price"].median()
            for name, avg_price in player_avg.items():
                self.star_power_map[name] = np.log(max(avg_price, 0.5))

        self.is_fitted = True
        print(f"[编码器] 已拟合 {len(self.star_power_map)} 名球员的球星效应")
        return self

    # tier -> 默认 Base 卡均价 (USD)，用于训练集/预测时无该球员数据的兜底
    # 避免"未知球员=最弱球员"的偏见: tier 0 超巨 ~$300, 1 全明星 ~$120,
    # 2 优质先发 ~$35, 3 轮换 ~$15, 4 板凳 ~$8, 5 双向 ~$4
    TIER_DEFAULT_PRICE = {0: 300.0, 1: 120.0, 2: 35.0, 3: 15.0, 4: 8.0, 5: 4.0}

    def _fallback_star_power(self, player: str) -> float:
        """未知球员的球星效应默认值：优先查球员库 tier，兜底 $35（角色球员）"""
        try:
            from src.data.player_db import get_player_by_name
            info = get_player_by_name(player)
            tier = info["tier"] if info else 2
        except Exception:
            tier = 2
        base = self.TIER_DEFAULT_PRICE.get(tier, 35.0)
        return np.log(base)

    def transform(self, df):
        """
        将卡片数据DataFrame转换为特征矩阵

        Args:
            df: DataFrame, 需包含所有卡片属性列

        Returns:
            X: np.ndarray, shape (n_samples, 36)
        """
        if not self.is_fitted:
            raise RuntimeError("编码器尚未拟合，请先调用 fit()")

        n = len(df)
        X = np.zeros((n, len(FEATURE_NAMES)), dtype=np.float64)

        # ---- 球星效应: log(该球员Base卡均价) ----
        for i, (_, row) in enumerate(df.iterrows()):
            player = row.get("player_name", "")
            sp = self.star_power_map.get(player)
            X[i, 0] = sp if sp is not None else self._fallback_star_power(player)

        # ---- 基础特征 ----
        X[:, 1] = df["is_rookie"].values.astype(float)                           # is_rookie
        X[:, 2] = df["refraction_level"].values.astype(float)                    # refraction_level
        # serial_scarcity = 1/限量数, 未编号=0
        serial_max_vals = df["serial_max"].values.astype(float)
        with np.errstate(divide='ignore', invalid='ignore'):
            X[:, 3] = np.where(serial_max_vals > 0, 1.0 / serial_max_vals, 0.0)  # serial_scarcity
        X[:, 4] = df["is_jersey_match"].values.astype(float)                     # is_jersey_match
        X[:, 5] = df["auto_type"].values.astype(float)                           # auto_type (0-3)
        X[:, 6] = df["has_auto"].values.astype(float)                            # is_auto

        # ---- 物料特征 ----
        X[:, 7] = df["material_windows"].values.astype(float)                    # material_windows
        X[:, 8] = df["material_colors"].values.astype(float)                     # material_colors
        X[:, 9] = df["is_logoman"].values.astype(float)                          # is_logoman
        X[:, 10] = df["is_tag"].values.astype(float)                              # is_tag
        X[:, 11] = df["material_source"].values.astype(float)                     # material_source
        X[:, 12] = df["has_material"].values.astype(float)                        # has_material

        # ---- 评级特征 ----
        X[:, 13] = df["has_grade"].values.astype(float)                           # has_grade
        # grade_score: 归一化到 [0, 1], 无评级则为0
        grade_raw = df["grade_score"].values.astype(float)
        X[:, 14] = np.where(df["has_grade"].values == 1,
                            (grade_raw - 7.0) / 3.0, 0.0)                        # grade_score
        X[:, 15] = df["grade_grader"].values.astype(float)                        # grade_grader

        # ---- 产品系列 One-Hot (5维) ----
        product_col = df["product"].values
        for j, pname in enumerate(PRODUCT_NAMES):
            X[:, 16 + j] = (product_col == pname).astype(float)

        # ---- 年份特征 (3维) ----
        year_vals = df["card_year"].values.astype(float)
        X[:, 21] = (year_vals - MIN_YEAR) / (MAX_YEAR - MIN_YEAR)                # card_year_norm
        X[:, 22] = (year_vals <= 2015).astype(float)                              # is_vintage
        X[:, 23] = ((year_vals >= 2018) & (df["is_rookie"].values == 1)).astype(float)  # is_modern_rc

        # ---- 交互特征 (12维) ----
        star_power = X[:, 0]
        is_rookie = X[:, 1]
        ref_level = X[:, 2]
        serial_scarcity = X[:, 3]
        jersey_match = X[:, 4]
        is_auto = X[:, 6]
        is_logoman = X[:, 9]
        has_material = X[:, 12]
        grade_score_norm = X[:, 14]

        X[:, 24] = is_rookie * is_auto * has_material                             # rpa_effect
        X[:, 25] = is_logoman * (ref_level >= 5).astype(float)                    # logoman_1of1
        X[:, 26] = is_rookie * ref_level                                          # rookie_refraction
        X[:, 27] = is_rookie * is_auto                                            # rookie_auto
        X[:, 28] = is_rookie * grade_score_norm                                   # rookie_grade
        X[:, 29] = is_auto * has_material                                         # auto_material
        X[:, 30] = is_logoman * grade_score_norm                                  # logoman_grade
        X[:, 31] = jersey_match * is_auto                                         # jersey_auto
        X[:, 32] = star_power * is_rookie                                         # star_rookie
        X[:, 33] = serial_scarcity * ref_level                                    # scarcity_refraction
        X[:, 34] = (grade_score_norm > 0.9).astype(float) * is_rookie             # high_grade_rc
        X[:, 35] = (ref_level >= 3).astype(float) * star_power                    # superfractor_effect

        return X

    def fit_transform(self, df):
        """拟合并转换"""
        self.fit(df)
        return self.transform(df)

    def transform_single(self, card_dict):
        """
        转换单张卡片

        Args:
            card_dict: 包含卡片属性的字典

        Returns:
            X: np.ndarray, shape (1, 36)
        """
        df = pd.DataFrame([card_dict])
        # 确保所有必需的列存在
        required_cols = [
            "player_name", "product", "card_year", "is_rookie",
            "refraction_level", "serial_max", "is_jersey_match",
            "has_auto", "auto_type", "has_material",
            "material_windows", "material_colors", "is_logoman", "is_tag",
            "material_source", "has_grade", "grade_score", "grade_grader",
        ]
        for col in required_cols:
            if col not in df.columns:
                df[col] = 0  # 默认值

        return self.transform(df)

    def save(self, filepath):
        """保存编码器"""
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        joblib.dump({
            "star_power_map": self.star_power_map,
            "is_fitted": self.is_fitted,
        }, filepath)
        print(f"[编码器] 已保存到 {filepath}")

    @classmethod
    def load(cls, filepath):
        """加载编码器"""
        data = joblib.load(filepath)
        encoder = cls()
        encoder.star_power_map = data["star_power_map"]
        encoder.is_fitted = data["is_fitted"]
        print(f"[编码器] 已从 {filepath} 加载 ({len(encoder.star_power_map)} 名球员)")
        return encoder


def get_feature_names():
    """返回特征名称列表"""
    return FEATURE_NAMES.copy()


def get_feature_display_names():
    """返回用于UI展示的中文特征名称"""
    return {
        "star_power_log": "球星效应",
        "is_rookie": "新秀标识",
        "refraction_level": "折射等级",
        "serial_scarcity": "编号稀缺性",
        "is_jersey_match": "同背编号",
        "auto_type": "签字类型",
        "is_auto": "有签字",
        "material_windows": "物料窗口数",
        "material_colors": "物料颜色数",
        "is_logoman": "Logoman",
        "is_tag": "Tag物料",
        "material_source": "物料来源",
        "has_material": "有物料",
        "has_grade": "已评级",
        "grade_score": "评级分数",
        "grade_grader": "评级公司",
        "product_Prizm": "系列-Prizm",
        "product_Select": "系列-Select",
        "product_NT": "系列-NT",
        "product_Donruss": "系列-Donruss",
        "product_Mosaic": "系列-Mosaic",
        "card_year_norm": "年份",
        "is_vintage": "老卡(≤2015)",
        "is_modern_rc": "现代新秀(≥2018)",
        "rpa_effect": "RPA效应",
        "logoman_1of1": "Logoman×1/1",
        "rookie_refraction": "新秀×折射",
        "rookie_auto": "新秀×签字",
        "rookie_grade": "新秀×评级",
        "auto_material": "签字×物料",
        "logoman_grade": "Logoman×评级",
        "jersey_auto": "同背×签字",
        "star_rookie": "球星×新秀",
        "scarcity_refraction": "稀缺×折射",
        "high_grade_rc": "高分×新秀",
        "superfractor_effect": "超折射×球星",
    }
