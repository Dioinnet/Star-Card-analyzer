"""
评估服务：编码器 + 模型懒加载，供 FastAPI / Agent / Streamlit 复用
===================================================================
无 streamlit / fastapi 依赖，两进程均可 import。

用法:
    from src.services.pricing_service import load_models, evaluate_card_dict
    load_models()
    result = evaluate_card_dict(card_dict)
"""

import os

_encoder = None
_engine = None

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "models")
ENCODER_PATH = os.path.join(MODEL_DIR, "card_encoder.joblib")
MODEL_PATH = os.path.join(MODEL_DIR, "xgb_card_pricing.joblib")


def load_models():
    """懒加载编码器和模型（幂等，重复调用不重复加载）"""
    global _encoder, _engine

    if _encoder is not None and _engine is not None:
        return _encoder, _engine

    from src.features.card_encoder import CardEncoder
    from src.models.pricing_engine import PricingEngine

    if os.path.exists(ENCODER_PATH):
        _encoder = CardEncoder.load(ENCODER_PATH)
    else:
        print(f"[pricing_service] 警告: 编码器未找到 ({ENCODER_PATH})，请先运行 train.py")

    if os.path.exists(MODEL_PATH):
        _engine = PricingEngine.load(MODEL_PATH)
    else:
        print(f"[pricing_service] 警告: 模型未找到 ({MODEL_PATH})，请先运行 train.py")

    return _encoder, _engine


def is_loaded() -> bool:
    """模型是否已加载"""
    return _encoder is not None and _engine is not None and _engine.is_fitted


def evaluate_card_dict(card_dict: dict) -> dict:
    """
    评估一张卡片（CardRequest 同款字段 dict）

    Args:
        card_dict: 卡片属性（player_name/product/card_year/is_rookie/
                   refraction_level/serial_max/has_auto/...）

    Returns:
        {price, ci_low, ci_high, attribution(按|贡献|排序), special_flags}
        评估失败抛 RuntimeError
    """
    load_models()
    if _encoder is None or _engine is None:
        raise RuntimeError("模型尚未加载，请先运行 train.py 训练模型")

    card_dict = dict(card_dict)  # 不污染调用方

    # 确保包含编码器需要的补充字段
    if "player_team" not in card_dict:
        card_dict["player_team"] = ""
    if "player_rc_year" not in card_dict:
        card_dict["player_rc_year"] = (card_dict.get("card_year", 0)
                                       if card_dict.get("is_rookie") else 0)

    X = _encoder.transform_single(card_dict)
    result = _engine.predict(X, return_attribution=True)

    # ---- 特殊标记 ----
    special_flags = []
    if card_dict.get("is_rookie") and card_dict.get("has_auto") and card_dict.get("has_material"):
        special_flags.append("RPA (新秀+签字+物料三重叠加)")
    if card_dict.get("is_logoman") and card_dict.get("serial_max") == 1:
        special_flags.append("Logoman 1/1 (极度稀有)")
    if card_dict.get("is_jersey_match"):
        special_flags.append("同背编号 (号码匹配加成)")
    if card_dict.get("is_rookie") and card_dict.get("refraction_level") == 5:
        special_flags.append("新秀 1/1 (顶级稀有)")
    if card_dict.get("has_grade") and card_dict.get("grade_score") >= 10.0:
        special_flags.append("满分评级 (黑标级别)")

    # ---- 归因列表（按贡献绝对值排序） ----
    attribution_list = []
    if result.get("attribution"):
        sorted_items = sorted(result["attribution"].items(),
                              key=lambda x: abs(x[1]), reverse=True)
        attribution_list = [
            {"feature": feat, "contribution": float(contrib)}
            for feat, contrib in sorted_items
        ]

    return {
        "price": float(result["price"]),
        "ci_low": float(result["ci_low"]),
        "ci_high": float(result["ci_high"]),
        "attribution": attribution_list,
        "special_flags": special_flags,
    }
