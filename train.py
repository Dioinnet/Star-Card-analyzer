"""
端到端训练脚本
============
完整训练流程：加载数据（模拟 + 真实）→ 特征编码 → 训练XGBoost → 评估 → 保存模型

用法:
    python train.py                        # 仅模拟数据训练
    python train.py --real-data            # 混合 data/processed/ 中的真实数据
    python train.py --real-data --real-weight 3.0  # 真实数据权重 x3

数据来源优先级:
    1. data/processed/*.csv  — 经过 data_pipeline 清洗的 eBay 真实成交数据
    2. data/card_transactions.csv — 上次 generate_sample 生成的模拟数据
    3. 自动生成 5000 条模拟数据（如果以上都不存在）

输出:
    models/card_encoder.joblib  — 特征编码器
    models/xgb_card_pricing.joblib — XGBoost定价模型
"""

import sys
import os
import io
import time
import argparse

# 强制UTF-8编码，避免Windows GBK兼容问题
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.features.card_encoder import CardEncoder, get_feature_names, get_feature_display_names
from src.models.pricing_engine import PricingEngine


# ============================================================
# 数据加载
# ============================================================

COLUMN_MAPPING = {
    # eBay/管线输出 → 编码器期望
    "sold_price": "price",
    "total_price": "price",
    "final_price": "price",
    "player": "player_name",
    "brand_series": "product",
    "series": "product",
    "set_name": "product",
    "refraction": "refraction_level",
    "parallel": "refraction_name",
    "numbered_to": "serial_max",
    "print_run": "serial_max",
    "serial_num": "serial_number",
    "jersey_match": "is_jersey_match",
    "jersey_number_match": "is_jersey_match",
    "auto": "has_auto",
    "autograph": "has_auto",
    "signature_type": "auto_type",
    "memorabilia": "has_material",
    "game_used": "has_material",
    "patch_windows": "material_windows",
    "patch_colors": "material_colors",
    "logoman_flag": "is_logoman",
    "tag_flag": "is_tag",
    "mat_source": "material_source",
    "graded": "has_grade",
    "grade": "grade_score",
    "grader": "grade_grader",
}


def align_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    将不同来源的数据列名对齐到编码器期望的字段名

    Args:
        df: 原始 DataFrame（可能来自 eBay 爬虫或数据管线）

    Returns:
        列名标准化后的 DataFrame
    """
    df = df.copy()

    # 字段重命名
    rename_map = {}
    for src_col, target_col in COLUMN_MAPPING.items():
        if src_col in df.columns and target_col not in df.columns:
            rename_map[src_col] = target_col
    if rename_map:
        df = df.rename(columns=rename_map)

    # 确保必需字段存在（缺失的填默认值）
    required_defaults = {
        "player_name": "Unknown Player",
        "product": "Prizm",
        "card_year": 2022,
        "is_rookie": 0,
        "refraction_level": 0,
        "refraction_name": "Base",
        "serial_number": 0,
        "serial_max": 0,
        "is_jersey_match": 0,
        "has_auto": 0,
        "auto_type": 0,
        "auto_type_name": "None",
        "has_material": 0,
        "material_windows": 0,
        "material_colors": 0,
        "is_logoman": 0,
        "is_tag": 0,
        "material_source": 0,
        "material_source_name": "None",
        "has_grade": 0,
        "grade_score": 0.0,
        "grade_grader": 0,
        "grade_grader_name": "None",
        "player_team": "",
        "player_rc_year": 0,
    }

    for col, default in required_defaults.items():
        if col not in df.columns:
            df[col] = default

    # 类型修正（eBay 数据可能是字符串）
    int_cols = ["is_rookie", "refraction_level", "serial_number", "serial_max",
                "is_jersey_match", "has_auto", "auto_type", "has_material",
                "material_windows", "material_colors", "is_logoman", "is_tag",
                "material_source", "has_grade", "grade_grader"]
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    float_cols = ["price", "grade_score"]
    for col in float_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)

    return df


# ============================================================
# 主训练流程
# ============================================================

def main():
    """主训练流程"""
    parser = argparse.ArgumentParser(description="球星卡价值分析系统 — 模型训练")
    args = parser.parse_args()

    print("=" * 60)
    print("  球星卡价值分析系统 — 模型训练")
    print("=" * 60)

    # ============================================================
    # 第1步：加载 eBay + CardHobby 真实交易数据
    # ============================================================
    print(f"\n[第1步] 加载训练数据 (eBay + CardHobby 真实成交数据库)...")
    t0 = time.time()

    ebay_path = "data/ebay_comps_database.csv"
    ch_path = "data/cardhobby_comps_database.csv"

    dfs = []
    for path, label in [(ebay_path, "eBay"), (ch_path, "CardHobby")]:
        if os.path.exists(path):
            df_src = pd.read_csv(path)
            df_src = align_columns(df_src)
            df_src["data_source"] = label
            dfs.append(df_src)
            print(f"  [{label}] {len(df_src)} 条记录")
        else:
            print(f"  [{label}] 未找到 {path}，请先运行 scripts/build_comps_db.py")

    if not dfs:
        print("  [错误] 没有训练数据，退出")
        return

    df = pd.concat(dfs, ignore_index=True)
    # 去重(同球员+系列+年份+折射)
    df = df.drop_duplicates(subset=["player_name", "product", "card_year",
                                      "refraction_level", "serial_max", "has_auto",
                                      "has_material", "has_grade"],
                             keep="first")
    df["sample_weight"] = 1.0
    # 卡淘样本量小(几十条 vs eBay 上千条)，降权避免少量样本被树模型"背下"导致超拟合
    df.loc[df["data_source"] == "CardHobby", "sample_weight"] = 0.8

    print(f"  → 数据加载耗时: {time.time() - t0:.1f}s")

    print(f"\n  数据概览:")
    print(f"    总样本数: {len(df)}")
    print(f"    价格范围: ${df['price'].min():.2f} ~ ${df['price'].max():.2f}")
    print(f"    价格中位数: ${df['price'].median():.2f}")
    print(f"    价格均值: ${df['price'].mean():.2f}")
    for src, cnt in df["data_source"].value_counts().items():
        print(f"    {src}: {cnt} 条")
    print(f"    新秀卡比例: {df['is_rookie'].mean():.1%}")
    print(f"    签字卡比例: {df['has_auto'].mean():.1%}")
    print(f"    物料卡比例: {df['has_material'].mean():.1%}")

    # ============================================================
    # 第2步：特征编码
    # ============================================================
    print("\n[第2步] 特征编码...")
    t0 = time.time()

    encoder = CardEncoder()
    X = encoder.fit_transform(df)
    y = df["price"].values
    feature_names = get_feature_names()
    print(f"  → 特征矩阵: {X.shape}")
    print(f"  → 特征数量: {len(feature_names)}")
    print(f"  → 耗时: {time.time() - t0:.1f}s")

    # ============================================================
    # 第3步：拆分训练/测试集
    # ============================================================
    print("\n[第3步] 拆分训练/测试集 (80/20)...")
    # 同步拆分样本权重（卡淘降权，见数据加载处）
    weights = df["sample_weight"].values
    X_train, X_test, y_train, y_test, w_train, _ = train_test_split(
        X, y, weights, test_size=0.2, random_state=42,
    )
    print(f"  → 训练集: {len(X_train)} 样本")
    print(f"  → 测试集: {len(X_test)} 样本")

    # ============================================================
    # 第4步：训练定价引擎
    # ============================================================
    print("\n[第4步] 训练 XGBoost 定价引擎...")
    t0 = time.time()

    engine = PricingEngine(params={
        "n_estimators": 200,
        "max_depth": 5,
        "learning_rate": 0.05,
        "subsample": 0.7,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.5,
        "reg_lambda": 2.0,
        "min_child_weight": 4,
        "random_state": 42,
        "verbosity": 0,
        "objective": "reg:squarederror",
    })

    # 如果训练集同时包含真实和模拟数据，分别评估
    engine.fit(X_train, y_train, sample_weight=w_train)
    print(f"  → 训练耗时: {time.time() - t0:.1f}s")

    # ============================================================
    # 第5步：模型评估
    # ============================================================
    print("\n[第5步] 模型评估...")

    # 整体测试集评估
    metrics = engine.evaluate(X_test, y_test)
    print(f"  → 测试集整体 MAPE: {metrics['mape']:.2%}")
    print(f"  → 测试集 Log-RMSE: {metrics['rmse_log']:.4f}")
    print(f"  → 测试集 R² (log空间): {metrics['r2_log']:.4f}")

    # 分别评估 eBay 和 CardHobby 的误差
    if "data_source" in df.columns:
        for src_label in df["data_source"].unique():
            src_mask = df["data_source"] == src_label
            src_indices = np.where(src_mask.values)[0]
            test_src = np.intersect1d(src_indices, np.arange(len(X_test)))
            if len(test_src) > 0:
                src_metrics = engine.evaluate(X_test[test_src], y_test[test_src])
                print(f"  → {src_label} MAPE: {src_metrics['mape']:.2%} ({len(test_src)} 条)")

    # 训练集评估
    train_metrics = engine.evaluate(X_train, y_train)
    print(f"  → 训练集 MAPE: {train_metrics['mape']:.2%}")

    # ---- 价格区间准确率 ----
    print("\n  → 置信区间覆盖测试:")
    results = engine.predict(X_test[:200], return_attribution=False)
    if isinstance(results, dict):
        results = [results]
    in_ci = sum(
        1 for i, r in enumerate(results)
        if r["ci_low"] <= y_test[i] <= r["ci_high"]
    )
    print(f"    真实价格落在95%CI内的比例: {in_ci}/{len(results)} = {in_ci/len(results):.1%}")

    # ---- 特征重要性 Top-15 ----
    print("\n  → Top-15 特征重要性:")
    importance = engine.get_feature_importance()
    for rank, (name, imp) in enumerate(importance[:15], 1):
        bar = "█" * int(imp * 500)
        print(f"    {rank:2d}. {name:<20s} {imp:.4f} {bar}")

    # ============================================================
    # 第6步：预测示例
    # ============================================================
    print("\n[第6步] 预测示例...")

    sample_indices = []
    # 找一个RPA
    rpa_mask = (df["is_rookie"] == 1) & (df["has_auto"] == 1) & (df["has_material"] == 1)
    if rpa_mask.any():
        sample_indices.append(df[rpa_mask].index[0])
    # 找一个1of1
    one_mask = df["refraction_level"] == 5
    if one_mask.any():
        sample_indices.append(df[one_mask].index[0])
    # 展示一条 CardHobby 数据样本
    if "data_source" in df.columns:
        ch_mask = df["data_source"] == "CardHobby"
        if ch_mask.any():
            sample_indices.append(df[ch_mask].index[0])
    # 找一个Base卡
    base_mask = (df["refraction_level"] == 0) & (df["is_rookie"] == 0)
    if base_mask.any():
        sample_indices.append(df[base_mask].index[0])

    for label in sample_indices[:4]:
        # label 是 df 的实际行索引（drop_duplicates 后可能不连续）
        # 用 get_loc 转成 X 中的位置索引
        try:
            data_idx = df.index.get_loc(label)
        except (KeyError, TypeError):
            continue
        row = df.loc[label]
        X_sample = X[data_idx:data_idx+1]
        result = engine.predict(X_sample, return_attribution=True)

        source_tag = f" [{row.get('data_source', '')}]" if "data_source" in df.columns else ""
        print(f"\n  {'─' * 50}")
        print(f"  卡片: {row['player_name']} | {row['product']} | {row.get('refraction_name', 'Base')}{source_tag}")
        print(f"  年份: {row['card_year']} | 新秀: {'是' if row['is_rookie'] else '否'}")
        if row['has_auto']:
            print(f"  签字: {row.get('auto_type_name', 'Yes')}")
        if row['has_material']:
            print(f"  物料: {row['material_windows']}窗/{row['material_colors']}色 {'Logoman' if row['is_logoman'] else ''}")
        if row['has_grade']:
            print(f"  评级: {row.get('grade_grader_name', 'Graded')} {row['grade_score']}")
        print(f"  真实价格: ${row['price']:.2f}")
        print(f"  预估价格: ${result['price']:.2f}")
        print(f"  置信区间: ${result['ci_low']:.2f} ~ ${result['ci_high']:.2f}")
        if result.get("attribution"):
            print(f"  Top-5 归因:")
            sorted_attr = sorted(result["attribution"].items(),
                                 key=lambda x: abs(x[1]), reverse=True)[:5]
            for feat, contrib in sorted_attr:
                direction = "+" if contrib > 0 else ""
                print(f"    {feat}: {direction}${contrib:.2f}")

    # ============================================================
    # 第7步：保存模型
    # ============================================================
    print(f"\n{'=' * 60}")
    print("[第7步] 保存模型...")

    encoder_path = "models/card_encoder.joblib"
    model_path = "models/xgb_card_pricing.joblib"

    encoder.save(encoder_path)
    engine.save(model_path)

    print(f"  → 编码器: {encoder_path}")
    print(f"  → 模型: {model_path}")

    # ============================================================
    # 完成
    # ============================================================
    print(f"\n{'=' * 60}")
    print("  ✅ 训练完成！")
    print(f"  MAPE: {metrics['mape']:.2%}")
    print(f"  训练数据: eBay + CardHobby 真实成交数据库 ({len(df)} 条)")
    print(f"  现在可以运行: streamlit run app.py")
    print(f"  或启动API: uvicorn src.api.main:app --host 0.0.0.0 --port 8000")
    print(f"{'=' * 60}\n")

    return metrics


if __name__ == "__main__":
    main()
