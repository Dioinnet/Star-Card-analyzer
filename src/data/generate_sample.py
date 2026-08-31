"""
球星卡模拟交易数据生成器
=======================
生成符合真实市场规律的篮球卡交易数据，用于训练XGBoost定价模型。

价格生成逻辑（对数空间）：
  log_price = base_player + rookie_bonus + refraction_multiplier
            + serial_scarcity_effect + auto_bonus + material_bonus
            + grade_nonlinear_boost + rpa_synergy + interaction_effects + noise

关键市场规律：
  - 新秀溢价：新秀卡有额外乘数
  - 折射乘数：折射等级越高，价格指数级增长
  - 编号稀缺性：限量越少越贵，1/1 有极端溢价
  - RPA叠加效应：新秀+签字+物料同时存在时产生协同溢价
  - 评级非线性溢价：PSA10/BGS9.5以上溢价显著加速
  - Logoman + 1编1 = 天价卡
"""

import sys
import io
# 强制UTF-8编码，避免Windows GBK兼容问题
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np
import pandas as pd

# 从全联盟球员数据库加载
from src.data.player_db import (
    get_all_players, TIER_PRICE_RANGE,
    get_player_names_sorted, get_player_by_name,
)

# ============================================================
# 球员数据库（从 player_db 加载并计算 Base 卡均价）
# ============================================================
def _build_player_db():
    """从全联盟数据库构建生成器用的球员列表"""
    all_players = get_all_players()
    db = []
    for (name, jersey, rc_year, tier, pos, team) in all_players:
        price_min, price_max = TIER_PRICE_RANGE.get(tier, (1.0, 3.0))
        # 取区间中值加随机偏置作为Base卡均价
        base_price = round((price_min + price_max) / 2, 2)
        db.append((name, team, rc_year, base_price, jersey, tier))
    return db

PLAYER_DB = _build_player_db()

# ============================================================
# 产品系列配置
# ============================================================
PRODUCT_CONFIG = {
    "Prizm": {
        "base_multiplier": 0.8,       # 基础倍率
        "refraction_prob": [0.40, 0.25, 0.15, 0.10, 0.07, 0.03],  # Base/Silver/Gold/Mojo/Black/1of1
        "has_auto_prob": 0.25,
        "has_material_prob": 0.05,
        "typical_years": list(range(2012, 2025)),
    },
    "Select": {
        "base_multiplier": 1.0,
        "refraction_prob": [0.35, 0.25, 0.15, 0.12, 0.08, 0.05],
        "has_auto_prob": 0.30,
        "has_material_prob": 0.10,
        "typical_years": list(range(2013, 2025)),
    },
    "National Treasures": {
        "base_multiplier": 3.0,       # NT是高端系列
        "refraction_prob": [0.15, 0.15, 0.15, 0.20, 0.20, 0.15],
        "has_auto_prob": 0.70,        # NT签字比例高
        "has_material_prob": 0.50,    # NT物料比例高
        "typical_years": list(range(2012, 2025)),
    },
    "Donruss": {
        "base_multiplier": 0.5,
        "refraction_prob": [0.55, 0.25, 0.12, 0.05, 0.02, 0.01],
        "has_auto_prob": 0.15,
        "has_material_prob": 0.05,
        "typical_years": list(range(2014, 2025)),
    },
    "Mosaic": {
        "base_multiplier": 0.7,
        "refraction_prob": [0.38, 0.22, 0.16, 0.12, 0.08, 0.04],
        "has_auto_prob": 0.20,
        "has_material_prob": 0.08,
        "typical_years": list(range(2016, 2025)),
    },
}

# 折射等级名称映射
REFRACTION_NAMES = ["Base", "Silver", "Gold", "Mojo", "Black", "1of1"]

# 签字类型
AUTO_TYPES = ["None", "Sticker", "On-Card", "Inscription"]

# 物料来源
MATERIAL_SOURCES = ["None", "Jersey", "Game-Worn", "Prime"]

# 评级公司
GRADERS = ["None", "PSA", "BGS", "SGC"]

# 限量编号的典型分布（折射等级 -> (典型限量, 变体)）
SERIAL_CONFIG = {
    0: (None, None),      # Base: 不编号
    1: (None, None),      # Silver: 通常不编号
    2: (99, [49, 75, 99, 149, 199]),        # Gold: /49 ~ /199
    3: (25, [10, 25, 35, 49, 50]),          # Mojo: /10 ~ /50
    4: (5, [1, 3, 5, 8, 10, 15]),           # Black: /1 ~ /15
    5: (1, [1]),                              # 1of1
}


def _safe_log(x):
    """安全log变换"""
    return np.log(max(x, 0.01))


def generate_sample(n_samples=5000, random_seed=42):
    """
    生成模拟球星卡交易数据

    Args:
        n_samples: 样本数量
        random_seed: 随机种子

    Returns:
        pd.DataFrame: 包含卡片属性和成交价格的DataFrame
    """
    rng = np.random.default_rng(random_seed)
    data = []

    # 构建球员查找表 (name, team, rc_year, base_price, jersey, tier)
    player_names = [p[0] for p in PLAYER_DB]
    player_teams = [p[1] for p in PLAYER_DB]
    player_rc_years = [p[2] for p in PLAYER_DB]
    player_base_prices = np.array([p[3] for p in PLAYER_DB])
    player_jerseys = [p[4] for p in PLAYER_DB]
    player_tiers = [p[5] for p in PLAYER_DB]

    product_names = list(PRODUCT_CONFIG.keys())

    for i in range(n_samples):
        # ---- 选择球员 ----
        p_idx = rng.integers(0, len(PLAYER_DB))
        player_name = player_names[p_idx]
        player_team = player_teams[p_idx]
        player_rc_year = player_rc_years[p_idx]
        player_base_price = player_base_prices[p_idx]

        # ---- 选择产品系列 ----
        product = rng.choice(product_names)
        pconfig = PRODUCT_CONFIG[product]

        # ---- 选择年份 ----
        card_year = int(rng.choice(pconfig["typical_years"]))
        is_rookie = 1 if (card_year == player_rc_year) else 0

        # ---- 选择折射等级 ----
        ref_probs = np.array(pconfig["refraction_prob"])
        ref_probs = ref_probs / ref_probs.sum()  # 归一化
        refraction_level = int(rng.choice(len(REFRACTION_NAMES), p=ref_probs))
        refraction_name = REFRACTION_NAMES[refraction_level]

        # ---- 编号与稀缺性 ----
        serial_config = SERIAL_CONFIG[refraction_level]
        if serial_config[0] is not None:
            serial_max = int(rng.choice(serial_config[1]))
        else:
            # Base/Silver 有概率不编号 (90%不编号)
            if rng.random() < 0.90:
                serial_max = None
            else:
                # 偶有编号变体
                serial_max = int(rng.choice([49, 75, 99, 149, 199, 299]))

        if serial_max is not None:
            serial_number = int(rng.integers(1, serial_max + 1))
        else:
            serial_number = None

        # ---- 同背编检测（编号=球衣号）----
        player_jersey = player_jerseys[p_idx]
        is_jersey_match = 0
        if serial_number is not None and serial_number == player_jersey:
            is_jersey_match = 1

        # ---- 签字 ----
        has_auto = 1 if rng.random() < pconfig["has_auto_prob"] else 0
        if has_auto:
            # 签字类型分布：60%贴签 30%卡签 10%铭文签
            auto_type = int(rng.choice([1, 2, 3], p=[0.60, 0.30, 0.10]))
        else:
            auto_type = 0  # 无签字

        # ---- 物料 ----
        has_material = 1 if rng.random() < pconfig["has_material_prob"] else 0
        if has_material:
            material_windows = int(rng.choice([1, 1, 2, 2, 3, 4], p=[0.40, 0.25, 0.15, 0.10, 0.07, 0.03]))
            material_colors = int(min(rng.choice([1, 1, 2, 2, 3, 4], p=[0.35, 0.30, 0.18, 0.10, 0.05, 0.02]), material_windows + 1))
            # Logoman: 极稀有 (0.5%概率)
            is_logoman = 1 if rng.random() < 0.005 else 0
            # Tag: 稀有 (2%概率)
            is_tag = 1 if (not is_logoman and rng.random() < 0.02) else 0
            # 物料来源
            material_source = int(rng.choice([1, 2, 3], p=[0.45, 0.35, 0.20]))
        else:
            material_windows = 0
            material_colors = 0
            is_logoman = 0
            is_tag = 0
            material_source = 0

        # ---- 评级 ----
        has_grade = 1 if rng.random() < 0.30 else 0  # 30%卡片经过评级
        if has_grade:
            # 评级分数分布：新卡偏高分，老卡偏分散
            if card_year >= 2020:
                # 现代卡：基本9-10分
                grade_score = float(np.clip(rng.normal(9.5, 0.4), 7.0, 10.0))
            elif card_year >= 2015:
                grade_score = float(np.clip(rng.normal(9.0, 0.7), 6.0, 10.0))
            else:
                grade_score = float(np.clip(rng.normal(8.5, 1.0), 5.0, 10.0))
            grade_score = round(grade_score, 1)
            # BGS黑标10极为稀有
            grade_grader = int(rng.choice([1, 2, 3], p=[0.50, 0.30, 0.20]))
        else:
            grade_score = 0.0
            grade_grader = 0

        # ============================================================
        # 价格生成（对数空间）
        # ============================================================

        # 1. 基础价格 = 球员Base价 × 产品倍率
        log_base = _safe_log(player_base_price * pconfig["base_multiplier"])

        # 2. 新秀溢价
        rookie_bonus = 0.0
        if is_rookie:
            # 新秀溢价：超级新秀更大
            if player_rc_year >= 2022:  # 近年新秀更热
                rookie_bonus = _safe_log(2.5 + rng.normal(0, 0.3))
            elif player_rc_year >= 2018:
                rookie_bonus = _safe_log(2.0 + rng.normal(0, 0.25))
            else:
                rookie_bonus = _safe_log(1.8 + rng.normal(0, 0.3))

        # 3. 折射乘数（指数级增长）
        refraction_multipliers = {
            0: 1.0,     # Base
            1: 2.5,     # Silver
            2: 8.0,     # Gold
            3: 25.0,    # Mojo
            4: 80.0,    # Black
            5: 400.0,   # 1of1
        }
        ref_base = refraction_multipliers[refraction_level]
        # 加入随机噪声让价格有自然波动
        log_ref = _safe_log(ref_base * np.exp(rng.normal(0, 0.35)))

        # 4. 编号稀缺性效应
        log_serial = 0.0
        if serial_max is not None:
            # 稀缺性 = 1/限量数, 越稀缺溢价越高
            scarcity = 1.0 / serial_max
            # 1/1 极端溢价
            if serial_max == 1:
                log_serial = _safe_log(5.0 + rng.normal(0, 1.0))
            else:
                log_serial = _safe_log(1.0 + scarcity * 50 * np.exp(rng.normal(0, 0.5)))
            # 同背编额外溢价
            if is_jersey_match:
                log_serial += _safe_log(1.5 + rng.normal(0, 0.3))

        # 5. 签字溢价
        log_auto = 0.0
        if has_auto:
            auto_multipliers = {1: 2.0, 2: 3.5, 3: 6.0}  # 贴签/卡签/铭文签
            log_auto = _safe_log(auto_multipliers[auto_type] * np.exp(rng.normal(0, 0.4)))

        # 6. 物料溢价
        log_material = 0.0
        if has_material:
            mat_base = 1.0
            mat_base += material_windows * 0.3
            mat_base += material_colors * 0.5
            if is_logoman:
                mat_base += 15.0  # Logoman 天价
            if is_tag:
                mat_base += 3.0   # Tag 显著溢价
            mat_source_bonus = {1: 1.0, 2: 2.5, 3: 4.0}.get(material_source, 1.0)
            log_material = _safe_log(mat_base * mat_source_bonus * np.exp(rng.normal(0, 0.5)))

        # 7. 评级溢价（非线性）
        log_grade = 0.0
        if has_grade:
            # 评级溢价随分数非线性增长
            if grade_score >= 10.0:
                grade_mult = 8.0
            elif grade_score >= 9.5:
                grade_mult = 5.0
            elif grade_score >= 9.0:
                grade_mult = 3.0
            elif grade_score >= 8.5:
                grade_mult = 1.8
            elif grade_score >= 8.0:
                grade_mult = 1.2
            else:
                grade_mult = 0.8  # 低分反而折价
            # BGS 黑标溢价
            if grade_grader == 2 and grade_score >= 9.5:
                grade_mult *= 1.3
            log_grade = _safe_log(grade_mult * np.exp(rng.normal(0, 0.25)))

        # 8. RPA 协同效应（新秀×签字×物料 = 三者叠加超线性）
        log_rpa = 0.0
        if is_rookie and has_auto and has_material:
            # RPA 有惊人的协同溢价
            log_rpa = _safe_log(3.0 + rng.normal(0, 0.8))

        # 9. 关键交互效应
        log_interaction = 0.0
        # Logoman × 1of1 = 终极天价
        if is_logoman and serial_max == 1:
            log_interaction += _safe_log(10.0 + rng.normal(0, 1.5))
        # 新秀1of1
        if is_rookie and refraction_level == 5:
            log_interaction += _safe_log(2.0 + rng.normal(0, 0.8))
        # Wembanyama 效应 (超级新秀)
        if player_name == "Victor Wembanyama" and is_rookie:
            log_interaction += _safe_log(1.8 + rng.normal(0, 0.5))
        # James 1of1
        if player_name == "LeBron James" and refraction_level >= 4:
            log_interaction += _safe_log(1.5 + rng.normal(0, 0.6))

        # ---- 汇总价格 ----
        log_price = (
            log_base
            + rookie_bonus
            + log_ref
            + log_serial
            + log_auto
            + log_material
            + log_grade
            + log_rpa
            + log_interaction
            + rng.normal(0, 0.3)  # 最终随机噪声
        )
        price = round(np.exp(log_price), 2)
        # 确保价格合理（不低于$0.50）
        price = max(price, 0.50)

        # ---- 组装数据 ----
        record = {
            "player_name": player_name,
            "player_team": player_team,
            "player_rc_year": player_rc_year,
            "product": product,
            "card_year": card_year,
            "is_rookie": is_rookie,
            "refraction_level": refraction_level,
            "refraction_name": refraction_name,
            "serial_number": serial_number if serial_number is not None else 0,
            "serial_max": serial_max if serial_max is not None else 0,
            "is_jersey_match": is_jersey_match,
            "has_auto": has_auto,
            "auto_type": auto_type,
            "auto_type_name": AUTO_TYPES[auto_type],
            "has_material": has_material,
            "material_windows": material_windows,
            "material_colors": material_colors,
            "is_logoman": is_logoman,
            "is_tag": is_tag,
            "material_source": material_source,
            "material_source_name": MATERIAL_SOURCES[material_source],
            "has_grade": has_grade,
            "grade_score": grade_score,
            "grade_grader": grade_grader,
            "grade_grader_name": GRADERS[grade_grader],
            "price": price,
        }
        data.append(record)

    df = pd.DataFrame(data)

    # ---- 后处理：去除极端异常值 ----
    q01 = df["price"].quantile(0.01)
    q99 = df["price"].quantile(0.99)
    df = df[(df["price"] >= q01) & (df["price"] <= q99)].copy()

    print(f"[数据生成] 生成 {len(df)} 条模拟交易数据")
    print(f"[数据生成] 价格范围: ${df['price'].min():.2f} ~ ${df['price'].max():.2f}")
    print(f"[数据生成] 价格中位数: ${df['price'].median():.2f}")

    return df


if __name__ == "__main__":
    # 测试数据生成
    df = generate_sample(5000, random_seed=42)
    print(df.head())
    print(f"\n[统计] 各系列数量:\n{df['product'].value_counts()}")
    print(f"\n[统计] 新秀比例: {df['is_rookie'].mean():.1%}")
    print(f"\n[统计] 签字比例: {df['has_auto'].mean():.1%}")
    print(f"\n[统计] 物料比例: {df['has_material'].mean():.1%}")
    print(f"\n[统计] 评级比例: {df['has_grade'].mean():.1%}")
    print(f"\n[统计] RPA数量: {((df['is_rookie']==1)&(df['has_auto']==1)&(df['has_material']==1)).sum()}")
