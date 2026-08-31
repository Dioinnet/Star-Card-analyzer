"""
球星卡价值分析系统 — Streamlit 前端
==================================
交互式球星卡估价工具，左右分栏布局。

功能:
  - 左侧：卡片属性表单（球员/系列/折射/签字/物料/评级）
  - 右侧：预估价格 + SHAP 归因进度条
  - 侧边栏：卡淘真实成交案例（点击一键填入）
  - 自动校验新秀资格（年份不匹配时 RC 自动禁用）

用法:
    streamlit run app.py

前置条件:
    先运行 python train.py 生成模型文件
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import numpy as np
from typing import List
import time

# 页面配置（必须是第一个st命令）
st.set_page_config(
    page_title="球星卡价值分析系统",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",  # 默认展开侧边栏（展示参考样本）
)

from src.features.card_encoder import CardEncoder, get_feature_display_names
from src.models.pricing_engine import PricingEngine
from src.data.player_db import (
    get_player_names_sorted, get_player_by_name,
    get_team_names, TIER_PRICE_RANGE,
    get_player_image_url,
)
from src.data.player_honors import get_player_honors

# ============================================================
# 常量（从全联盟数据库动态加载）
# ============================================================
PLAYER_LIST = get_player_names_sorted()
TEAM_LIST = get_team_names()

PRODUCT_LIST = ["Prizm", "Select", "National Treasures", "Donruss", "Mosaic"]

REFRACTION_OPTIONS = {
    "Base (普卡)": 0,
    "Silver (银折)": 1,
    "Gold (金折)": 2,
    "Cracked Ice (碎冰折)": 2,
    "Mojo (马赛克折)": 3,
    "Blue (蓝折)": 3,
    "Purple (紫折)": 3,
    "Black (黑折)": 4,
    "1/1 (独一编)": 5,
}

# 按折射等级的兜底 label（_comps_row_to_sample 生成的 label 必须在此选项内）
BASE_REFRACTION_LABELS = ["Base (普卡)", "Silver (银折)", "Gold (金折)",
                          "Mojo (马赛克折)", "Black (黑折)", "1/1 (独一编)"]

AUTO_OPTIONS = {
    "无签字": (False, 0),
    "贴签 (Sticker Auto)": (True, 1),
    "卡签 (On-Card Auto)": (True, 2),
    "铭文签 (Inscription Auto)": (True, 3),
}

MATERIAL_SOURCE_OPTIONS = {
    "无物料": 0,
    "球衣料 (Jersey)": 1,
    "比赛穿 (Game-Worn)": 2,
    "Prime (高端切料)": 3,
}

GRADER_OPTIONS = {
    "未评级": (False, 0, 0.0),
    "PSA": (True, 1, 9.0),
    "BGS": (True, 2, 9.0),
    "SGC": (True, 3, 9.0),
}

# 年份范围：覆盖退役球星新秀卡（Kobe 1996 / Jordan 1984 等），2024 为最新系列年
YEAR_RANGE = list(range(2024, 1979, -1))


# ============================================================
# 自定义 CSS — 琉璃渐变 + 玻璃态风格
# ============================================================
def inject_custom_css():
    """注入自定义样式：琉璃色渐变背景 + 毛玻璃卡片"""

    # 琉璃色板
    glaze_teal = "#2dd4bf"
    glaze_cyan = "#22d3ee"
    glaze_blue = "#60a5fa"
    glaze_purple = "#a78bfa"
    glaze_rose = "#fb7185"

    text_primary = "#1e293b"
    text_secondary = "#64748b"
    text_tertiary = "#94a3b8"
    border_color = "#e2e8f0"
    bg_glass = "rgba(255,255,255,0.72)"
    bg_glass_hover = "rgba(255,255,255,0.88)"
    bg_input = "rgba(255,255,255,0.85)"

    shadow_card = "0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06)"
    shadow_hover = "0 4px 8px rgba(0,0,0,0.06), 0 12px 24px rgba(0,0,0,0.08)"
    radius = "10px"
    radius_lg = "16px"

    css = f"""
    <style>
    /* ===== 琉璃渐变全局背景 ===== */
    .stApp {{
        background: linear-gradient(160deg, #ecfeff 0%, #e0f2fe 15%, #f0fdf4 35%, #faf5ff 55%, #fff1f2 75%, #ecfeff 100%);
        background-attachment: fixed;
    }}
    .main {{
        background: transparent !important;
    }}

    /* ===== 标题 ===== */
    h1 {{
        color: #0f172a !important;
        font-weight: 700 !important;
        letter-spacing: -0.03em !important;
    }}
    h2, h3, h4 {{
        color: #1e293b !important;
        font-weight: 600 !important;
    }}

    /* ===== 侧边栏 — 毛玻璃 ===== */
    section[data-testid="stSidebar"] {{
        background: rgba(255,255,255,0.65) !important;
        backdrop-filter: blur(20px) saturate(1.4) !important;
        -webkit-backdrop-filter: blur(20px) saturate(1.4) !important;
        border-right: 1px solid rgba(0,0,0,0.06) !important;
    }}
    section[data-testid="stSidebar"] * {{
        color: {text_primary} !important;
    }}
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] small {{
        color: {text_secondary} !important;
    }}
    section[data-testid="stSidebar"] .stButton > button {{
        background: {bg_glass} !important;
        color: {text_primary} !important;
        border: 1px solid {border_color} !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
    }}
    section[data-testid="stSidebar"] .stButton > button:hover {{
        background: {bg_glass_hover} !important;
        border-color: {glaze_teal} !important;
    }}
    section[data-testid="stSidebar"] hr {{
        border-color: {border_color} !important;
    }}

    /* ===== 表单容器 — 毛玻璃 ===== */
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        background: {bg_glass} !important;
        backdrop-filter: blur(16px) saturate(1.3) !important;
        -webkit-backdrop-filter: blur(16px) saturate(1.3) !important;
        border: 1px solid rgba(255,255,255,0.6) !important;
        border-radius: {radius_lg} !important;
        box-shadow: {shadow_card} !important;
    }}

    /* ===== Selectbox ===== */
    div[data-baseweb="select"] > div {{
        background: {bg_input} !important;
        border: 1px solid {border_color} !important;
        border-radius: 8px !important;
        color: {text_primary} !important;
    }}
    div[data-baseweb="select"] > div:hover {{
        border-color: {glaze_teal} !important;
    }}
    div[data-baseweb="select"] span {{
        color: {text_primary} !important;
    }}
    div[data-baseweb="popover"] {{
        background: rgba(255,255,255,0.96) !important;
        backdrop-filter: blur(12px) !important;
        border: 1px solid {border_color} !important;
        border-radius: 10px !important;
        box-shadow: {shadow_hover} !important;
    }}
    div[data-baseweb="popover"] li {{
        color: {text_primary} !important;
    }}
    div[data-baseweb="popover"] li:hover {{
        background: #e0f2fe !important;
    }}

    /* ===== Number input ===== */
    div[data-testid="stNumberInput"] input {{
        background: {bg_input} !important;
        border: 1px solid {border_color} !important;
        border-radius: 8px !important;
        color: {text_primary} !important;
    }}
    div[data-testid="stNumberInput"] input:hover {{
        border-color: {glaze_teal} !important;
    }}
    div[data-testid="stNumberInput"] input:focus {{
        border-color: {glaze_teal} !important;
        box-shadow: 0 0 0 3px rgba(45,212,191,0.15) !important;
        outline: none !important;
    }}
    div[data-testid="stNumberInput"] button {{
        background: {bg_glass} !important;
        color: {text_secondary} !important;
        border-color: {border_color} !important;
    }}

    /* ===== Checkbox / Slider ===== */
    label[data-baseweb="checkbox"] span {{
        color: {text_primary} !important;
    }}
    div[data-testid="stSlider"] div[role="slider"] {{
        background: {glaze_teal} !important;
    }}

    /* ===== 主按钮 — 琉璃渐变 ===== */
    .stButton > button {{
        border-radius: 8px !important;
        font-weight: 600 !important;
        transition: all 0.25s ease !important;
    }}
    .stButton > button[kind="primary"] {{
        background: linear-gradient(135deg, {glaze_teal}, {glaze_blue}) !important;
        color: #fff !important;
        border: none !important;
        box-shadow: 0 2px 8px rgba(45,212,191,0.25) !important;
    }}
    .stButton > button[kind="primary"]:hover {{
        background: linear-gradient(135deg, #2bc4b0, #5098ed) !important;
        box-shadow: 0 6px 20px rgba(45,212,191,0.35) !important;
        transform: translateY(-1px) !important;
    }}

    /* ===== 动画 ===== */
    @keyframes fadeInUp {{
        from {{ opacity: 0; transform: translateY(16px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}
    @keyframes countUp {{
        from {{ opacity: 0; transform: scale(0.92); }}
        to   {{ opacity: 1; transform: scale(1); }}
    }}

    /* ===== 价格卡片 — 毛玻璃 ===== */
    .price-hero-card {{
        background: {bg_glass};
        backdrop-filter: blur(18px) saturate(1.5);
        -webkit-backdrop-filter: blur(18px) saturate(1.5);
        border: 1px solid rgba(255,255,255,0.5);
        border-radius: {radius_lg};
        padding: 28px 20px 20px 20px;
        text-align: center;
        animation: fadeInUp 0.5s ease-out;
        box-shadow: {shadow_card};
        margin-bottom: 14px;
    }}
    .price-hero-card:hover {{
        background: {bg_glass_hover};
        box-shadow: {shadow_hover};
        transition: all 0.3s ease;
    }}
    .price-value {{
        font-size: 3em;
        font-weight: 700;
        color: #0f172a;
        animation: countUp 0.6s ease-out;
        margin: 10px 0;
    }}
    .price-ci {{
        color: {text_tertiary};
        font-size: 0.9em;
        margin-top: 4px;
    }}

    /* ===== 置信度徽章 ===== */
    .confidence-badge {{
        display: inline-block;
        padding: 4px 14px;
        border-radius: 20px;
        font-size: 0.8em;
        font-weight: 500;
        margin-top: 10px;
    }}
    .confidence-high   {{ background: #ecfdf5; color: #059669; border: 1px solid #a7f3d0; }}
    .confidence-medium {{ background: #fffbeb; color: #d97706; border: 1px solid #fde68a; }}
    .confidence-low    {{ background: #fff1f2; color: #e11d48; border: 1px solid #fecdd3; }}

    /* ===== 特殊标记 ===== */
    .flag-tag {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 0.78em;
        font-weight: 500;
        margin: 3px 4px;
        animation: fadeInUp 0.4s ease-out;
    }}
    .flag-rpa    {{ background: #fffbeb; color: #b45309; border: 1px solid #fde68a; }}
    .flag-oneone {{ background: #fff1f2; color: #be123c; border: 1px solid #fecdd3; }}
    .flag-match  {{ background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }}
    .flag-grade  {{ background: #f0f9ff; color: #0369a1; border: 1px solid #bae6fd; }}

    /* ===== Comp 行 ===== */
    .comp-row {{
        padding: 10px 14px;
        border-radius: 8px;
        margin: 4px 0;
        background: rgba(255,255,255,0.55);
        border: 1px solid transparent;
        animation: fadeInUp 0.35s ease-out;
        transition: all 0.2s ease;
    }}
    .comp-row:hover {{
        background: rgba(255,255,255,0.85);
        border-color: {border_color};
        transform: translateX(4px);
        box-shadow: {shadow_card};
    }}

    /* ===== 侧边栏样本卡片 ===== */
    .sidebar-sample-card {{
        background: rgba(255,255,255,0.6);
        border: 1px solid {border_color};
        border-radius: 8px;
        padding: 10px 12px;
        margin: 8px 0;
        transition: all 0.2s ease;
    }}
    .sidebar-sample-card:hover {{
        background: rgba(255,255,255,0.85);
        border-color: {glaze_teal};
        box-shadow: {shadow_card};
    }}

    /* ===== Tab ===== */
    div[data-baseweb="tab-list"] {{
        background: transparent !important;
        border-bottom: 1px solid {border_color} !important;
    }}
    button[data-baseweb="tab"] {{
        color: {text_tertiary} !important;
        font-weight: 500 !important;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        color: {glaze_teal} !important;
        border-bottom: 2px solid {glaze_teal} !important;
    }}

    /* ===== Expander ===== */
    details[data-testid="stExpander"] {{
        background: {bg_glass} !important;
        border: 1px solid {border_color} !important;
        border-radius: 8px !important;
    }}

    /* ===== Alert ===== */
    div[data-testid="stAlert"] {{
        border-radius: 8px !important;
    }}

    /* ===== Caption / small ===== */
    .stMarkdown small, .stMarkdown caption {{
        color: {text_tertiary} !important;
    }}

    /* ===== SHAP 归因条 ===== */
    .shap-bar-positive {{
        background: linear-gradient(90deg, {glaze_teal}, {glaze_blue}) !important;
    }}
    .shap-bar-negative {{
        background: linear-gradient(90deg, {glaze_rose}, #f97316) !important;
    }}

    /* ===== 分割线 ===== */
    hr {{
        border-color: {border_color} !important;
    }}

    /* ===== 通用文字 ===== */
    .stMarkdown p {{
        color: {text_primary};
        font-size: 14px;
        line-height: 1.6;
    }}

    /* ===== 选中文字 ===== */
    ::selection {{
        background: #ccfbf1;
        color: #0f172a;
    }}

    @media (max-width: 768px) {{
        .price-value {{ font-size: 2em; }}
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


# ============================================================
# CardHobby 真实成交参考样本（兜底）
# 仅当卡淘真实数据为空时展示；结构供 apply_sample 使用
# ============================================================
CARDHOBBY_REFERENCE_SAMPLES = [
    {
        "title": "🛒 Santi Aldama 2021 Gold折 新秀RC",
        "description": "Santi Aldama 2021 金折新秀卡 — 灰熊轮换内线",
        "card": {
            "player_name": "Santi Aldama",
            "product": "Prizm",
            "card_year": 2021,
            "is_rookie": True,
            "refraction_label": "Gold (金折)",
            "serial_number": 0,
            "serial_max": 149,
            "auto_label": "无签字",
            "has_material": False,
            "material_windows": 1,
            "material_colors": 1,
            "is_logoman": False,
            "is_tag": False,
            "material_source_label": "无物料",
            "grader_label": "未评级",
            "grade_score": 0.0,
        },
        "real_price_note": "卡淘最近成交: ¥1,000 (2026-09-06)",
    },
    {
        "title": "🛒 James Bouknight 2021 1/1折 新秀RC",
        "description": "James Bouknight 2021 独一编新秀卡 — 稀缺 1/1",
        "card": {
            "player_name": "James Bouknight",
            "product": "Prizm",
            "card_year": 2021,
            "is_rookie": True,
            "refraction_label": "1/1 (独一编)",
            "serial_number": 1,
            "serial_max": 1,
            "auto_label": "无签字",
            "has_material": False,
            "material_windows": 1,
            "material_colors": 1,
            "is_logoman": False,
            "is_tag": False,
            "material_source_label": "无物料",
            "grader_label": "未评级",
            "grade_score": 0.0,
        },
        "real_price_note": "卡淘最近成交: ¥4,000 (2026-08-06)",
    },
    {
        "title": "🛒 Myles Turner 2025 Silver折",
        "description": "Myles Turner 2025 银折 — 步行者护框中锋",
        "card": {
            "player_name": "Myles Turner",
            "product": "Prizm",
            "card_year": 2025,
            "is_rookie": False,
            "refraction_label": "Silver (银折)",
            "serial_number": 0,
            "serial_max": 0,
            "auto_label": "无签字",
            "has_material": False,
            "material_windows": 1,
            "material_colors": 1,
            "is_logoman": False,
            "is_tag": False,
            "material_source_label": "无物料",
            "grader_label": "未评级",
            "grade_score": 0.0,
        },
        "real_price_note": "卡淘最近成交: ¥180 (2026-08-06)",
    },
    {
        "title": "🛒 Victor Wembanyama 2023 Silver折 新秀RC",
        "description": "Victor Wembanyama 新秀银折 — 当前市场最热新秀",
        "card": {
            "player_name": "Victor Wembanyama",
            "product": "Prizm",
            "card_year": 2023,
            "is_rookie": True,
            "refraction_label": "Silver (银折)",
            "serial_number": 0,
            "serial_max": 0,
            "auto_label": "无签字",
            "has_material": False,
            "material_windows": 1,
            "material_colors": 1,
            "is_logoman": False,
            "is_tag": False,
            "material_source_label": "无物料",
            "grader_label": "PSA",
            "grade_score": 10.0,
        },
        "real_price_note": "卡淘最近成交: ¥20,000 (2026-08-01)",
    },
]


# ============================================================
# 可比成交数据库 (CardHobby 卡淘)
# ============================================================
COMPS_CH_PATH = "data/cardhobby_comps_database.csv"
COMPS_PER_PAGE = 5  # 每页显示条数

# ---- 真实成交记录 → 侧边栏样本 的字段映射 ----
_REFRACTION_LABEL_BY_NAME = {
    "base": "Base (普卡)",
    "silver": "Silver (银折)",
    "gold": "Gold (金折)",
    "mojo": "Mojo (马赛克折)",
    "black": "Black (黑折)",
    "1of1": "1/1 (独一编)",
    "1/1": "1/1 (独一编)",
    "cracked ice": "Cracked Ice (碎冰折)",
    "碎冰": "Cracked Ice (碎冰折)",
    "blue": "Blue (蓝折)",
    "purple": "Purple (紫折)",
    "pink": "Pink (粉折)",
    "red": "Red (红折)",
    "green": "Green (绿折)",
    "orange": "Orange (橙折)",
    "lava": "Lava (熔岩折)",
    "disco": "Disco (迪斯科折)",
    "checkerboard": "Checkerboard (棋盘折)",
}
_AUTO_LABEL_BY_NAME = {
    "none": "无签字",
    "sticker": "贴签 (Sticker Auto)",
    "on-card": "卡签 (On-Card Auto)",
    "inscription": "铭文签 (Inscription Auto)",
}


def _comps_row_to_sample(row: pd.Series) -> dict:
    """
    将 comps 数据库中的一条真实成交记录转换为侧边栏样本格式
    （与 CARDHOBBY_REFERENCE_SAMPLES 的 card 字段结构一致，供 apply_sample 使用）
    """
    # 折射 label：优先按名称匹配，回退按等级；
    # 最终必须落在表单 selectbox 的 REFRACTION_OPTIONS 选项内，否则填入会崩
    ref_name = str(row.get("refraction_name", "")).lower()
    ref_label = _REFRACTION_LABEL_BY_NAME.get(ref_name)
    if not ref_label or ref_label not in REFRACTION_OPTIONS:
        ref_label = BASE_REFRACTION_LABELS[
            min(int(row.get("refraction_level", 0)), 5)]

    # 签字 label
    auto_name = str(row.get("auto_type_name", "None")).lower()
    auto_label = _AUTO_LABEL_BY_NAME.get(auto_name, "无签字")

    # 评级 label
    grader_name = str(row.get("grade_grader_name", "None"))
    grader_label = grader_name if grader_name in GRADER_OPTIONS else "未评级"

    # 产品系列：仅支持 UI 列表内的系列
    product = row.get("product", "Prizm")
    if product not in PRODUCT_LIST:
        product = "Prizm"

    # 货币：卡淘数据恒有 price_cny → 显示人民币（缺失时防御性回退 price）
    if "price_cny" in row.index and row.get("price_cny") not in (None, "", 0):
        price = float(row.get("price_cny", 0.0))
    else:
        price = float(row.get("price", 0.0))
    price_note = f"卡淘最近成交: ¥{price:,.0f}"
    sold_date = str(row.get("sold_date", ""))
    title = str(row.get("title", ""))[:70]

    # 描述：球员 + 年份 + 系列 + 折射
    desc_parts = [
        str(row.get("player_name", "Unknown")),
        f"{int(row.get('card_year', 0))}" if row.get("card_year") else "",
    ]
    desc = " ".join(p for p in desc_parts if p)
    ref_disp = ref_label.split(" (")[0]
    if ref_disp != "Base":
        desc += f" {ref_disp}折"
    if row.get("is_rookie"):
        desc += " 新秀RC"
    if row.get("has_grade"):
        desc += f" {grader_label}{row.get('grade_score', '')}"
    if sold_date:
        desc += f" · {sold_date}"

    # 物料卡必须有 ≥1 窗/色（标题未标明窗数时默认为 1，避免表单校验崩溃）
    has_mat = bool(row.get("has_material", 0))
    mat_windows = int(row.get("material_windows", 0))
    mat_colors = int(row.get("material_colors", 0))
    if has_mat:
        mat_windows = max(mat_windows, 1)
        mat_colors = max(mat_colors, 1)

    return {
        "title": f"🛒 {desc}",
        "description": desc,
        "card": {
            "player_name": str(row.get("player_name", "Unknown Player")),
            "product": product,
            "card_year": int(row.get("card_year", 2022)),
            "is_rookie": bool(row.get("is_rookie", 0)),
            "refraction_label": ref_label,
            "serial_number": int(row.get("serial_number", 0)),
            "serial_max": int(row.get("serial_max", 0)),
            "auto_label": auto_label,
            "has_material": has_mat,
            "material_windows": mat_windows,
            "material_colors": mat_colors,
            "is_logoman": bool(row.get("is_logoman", 0)),
            "is_tag": bool(row.get("is_tag", 0)),
            "material_source_label": "无物料",
            "grader_label": grader_label,
            "grade_score": float(row.get("grade_score", 0.0)),
        },
        "real_price_note": price_note
                           + (f" ({sold_date})" if sold_date else ""),
    }


# 低质/无代表性标题（多人拼盘、混卡 lot 等）不参与侧边栏展示
_LOW_VALUE_TITLE_KEYWORDS = [
    "lot", "拼盘", "组队", "全家福", "多选", "套装", "多人", "混卡",
]

# 球员 tier → 代表性权重（tier 越小越有代表性；未收录球员取 2.5）
_REP_TIER_WEIGHT = {0: 5.0, 1: 4.0, 2: 3.0, 3: 2.5, 4: 2.0, 5: 1.5}


def _build_tier_map() -> dict:
    """球员名 → tier 的映射（用于代表性评分）"""
    try:
        from src.data.player_db import get_all_players
        return {p[0]: float(p[3]) for p in get_all_players()}
    except Exception:
        return {}


def _representative_score(row: pd.Series, tier_map: dict) -> float:
    """代表性评分：球星热度为主，稀缺/签字加分，垃圾记录降权"""
    name = str(row.get("player_name", ""))
    tier = tier_map.get(name, 2.5)
    score = _REP_TIER_WEIGHT.get(int(tier) if float(tier) == int(tier) else tier,
                                 2.5) * 10.0
    # 稀缺/折射/签字 → 展示价值加分
    if int(row.get("serial_max", 0) or 0) > 0:
        score += 3.0
    if int(row.get("refraction_level", 0) or 0) > 0:
        score += 2.0
    if int(row.get("has_auto", 0) or 0) > 0:
        score += 2.0
    # 超低价垃圾降权
    price = float(row.get("price", 0.0) or 0.0)
    if 0 < price < 1.0:
        score -= 5.0
    return score


def _load_recent_samples(csv_path: str, n: int, filter_basketball: bool) -> List[dict]:
    """
    从 comps CSV 读取真实成交记录作为侧边栏参考样本（共用逻辑）

    挑选策略（2026-08）：不再单纯按时间取最近 n 条，而是按"球星代表性"挑选——
    优先知名球星（tier 靠前），同 tier 内稀缺/折射/签字卡加分，每名球员最多 1 条，
    确保侧边栏覆盖不同球星而非撞车/冷门凑套卡。

    Args:
        csv_path: CSV 路径
        n: 取 n 条
        filter_basketball: 是否过滤非篮球卡（卡淘为全品类平台需过滤）
    """
    from src.data.player_db import is_basketball_card_title

    if not os.path.exists(csv_path):
        return []
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return []
    if df.empty or "price" not in df.columns:
        return []

    # 只保留篮球卡（卡淘为全品类平台，过滤足球/F1/漫威等）
    if filter_basketball and "title" in df.columns:
        df = df[df["title"].map(is_basketball_card_title)]
        if df.empty:
            return []

    # 过滤无参考价值的起拍价记录（卡淘 ¥10 以下多为 ¥1 起拍价，非真实市场价）
    if "price_cny" in df.columns and filter_basketball:
        df_good = df[pd.to_numeric(df["price_cny"], errors="coerce").fillna(0) >= 10]
        if df_good.empty:
            # 数据少时放宽到 ¥5
            df_good = df[pd.to_numeric(df["price_cny"], errors="coerce").fillna(0) >= 5]
        if not df_good.empty:
            df = df_good

    # 过滤多人拼盘 lot 等无代表性标题
    if "title" in df.columns:
        low_mask = df["title"].astype(str).str.lower().str.contains(
            "|".join(_LOW_VALUE_TITLE_KEYWORDS), na=False)
        df = df[~low_mask]

    # 去重（同一球员+系列+年份+价格只留一条）
    dedup_cols = [c for c in ("player_name", "product", "card_year", "price")
                  if c in df.columns]
    if dedup_cols:
        df = df.drop_duplicates(subset=dedup_cols, keep="first")

    # 代表性排序（球星热度优先；同分时按成交日期新的优先）
    tier_map = _build_tier_map()
    df["_rep_score"] = df.apply(lambda r: _representative_score(r, tier_map), axis=1)
    if "sold_date" in df.columns:
        df["_sold_sort"] = pd.to_datetime(df["sold_date"], errors="coerce")
        df = df.sort_values(["_rep_score", "_sold_sort"],
                            ascending=[False, False], na_position="last")
    else:
        df = df.sort_values("_rep_score", ascending=False)
    # 每名球员最多 1 条，保证覆盖不同球星
    df = df.drop_duplicates(subset=["player_name"], keep="first")
    df = df.head(n)

    samples = []
    for _, row in df.iterrows():
        try:
            samples.append(_comps_row_to_sample(row))
        except Exception:
            continue
    return samples


def load_cardhobby_recent_samples(n: int = 5) -> List[dict]:
    """卡淘最近成交（篮球卡，人民币价格），CSV 缺失返回 []"""
    return _load_recent_samples(COMPS_CH_PATH, n, filter_basketball=True)


@st.cache_data
def load_comps_cardhobby():
    """加载 CardHobby 可比成交数据库"""
    if not os.path.exists(COMPS_CH_PATH):
        return pd.DataFrame()
    df = pd.read_csv(COMPS_CH_PATH)
    df["source_label"] = "CardHobby"
    return df


def compute_similarity(card: dict, comp: dict) -> float:
    """
    计算输入卡片与一条 comp 记录的相似度得分。

    评分维度（满分 100）：
      - 球员匹配: 25 分（完全匹配）或 10 分（同层级）
      - 产品系列: 15 分（完全匹配）
      - 年份差: 10 分（同年）→ 7→4→2→0
      - 折射等级: 20 分（完全匹配）或 10 分（相邻等级）
      - 新秀标识: 7 分
      - 签字匹配: 8 分
      - 物料匹配: 5 分
      - 评级匹配: 5 分
      - 时间新鲜度加成: 最多 5 分（30天内=5，90天内=3，更早=0）
    """
    score = 0.0

    # 1. 球员匹配
    if card.get("player_name") == comp.get("player_name"):
        score += 25.0
    else:
        # 同层级也算部分匹配
        card_p_info = get_player_by_name(card.get("player_name", ""))
        comp_p_info = get_player_by_name(str(comp.get("player_name", "")))
        if card_p_info and comp_p_info and card_p_info["tier"] == comp_p_info["tier"]:
            score += 10.0

    # 2. 产品系列
    if card.get("product") == comp.get("product"):
        score += 15.0

    # 3. 年份差
    card_year = card.get("card_year", 0)
    comp_year = comp.get("card_year", 0)
    year_diff = abs(card_year - comp_year)
    if year_diff == 0:
        score += 10.0
    elif year_diff == 1:
        score += 7.0
    elif year_diff == 2:
        score += 4.0
    elif year_diff <= 4:
        score += 2.0

    # 4. 折射等级
    card_ref = card.get("refraction_level", 0)
    comp_ref = comp.get("refraction_level", 0)
    if card_ref == comp_ref:
        score += 20.0
    elif abs(card_ref - comp_ref) <= 1:
        score += 10.0

    # 5. 新秀标识
    if card.get("is_rookie") == comp.get("is_rookie"):
        score += 7.0

    # 6. 签字匹配（有无签字 + 签字类型）
    card_has_auto = card.get("has_auto", 0)
    comp_has_auto = comp.get("has_auto", 0)
    if card_has_auto == comp_has_auto:
        score += 4.0
        if card_has_auto and comp_has_auto:
            if card.get("auto_type", 0) == comp.get("auto_type", 0):
                score += 4.0
    else:
        score += 1.0

    # 7. 物料匹配
    if card.get("has_material", 0) == comp.get("has_material", 0):
        score += 5.0

    # 8. 评级匹配
    if card.get("has_grade", 0) == comp.get("has_grade", 0):
        score += 5.0

    # 9. 时间新鲜度加成（越近越有参考价值）
    sold_date_str = str(comp.get("sold_date", ""))
    try:
        sold_date = pd.to_datetime(sold_date_str)
        days_ago = (pd.Timestamp.now() - sold_date).days
        if days_ago <= 7:
            score += 5.0
        elif days_ago <= 30:
            score += 3.0
        elif days_ago <= 90:
            score += 1.0
    except Exception:
        pass

    return round(score, 1)


def find_similar_comps(card_dict: dict, top_k: int = 20,
                       min_similarity: float = 15.0) -> pd.DataFrame:
    """
    从卡淘 comps 数据库中找出与输入卡片最相似的 k 条已售记录。

    Args:
        card_dict: 用户输入的卡片属性
        top_k: 返回前 k 条
        min_similarity: 最低匹配分数，低于此的不返回

    Returns:
        DataFrame，按相似度降序排列
    """
    comps_df = load_comps_cardhobby()

    if comps_df.empty:
        return comps_df

    comp_records = comps_df.to_dict("records")
    scored = []
    for comp in comp_records:
        sim = compute_similarity(card_dict, comp)
        if sim >= min_similarity:
            scored.append({**comp, "similarity": sim})

    if not scored:
        return pd.DataFrame()

    result = pd.DataFrame(scored)
    result = result.sort_values("similarity", ascending=False)
    return result.head(top_k)


def find_price_matches(estimated_price: float, tolerance: float = 0.35,
                       top_k: int = 24) -> pd.DataFrame:
    """
    按价格匹配：找出与预估价在同一区间的卡淘卡片。

    Args:
        estimated_price: 模型预估价（人民币）
        tolerance: 价格浮动范围（默认 ±35%）
        top_k: 返回前 k 条（按价格最接近排序）

    Returns:
        DataFrame，按价格接近度升序排列
    """
    comps_df = load_comps_cardhobby()
    price_col = "price_cny" if "price_cny" in (comps_df.columns if not comps_df.empty else []) else "price"

    if comps_df.empty:
        return comps_df

    lo = estimated_price * (1 - tolerance)
    hi = estimated_price * (1 + tolerance)

    # 价格区间筛选
    in_range = comps_df[
        (comps_df[price_col] >= lo) & (comps_df[price_col] <= hi)
    ].copy()

    if in_range.empty:
        return in_range

    # 按价格接近度排序
    in_range["_price_diff"] = abs(in_range[price_col] - estimated_price)
    in_range = in_range.sort_values("_price_diff")
    return in_range.head(top_k)


# ============================================================
# 模型加载（缓存）
# ============================================================
@st.cache_resource
def load_models():
    """加载编码器和定价模型（仅首次加载，后续使用缓存）"""
    encoder_path = "models/card_encoder.joblib"
    model_path = "models/xgb_card_pricing.joblib"

    if not os.path.exists(encoder_path) or not os.path.exists(model_path):
        st.error("❌ 模型文件未找到！请先运行 `python train.py` 训练模型。")
        st.stop()

    encoder = CardEncoder.load(encoder_path)
    engine = PricingEngine.load(model_path)
    return encoder, engine


# ============================================================
# Session State 初始化
# ============================================================
def init_session_state():
    """初始化 session_state 中的表单默认值"""
    defaults = {
        "sel_player": "Victor Wembanyama",
        "sel_product": "Prizm",
        "sel_year": 2023,
        "sel_is_rookie": True,
        "sel_refraction": "Base (普卡)",
        "sel_serial_num": 0,
        "sel_serial_max": 0,
        "sel_auto": "无签字",
        "sel_has_material": False,
        "sel_mat_windows": 1,
        "sel_mat_colors": 1,
        "sel_is_logoman": False,
        "sel_is_tag": False,
        "sel_mat_source": "无物料",
        "sel_grader": "未评级",
        "sel_grade_score": 0.0,
        "evaluated": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def apply_sample(sample_card: dict):
    """将参考样本的卡片属性写入 session_state — 同步更新 sel_* 和 widget_* 两级 key"""
    # 球员不在下拉选项列表 → 动态加入（防止 selectbox 回退到列表第一个球员，
    # 导致"点击 Bouknight 案例却评估成 AJ Green"这类错误）
    pname = str(sample_card.get("player_name", "")).strip()
    if pname and pname not in PLAYER_LIST:
        extras = list(st.session_state.get("extra_players", []))
        if pname not in extras:
            extras.append(pname)
        st.session_state["extra_players"] = extras

    # sel_* 变量（表单逻辑用）
    st.session_state["sel_player"]       = sample_card["player_name"]
    st.session_state["sel_product"]      = sample_card["product"]
    st.session_state["sel_year"]         = sample_card["card_year"]
    st.session_state["sel_is_rookie"]    = sample_card["is_rookie"]
    st.session_state["sel_refraction"]   = sample_card["refraction_label"]
    st.session_state["sel_serial_num"]   = sample_card["serial_number"]
    st.session_state["sel_serial_max"]   = sample_card["serial_max"]
    st.session_state["sel_auto"]         = sample_card["auto_label"]
    st.session_state["sel_has_material"] = sample_card["has_material"]
    st.session_state["sel_mat_windows"]  = sample_card["material_windows"]
    st.session_state["sel_mat_colors"]   = sample_card["material_colors"]
    st.session_state["sel_is_logoman"]   = sample_card["is_logoman"]
    st.session_state["sel_is_tag"]       = sample_card["is_tag"]
    st.session_state["sel_mat_source"]   = sample_card.get("material_source_label", "无物料")
    st.session_state["sel_grader"]       = sample_card["grader_label"]
    st.session_state["sel_grade_score"]  = sample_card["grade_score"]

    # widget_* 内部 key（Streamlit 控件用，不覆写则 UI 不刷新）
    st.session_state["widget_player"]    = sample_card["player_name"]
    st.session_state["widget_product"]   = sample_card["product"]
    st.session_state["widget_year"]      = sample_card["card_year"]
    st.session_state["widget_rookie"]    = sample_card["is_rookie"]
    st.session_state["widget_ref"]       = sample_card["refraction_label"]
    st.session_state["widget_serial_num"] = sample_card["serial_number"]
    st.session_state["widget_serial_max"] = sample_card["serial_max"]
    st.session_state["widget_auto"]      = sample_card["auto_label"]
    st.session_state["widget_has_mat"]   = sample_card["has_material"]
    st.session_state["widget_win"]       = sample_card["material_windows"]
    st.session_state["widget_col"]       = sample_card["material_colors"]
    st.session_state["widget_logo"]      = sample_card["is_logoman"]
    st.session_state["widget_tag"]       = sample_card["is_tag"]
    st.session_state["widget_mat_src"]   = sample_card.get("material_source_label", "无物料")
    st.session_state["widget_grader"]    = sample_card["grader_label"]
    st.session_state["widget_grade"]     = sample_card["grade_score"]


# ============================================================
# 侧边栏：卡淘真实成交参考
# ============================================================
def render_sidebar_samples():
    """渲染侧边栏 — 卡淘真实成交参考

    数据策略（2026-08）:
      * 纯卡淘（人民币市场），按"球星代表性"挑选（知名球星优先、每球员 1 条、滤掉 lot 垃圾）
      * 卡淘无数据才回退内置模拟样本
    """
    with st.sidebar:
        st.header("🏀 真实成交参考")

        samples = load_cardhobby_recent_samples(n=5)
        use_real = len(samples) > 0

        if use_real:
            st.caption("卡淘真实成交（按球星代表性挑选），点击一键填入表单。")
        else:
            st.caption("⚠️ 尚未采集到真实数据，以下为内置模拟样本（仅供体验界面）。")
            st.caption("运行 `python scripts\\build_comps_db.py` 采集真实数据后自动替换。")

        st.markdown("---")

        samples = samples if use_real else CARDHOBBY_REFERENCE_SAMPLES
        for i, sample in enumerate(samples):
            st.markdown(f"""
            <div class="sidebar-sample-card">
                <strong>{sample['title']}</strong><br>
                <small style="color:var(--text-secondary);">{sample['description']}</small><br>
                <small style="color:var(--accent-gold);"><i>{sample['real_price_note']}</i></small>
            </div>
            """, unsafe_allow_html=True)
            if st.button("📋 填入表单", key=f"sample_{i}", use_container_width=True):
                apply_sample(sample["card"])
                st.toast(f"已填入: {sample['title']}", icon="✅")
            st.markdown("---")

        st.caption(f"共 {len(samples)} 个参考样本")
        if use_real:
            st.caption("数据来源: 卡淘真实采集（自动过滤非篮球卡）")
        else:
            st.caption("数据来源: 内置模拟样本（未采集到真实数据）")


# ============================================================
# 输入表单
# ============================================================
def render_input_form():
    """渲染左侧输入表单，返回卡片属性字典"""
    st.subheader("📝 卡片属性")

    with st.container(border=True):
        # ---- 球员 & 系列 ----
        st.markdown("**🏀 球员 & 系列**")

        # 从 session_state 获取默认值
        # 选项 = 本地 505 人 + AI 助手动态加入的球员（点击案例/联网识别产生）
        player_options = PLAYER_LIST + [p for p in st.session_state.get("extra_players", [])
                                        if p not in PLAYER_LIST]
        player_idx = player_options.index(st.session_state["sel_player"]) if st.session_state["sel_player"] in player_options else 0
        product_idx = PRODUCT_LIST.index(st.session_state["sel_product"]) if st.session_state["sel_product"] in PRODUCT_LIST else 0
        year_idx = YEAR_RANGE.index(st.session_state["sel_year"]) if st.session_state["sel_year"] in YEAR_RANGE else 0

        col_a, col_b = st.columns(2)
        with col_a:
            player_name = st.selectbox(
                "球员名称", player_options,
                index=player_idx,
                key="widget_player",
                help="选择卡片上的球员（可搜索）",
            )
            st.session_state["sel_player"] = player_name
        with col_b:
            product = st.selectbox(
                "产品系列", PRODUCT_LIST,
                index=product_idx,
                key="widget_product",
                help="Panini 发行系列",
            )
            st.session_state["sel_product"] = product

        # ---- 新秀年自动校验 ----
        player_info = get_player_by_name(player_name)
        player_rc_year = player_info["rookie_year"] if player_info else 0
        player_tier = player_info["tier"] if player_info else 5
        player_team = player_info["team"] if player_info else ""

        col_a, col_b = st.columns(2)
        with col_a:
            card_year = st.selectbox(
                "卡片年份", YEAR_RANGE,
                index=year_idx,
                key="widget_year",
                help="卡片上印刷的年份",
            )
            st.session_state["sel_year"] = card_year

        with col_b:
            # 新秀资格判断
            is_rookie_year = (card_year == player_rc_year and player_rc_year > 0)
            rookie_disabled = not is_rookie_year

            # 年份与球员新秀年不匹配时，强制取消勾选
            # 注意：Streamlit 带 key 的 widget 只用首次 value，后续沿用内部状态；
            # 必须直接覆写 widget 的内部 key 才能正确反映变更。
            if rookie_disabled:
                st.session_state["widget_rookie"] = False
                st.session_state["sel_is_rookie"] = False

            is_rookie = st.checkbox(
                "新秀卡 (RC)" + (" ✓" if is_rookie_year else ""),
                disabled=rookie_disabled,
                key="widget_rookie",
                help="是否是球员的新秀年卡片" + (
                    "" if is_rookie_year else f" — {player_name} 的新秀年是 {player_rc_year}，{card_year} 年非新秀"
                ),
            )
            st.session_state["sel_is_rookie"] = is_rookie

        # 新秀年提示
        if player_rc_year > 0:
            if is_rookie_year:
                st.success(f"✅ {player_name} 的新秀年是 **{player_rc_year}** — 已选择新秀年！RC 卡享有新秀溢价。")
            else:
                st.warning(f"⚠️ {player_name} 的新秀年是 **{player_rc_year}**，当前选择的 {card_year} 不是新秀年，无法勾选 RC。")
        else:
            st.info(f"ℹ️ {player_name} 无新秀年数据，RC 不可选。")

        # 球员附加信息（未知球员可能暂无资料，需整体兜底）
        team_disp_caption = player_team or "海外/发展联盟"
        if player_info:
            st.caption(f"球队: {team_disp_caption} | 球衣号: #{player_info['jersey']} | "
                       f"层级: {player_info['tier_label']} | "
                       f"Base卡参考价: ${player_info['base_price_min']:.0f}-${player_info['base_price_max']:.0f}")
        else:
            st.caption(f"球队: {team_disp_caption} | 球衣号: #? | 层级: 未知 | Base卡参考价: 未知")

        # ---- AI 助手：球员不在本地球员库 → 联网识别 ----
        ai_info = st.session_state.get("ai_player_info")
        if ai_info and ai_info.get("name") != player_name:
            st.session_state["ai_player_info"] = None  # 球员切换后清除旧识别结果
        if player_name and player_info is None:
            st.warning(f"⚠️ **{player_name}** 未收录于本地球员库（505 人），"
                       "可以联网识别该球员的球队/位置/新秀年信息。")
            if st.button("🔍 联网识别该球员", key="btn_ai_lookup"):
                with st.spinner(f"AI 助手正在联网识别 {player_name} ..."):
                    from src.assistant.card_assistant import CardAssistant
                    info = CardAssistant().resolve_player(player_name)
                if info:
                    st.session_state["ai_player_info"] = info
                else:
                    st.session_state["ai_player_info"] = None
                    st.error(f"联网未找到 {player_name} 的篮球球员资料，请手动确认球员信息。")
                st.rerun()
        ai_info = st.session_state.get("ai_player_info")
        if ai_info and ai_info.get("name") == player_name:
            tier_label = f"tier {ai_info.get('tier', '?')}"
            team_disp = ai_info.get("team") or "球队未知（海外/发展联盟）"
            pos_disp = ai_info.get("position") or "位置未知"
            rc_disp = ai_info.get("rookie_year") or "未知"
            avatar = ai_info.get("avatar", "")
            avatar_html = (f"<img src='{avatar}' style='width:36px;height:36px;"
                           f"border-radius:50%;vertical-align:middle;margin-right:8px'>" if avatar else "")
            st.markdown(
                f"<div style='background:rgba(46,160,67,0.12);border:1px solid rgba(46,160,67,0.4);"
                f"border-radius:8px;padding:10px 12px;font-size:14px;'>"
                f"{avatar_html}<span style='vertical-align:middle'>✅ AI 助手识别："
                f"<b>{player_name}</b> | {team_disp} | {pos_disp} | 新秀年 {rc_disp} | {tier_label}"
                f"（来源: {ai_info.get('source', '')}）</span></div>",
                unsafe_allow_html=True,
            )

        # ---- 折射 & 编号 ----
        st.markdown("**✨ 折射 & 编号**")
        ref_labels = list(REFRACTION_OPTIONS.keys())
        ref_idx = ref_labels.index(st.session_state["sel_refraction"]) if st.session_state["sel_refraction"] in ref_labels else 0

        col_a, col_b = st.columns(2)
        with col_a:
            ref_label = st.selectbox(
                "折射等级", ref_labels,
                index=ref_idx,
                key="widget_ref",
                help="卡片的折射/平行类型",
            )
            st.session_state["sel_refraction"] = ref_label
        with col_b:
            serial_number = st.number_input(
                "编号 (Serial #)", min_value=0, max_value=999,
                value=st.session_state["sel_serial_num"], step=1,
                key="widget_serial_num",
                help="卡片上印的编号，0=未编号",
            )
            st.session_state["sel_serial_num"] = serial_number
            serial_max = st.number_input(
                "限量总数 (/XX)", min_value=0, max_value=999,
                value=st.session_state["sel_serial_max"], step=1,
                key="widget_serial_max",
                help="总发行量，如/99则填99，0=未编号",
            )
            st.session_state["sel_serial_max"] = serial_max

        # 同背编检测
        player_jersey = player_info["jersey"] if player_info else -1
        is_jersey_match = False
        if serial_number > 0 and serial_number == player_jersey:
            is_jersey_match = True
            st.info(f"🎯 检测到同背编号！(#{serial_number}/{serial_max} 匹配 {player_name} 的球衣号 #{player_jersey})")

        # ---- 签字 ----
        st.markdown("**🖊️ 签字信息**")
        auto_labels = list(AUTO_OPTIONS.keys())
        auto_idx = auto_labels.index(st.session_state["sel_auto"]) if st.session_state["sel_auto"] in auto_labels else 0

        auto_label = st.selectbox(
            "签字类型", auto_labels,
            index=auto_idx,
            key="widget_auto",
            help="卡片的签字类型",
        )
        st.session_state["sel_auto"] = auto_label
        has_auto, auto_type = AUTO_OPTIONS[auto_label]

        # ---- 物料 ----
        st.markdown("**🧵 实物物料**")
        has_material = st.checkbox(
            "含实物物料 (Patch/Jersey)", value=st.session_state["sel_has_material"],
            key="widget_has_mat",
            help="卡片是否含有球衣/Patch等实物",
        )
        st.session_state["sel_has_material"] = has_material

        material_windows = 0
        material_colors = 0
        is_logoman = False
        is_tag = False
        material_source = 0

        if has_material:
            # 防呆: 无物料卡填入时窗口/配色可能为 0（如 RPA 标题未标明窗数），
            # number_input min_value=1 会抛 StreamlitValueBelowMinError → 钳位到 ≥1
            mat_win_safe = max(int(st.session_state.get("sel_mat_windows", 1)), 1)
            mat_col_safe = max(int(st.session_state.get("sel_mat_colors", 1)), 1)
            col_a, col_b = st.columns(2)
            with col_a:
                material_windows = st.number_input(
                    "开窗数量", min_value=1, max_value=10,
                    value=mat_win_safe, step=1,
                    key="widget_win",
                    help="Patch/Jersey窗口数",
                )
                st.session_state["sel_mat_windows"] = material_windows
                material_colors = st.number_input(
                    "配色数量", min_value=1, max_value=10,
                    value=mat_col_safe, step=1,
                    key="widget_col",
                    help="Patch颜色断裂数",
                )
                st.session_state["sel_mat_colors"] = material_colors
            with col_b:
                is_logoman = st.checkbox(
                    "Logoman 🏆", value=st.session_state["sel_is_logoman"],
                    key="widget_logo",
                    help="是否含有NBA Logoman标志",
                )
                st.session_state["sel_is_logoman"] = is_logoman
                is_tag = st.checkbox(
                    "Tag 📛", value=st.session_state["sel_is_tag"],
                    key="widget_tag",
                    help="是否含有球衣标签Tag",
                )
                st.session_state["sel_is_tag"] = is_tag

            mat_source_labels = list(MATERIAL_SOURCE_OPTIONS.keys())
            mat_src_idx = mat_source_labels.index(st.session_state["sel_mat_source"]) if st.session_state["sel_mat_source"] in mat_source_labels else 0

            material_source_label = st.selectbox(
                "物料来源", mat_source_labels,
                index=mat_src_idx,
                key="widget_mat_src",
                help="实物物料的取得来源",
            )
            st.session_state["sel_mat_source"] = material_source_label
            material_source = MATERIAL_SOURCE_OPTIONS[material_source_label]

        # ---- 评级 ----
        st.markdown("**📊 评级信息**")
        grader_labels = list(GRADER_OPTIONS.keys())
        grader_idx = grader_labels.index(st.session_state["sel_grader"]) if st.session_state["sel_grader"] in grader_labels else 0

        col_a, col_b = st.columns(2)
        with col_a:
            grader_label = st.selectbox(
                "评级公司", grader_labels,
                index=grader_idx,
                key="widget_grader",
                help="评级服务的公司",
            )
            st.session_state["sel_grader"] = grader_label
        has_grade, grade_grader, default_grade = GRADER_OPTIONS[grader_label]

        with col_b:
            if has_grade:
                grade_score = st.slider(
                    "评级分数", min_value=7.0, max_value=10.0,
                    value=st.session_state["sel_grade_score"] if st.session_state["sel_grade_score"] >= 7.0 else default_grade,
                    step=0.5,
                    key="widget_grade",
                    help="BGS/PSA评级分数",
                )
                st.session_state["sel_grade_score"] = grade_score
            else:
                grade_score = 0.0
                st.session_state["sel_grade_score"] = 0.0

    # ---- 组装属性字典 ----
    card_dict = {
        "player_name": player_name,
        "product": product,
        "card_year": card_year,
        "is_rookie": 1 if is_rookie else 0,
        "refraction_level": REFRACTION_OPTIONS[ref_label],
        "serial_number": serial_number,
        "serial_max": serial_max,
        "is_jersey_match": 1 if is_jersey_match else 0,
        "has_auto": 1 if has_auto else 0,
        "auto_type": auto_type,
        "has_material": 1 if has_material else 0,
        "material_windows": material_windows,
        "material_colors": material_colors,
        "is_logoman": 1 if is_logoman else 0,
        "is_tag": 1 if is_tag else 0,
        "material_source": material_source,
        "has_grade": 1 if has_grade else 0,
        "grade_score": grade_score,
        "grade_grader": grade_grader,
        # 编码器需要的补充字段
        "player_team": player_team,
        "player_rc_year": player_rc_year,
        "refraction_name": ref_label.split(" (")[0],
        "auto_type_name": auto_label.split(" (")[0] if "(" in auto_label else auto_label,
        "material_source_name": "",
        "grade_grader_name": grader_label,
    }

    return card_dict


# ============================================================
# 结果展示
# ============================================================
def render_results(card_dict, result):
    """渲染右侧结果面板"""
    st.subheader("📈 估价结果")

    price = result["price"]
    ci_low = result["ci_low"]
    ci_high = result["ci_high"]
    attribution = result.get("attribution", {})

    # ---- 价格卡片 (带动画) ----
    if price >= 10000 or price >= 1000:
        price_str = f"${price:,.0f}"
    else:
        price_str = f"${price:.2f}"

    # ---- 球员照片 ----
    player_name = card_dict.get("player_name", "")
    player_info = get_player_by_name(player_name)
    team_name = player_info["team"] if player_info else ""
    image_url = get_player_image_url(player_name)

    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:center;gap:20px;margin-bottom:16px;">
        <div style="
            width:100px;height:100px;border-radius:50%;overflow:hidden;
            border:3px solid rgba(255,255,255,0.8);
            box-shadow:0 4px 16px rgba(0,0,0,0.10), 0 1px 3px rgba(0,0,0,0.06);
            flex-shrink:0;
            background:#f1f5f9;
        ">
            <img src="{image_url}" alt="{player_name}"
                 style="width:100%;height:100%;object-fit:cover;"
                 onerror="this.style.display='none'"
                 referrerpolicy="no-referrer" />
        </div>
        <div style="text-align:left;">
            <div style="font-size:1.3em;font-weight:700;color:#0f172a;">{player_name}</div>
            <div style="font-size:0.9em;color:#64748b;">{team_name}</div>
            <div style="font-size:0.8em;color:#94a3b8;">
                {player_info.get('tier_label','')} · #{player_info.get('jersey','')} · {player_info.get('position','')}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    uncertainty = (ci_high - ci_low) / price if price > 0 else 0
    if uncertainty < 0.2:
        conf_class, conf_label = "confidence-high", "🟢 置信度高 (< 20%)"
    elif uncertainty < 0.5:
        conf_class, conf_label = "confidence-medium", "🟡 置信度中等 (20-50%)"
    else:
        conf_class, conf_label = "confidence-low", "🔴 置信度较低 (> 50%)"

    st.markdown(f"""
    <div class="price-hero-card">
        <h3 style="margin:0 0 8px 0; color: var(--text-secondary);">💰 预估市场价值</h3>
        <div class="price-value">{price_str}</div>
        <div class="price-ci">95% 置信区间: ${ci_low:,.0f} ~ ${ci_high:,.0f}</div>
        <span class="confidence-badge {conf_class}">{conf_label}</span>
    </div>
    """, unsafe_allow_html=True)

    # ---- 特殊标记 (带动画) ----
    flags = []
    if card_dict["is_rookie"] and card_dict["has_auto"] and card_dict["has_material"]:
        flags.append(("🏆", "RPA 卡牌", "flag-rpa"))
    if card_dict["is_logoman"] and card_dict["serial_max"] == 1:
        flags.append(("💎", "Logoman 1/1", "flag-oneone"))
    if card_dict["is_jersey_match"]:
        flags.append(("🎯", "同背编号", "flag-match"))
    if card_dict["is_rookie"] and card_dict["refraction_level"] == 5:
        flags.append(("🌟", "新秀 1/1", "flag-oneone"))
    if card_dict["has_grade"] and card_dict["grade_score"] >= 10.0:
        flags.append(("⚫", "满分评级", "flag-grade"))

    if flags:
        st.markdown("### 🏷️ 特殊标记")
        tags_html = " ".join(
            f'<span class="flag-tag {css_cls}">{icon} {label}</span>'
            for icon, label, css_cls in flags
        )
        st.markdown(tags_html, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    # ---- SHAP 归因 ----
    if attribution:
        with st.container(border=True):
            st.markdown("### 🔍 价格归因分析 (SHAP)")
            st.caption("各因素对最终价格的贡献（正值=溢价，负值=折价）")

            sorted_items = sorted(attribution.items(), key=lambda x: abs(x[1]), reverse=True)
            nonzero_items = [(k, v) for k, v in sorted_items if abs(v) > 0.01]
            if not nonzero_items:
                nonzero_items = sorted_items[:10]

            display_items = nonzero_items[:12]
            max_abs = max(abs(v) for _, v in display_items) if display_items else 1

            for feat, contrib in display_items:
                # 正值蓝色，负值红色
                if contrib >= 0:
                    bar_fill = "linear-gradient(90deg, #2dd4bf, #60a5fa)"
                    bar_bg = "rgba(45,212,191,0.08)"
                    sign = "+"
                else:
                    bar_fill = "linear-gradient(90deg, #fb7185, #f97316)"
                    bar_bg = "rgba(251,113,133,0.08)"
                    sign = ""

                pct = min(abs(contrib) / max_abs * 100, 100) if max_abs > 0 else 0

                st.markdown(f"""
                <div style="display:flex;align-items:center;gap:12px;margin:6px 0;">
                    <div style="width:120px;text-align:right;font-size:13px;color:rgba(0,0,0,0.65);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="{feat}">{feat}</div>
                    <div style="flex:1;height:22px;background:{bar_bg};border-radius:4px;overflow:hidden;position:relative;">
                        <div style="width:{pct:.1f}%;height:100%;background:{bar_fill};border-radius:4px;transition:width 0.7s cubic-bezier(0.4,0,0.2,1);"></div>
                    </div>
                    <div style="width:100px;font-size:13px;font-weight:600;color:{bar_fill};text-align:right;">{sign}${contrib:,.0f}</div>
                </div>
                """, unsafe_allow_html=True)

    # ---- 可比成交 (Comps) — 翻页（纯卡淘） ----
    with st.container(border=True):
        st.markdown("### 📊 市场相似成交记录（卡淘）")

        # 初始化翻页状态
        if "ch_page" not in st.session_state:
            st.session_state["ch_page"] = 0

        with st.spinner("正在匹配卡淘成交..."):
            similar = find_similar_comps(card_dict, top_k=20, min_similarity=15.0)

        if not similar.empty:
            total = len(similar)
            total_pages = max(1, (total + COMPS_PER_PAGE - 1) // COMPS_PER_PAGE)
            page = st.session_state["ch_page"]

            # 翻页超出范围时回卷
            if page >= total_pages:
                page = 0
                st.session_state["ch_page"] = 0

            start = page * COMPS_PER_PAGE
            end = min(start + COMPS_PER_PAGE, total)
            page_data = similar.iloc[start:end]

            st.caption(f"共 {total} 条匹配 | 第 {page+1}/{total_pages} 页 | "
                       f"最高匹配度: {similar.iloc[0]['similarity']:.0f}%")

            # ---- 列表 ----
            for i, (_, comp) in enumerate(page_data.iterrows()):
                sim_pct = comp["similarity"]
                badge = "🟢" if sim_pct >= 80 else ("🟡" if sim_pct >= 60 else "🟠")

                col1, col2, col3 = st.columns([6, 2, 2])
                with col1:
                    title_display = str(comp.get("title", ""))[:100]
                    st.markdown(f"""
                    <div class="comp-row">
                        <strong>{badge} {title_display}</strong>
                        <br><small style="color:var(--text-secondary);">{comp.get('sold_date','')} | {comp.get('listing_type','')}</small>
                    </div>
                    """, unsafe_allow_html=True)
                with col2:
                    price_cny = comp.get("price_cny", comp.get("price", 0))
                    price_usd_val = comp.get("price_usd", round(price_cny / 7.25, 2))
                    st.markdown(f"<h4 style='color:#e11d48;margin:0;'>¥{price_cny:,.0f}</h4>",
                                unsafe_allow_html=True)
                    st.caption(f"≈ ${price_usd_val:,.0f} USD")
                    st.caption(f"卖家: {comp.get('seller','')[:12]}")
                with col3:
                    sim_color = (
                        "#059669" if sim_pct >= 80 else
                        "#d97706" if sim_pct >= 60 else "#e11d48"
                    )
                    st.markdown(f"<span style='font-size:1.1em;font-weight:bold;color:{sim_color};'>{sim_pct:.0f}%</span>",
                                unsafe_allow_html=True)
                    st.caption("匹配度")

            # ---- 翻页按钮 ----
            if total_pages > 1:
                st.markdown("")
                c_prev, c_info, c_next = st.columns([1, 2, 1])
                with c_prev:
                    if st.button("◀ 上一页", key="prev_ch",
                                 disabled=(page == 0), use_container_width=True):
                        st.session_state["ch_page"] = max(0, page - 1)
                        st.rerun()
                with c_info:
                    st.markdown(f"<p style='text-align:center;color:#888;'>{page+1} / {total_pages}</p>",
                                unsafe_allow_html=True)
                with c_next:
                    if st.button("下一页 ▶", key="next_ch",
                                 disabled=(page >= total_pages - 1), use_container_width=True):
                        st.session_state["ch_page"] = min(total_pages - 1, page + 1)
                        st.rerun()
        else:
            st.info("暂无卡淘相似成交数据。")

    # ---- 同价位替代卡（纯卡淘） ----
    with st.container(border=True):
        st.markdown("### 💱 同价位可以买到什么？")
        st.caption(f"预算 ${price:,.0f} 左右，以下卡淘成交也在同一价格区间")

        # 翻页状态
        if "price_page_cardhobby" not in st.session_state:
            st.session_state["price_page_cardhobby"] = 0

        # 卡淘用 CNY 比价（USD → CNY 近似）
        search_price = price * 7.25

        matched = find_price_matches(search_price, tolerance=0.40, top_k=24)

        if not matched.empty:
            total = len(matched)
            total_pages = max(1, (total + COMPS_PER_PAGE - 1) // COMPS_PER_PAGE)
            page = st.session_state["price_page_cardhobby"]
            if page >= total_pages:
                page = 0
                st.session_state["price_page_cardhobby"] = 0

            start = page * COMPS_PER_PAGE
            end = min(start + COMPS_PER_PAGE, total)
            page_data = matched.iloc[start:end]

            st.caption(f"共 {total} 张卡片在 "
                       f"¥{search_price*0.6:,.0f} ~ ¥{search_price*1.4:,.0f} 区间 | "
                       f"第 {page+1}/{total_pages} 页")

            for _, comp in page_data.iterrows():
                comp_price = comp.get("price_cny", comp.get("price", 0))
                diff_pct = (comp_price - search_price) / search_price * 100 if search_price > 0 else 0
                diff_sign = "+" if diff_pct > 0 else ""
                diff_color = "#047857" if abs(diff_pct) < 10 else ("#d97706" if abs(diff_pct) < 25 else "#b91c1c")

                title_display = str(comp.get("title", ""))[:90]
                col_p1, col_p2, col_p3 = st.columns([6, 2, 2])
                with col_p1:
                    st.markdown(f"""
                    <div class="comp-row">
                        <strong>{title_display}</strong>
                        <br><small style="color:var(--text-secondary);">{comp.get('sold_date','')} | {comp.get('listing_type','')}</small>
                    </div>
                    """, unsafe_allow_html=True)
                with col_p2:
                    st.markdown(f"<h4 style='color:#0891b2;margin:0;'>¥{comp_price:,.0f}</h4>",
                                unsafe_allow_html=True)
                with col_p3:
                    st.markdown(f"<span style='font-size:1.0em;font-weight:600;color:{diff_color};'>{diff_sign}{diff_pct:.0f}%</span>",
                                unsafe_allow_html=True)
                    st.caption("差价")

            if total_pages > 1:
                c_prev, c_info, c_next = st.columns([1, 2, 1])
                with c_prev:
                    if st.button("◀ 上一页", key="prev_price_cardhobby",
                                 disabled=(page == 0), use_container_width=True):
                        st.session_state["price_page_cardhobby"] = max(0, page - 1)
                        st.rerun()
                with c_info:
                    st.markdown(f"<p style='text-align:center;color:#888;'>{page+1} / {total_pages}</p>",
                                unsafe_allow_html=True)
                with c_next:
                    if st.button("下一页 ▶", key="next_price_cardhobby",
                                 disabled=(page >= total_pages - 1), use_container_width=True):
                        st.session_state["price_page_cardhobby"] = min(total_pages - 1, page + 1)
                        st.rerun()
        else:
            st.info("暂无卡淘价格区间内的卡片。")

    # ---- 使用提示 ----
    with st.expander("💡 使用提示", expanded=False):
        st.markdown("""
        - **预估价**基于 XGBoost 模型在模拟+真实数据上的训练结果，反映市场定价规律
        - **置信区间**反映模型对该卡片属性组合的不确定性
        - SHAP **归因分析**揭示每个因素如何影响最终价格
        - **CardHobby 卡淘成交**（人民币）展示，可翻页浏览
        - **RPA卡牌**（新秀+签字+物料）具有显著的协同溢价效应
        - 侧边栏提供 **卡淘真实成交案例**，点击可快速体验不同场景
        """)


# ============================================================
# 页面头部
# ============================================================
def render_header():
    """渲染页面标题"""
    st.title("🏀 球星卡价值分析系统")
    st.caption("基于 XGBoost 机器学习模型 & SHAP 可解释性分析的球星卡智能估价工具")
    st.markdown("---")


# ============================================================
# 主入口
# ============================================================
def main():
    init_session_state()
    inject_custom_css()
    render_header()

    # 加载模型
    with st.spinner("正在加载模型..."):
        try:
            encoder, engine = load_models()
        except Exception as e:
            st.error(f"模型加载失败: {e}")
            st.info("请先运行 `python train.py` 训练模型，然后再启动 Streamlit。")
            st.stop()

    # ---- 侧边栏：卡淘真实成交参考 ----
    render_sidebar_samples()

    st.success("✅ 模型已就绪 — 在左侧填写卡片属性，或从侧边栏选择参考样本快速体验")

    # 左右分栏
    col_left, col_right = st.columns([1, 1.1])

    with col_left:
        card_dict = render_input_form()

        # 如果用户改了表单关键字段，清除旧评估结果（避免翻页时看到过时数据）
        if st.session_state.get("evaluated"):
            last = st.session_state.get("eval_card", {})
            key_fields = ["player_name", "product", "card_year", "refraction_level",
                          "has_auto", "auto_type", "has_material", "is_rookie"]
            changed = any(last.get(k) != card_dict.get(k) for k in key_fields)
            if changed:
                st.session_state["evaluated"] = False

        st.markdown("---")
        evaluate_btn = st.button(
            "🔍 开始评估",
            type="primary",
            use_container_width=True,
        )

        # 点击评估按钮 → 持久化结果到 session_state
        if evaluate_btn:
            with st.spinner("正在分析卡片价值..."):
                time.sleep(0.3)
                try:
                    X = encoder.transform_single(card_dict)
                    result = engine.predict(X, return_attribution=True)
                    st.session_state["evaluated"] = True
                    st.session_state["eval_card"] = card_dict
                    st.session_state["eval_result"] = result
                except Exception as e:
                    st.error(f"评估失败: {e}")
                    st.info("请检查卡片属性输入是否正确，或重新训练模型。")

        # ---- 球员荣誉（评估后展示） ----
        if st.session_state.get("evaluated"):
            eval_card = st.session_state["eval_card"]
            player_name = eval_card.get("player_name", "")

            st.markdown("---")
            st.subheader("🏆 生涯荣誉")

            honors = get_player_honors(player_name)

            if honors:
                for h in honors:
                    st.markdown(f"""
                    <div style="display:flex;align-items:center;gap:10px;padding:6px 10px;
                                margin:3px 0;border-radius:6px;
                                background:rgba(255,255,255,0.5);font-size:13px;">
                        <span style="font-size:1.2em;width:28px;text-align:center;">{h['icon']}</span>
                        <span style="font-weight:600;color:#1e293b;min-width:60px;">{h['category']}</span>
                        <span style="color:#64748b;">{h['detail']}</span>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.caption("暂无荣誉记录")

    with col_right:
        if st.session_state.get("evaluated"):
            # 翻页 rerun 后结果仍在，直接渲染
            render_results(st.session_state["eval_card"],
                          st.session_state["eval_result"])

            # ---- AI 助手：本地样本不足 → 联网查真实成交参考 ----
            eval_card = st.session_state["eval_card"]
            eval_player = str(eval_card.get("player_name", "")).strip()
            has_local_sample = eval_player in encoder.star_power_map
            if eval_player and not has_local_sample:
                with st.expander("🔍 AI 助手：本地成交样本不足，联网查参考价", expanded=False):
                    st.caption("模型对该球员的训练样本很少，价格置信度较低。"
                               "可以让 AI 助手在卡淘实时查找该球员的真实成交，辅助判断。")
                    if st.button("📡 联网查真实成交参考", key="btn_ai_price",
                                 use_container_width=True):
                        with st.spinner("AI 助手正在采集卡淘公开列表（约 30-60 秒）..."):
                            from src.assistant.card_assistant import CardAssistant
                            refs = CardAssistant().search_price_reference(eval_player)
                        if refs:
                            st.success(f"找到 {len(refs)} 条相关成交/在售记录：")
                            for r in refs:
                                price_txt = ""
                                if r.get("price_cny"):
                                    price_txt = f"¥{r['price_cny']:,.0f}"
                                elif r.get("price_usd"):
                                    price_txt = f"${r['price_usd']:.2f}"
                                bids = r.get("bids")
                                bid_txt = f" | {bids} 次出价" if bids else ""
                                date_txt = f" | {r['sold_date']}" if r.get("sold_date") else ""
                                st.markdown(
                                    f"- **{price_txt}**{bid_txt}{date_txt} — "
                                    f"{r['title']}（{r['source']}）")
                            st.caption("提示：上面价格为近似参考，非精确成交数据。"
                                       "可对照左侧预估，若差距大请人工复核卡片细节。")
                        else:
                            st.warning("未找到该球员的卡淘在售/成交记录。"
                                       "可能是中文名差异，或该球员卡片当前无货。")
        else:
            with st.container(border=True):
                st.markdown("### 💰 预估市场价值")
                st.markdown(
                    "<p style='text-align:center; color:#aaa; padding: 3em 0;'>"
                    "👈 在左侧填写卡片属性后，点击「开始评估」<br><br>"
                    "📋 也可以打开左侧边栏，从卡淘真实成交案例中选择参考卡片</p>",
                    unsafe_allow_html=True
                )

        # ---- AI 估价助手（始终可见；未配置 LLM Key 时降级） ----
        render_agent_chat()


def render_agent_chat():
    """AI 估价助手聊天面板：OpenAI 兼容 LLM + function calling"""
    st.container(border=True)

    st.markdown("### 🤖 AI 估价助手")
    st.caption("可以和 AI 对话评估卡片、识别冷门球员、查询卡淘成交参考")

    # ---- 会话状态初始化 ----
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []
    if "agent_session_id" not in st.session_state:
        st.session_state.agent_session_id = ""
    if "agent_last_tool_calls" not in st.session_state:
        st.session_state.agent_last_tool_calls = []
    if "agent_degraded" not in st.session_state:
        st.session_state.agent_degraded = False

    # ---- 历史消息 ----
    for m in st.session_state.agent_messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # ---- 工具调用摘要（上一条 assistant 回复的） ----
    if st.session_state.get("agent_last_tool_calls"):
        for t in st.session_state.agent_last_tool_calls:
            st.caption(f"🔧 已调用 `{t['name']}` — {t['result_summary'][:90]}")

    # ---- 降级提示 ----
    if st.session_state.get("agent_degraded"):
        st.info("当前未配置 LLM API Key（降级模式）。"
                "配置环境变量 OPENAI_API_KEY（DeepSeek 等 OpenAI 兼容服务）后重启即可启用。")

    # 上轮发送/清空后的输入框清除（必须在 widget 实例化前修改 session_state）
    if st.session_state.pop("agent_input_clear", False):
        st.session_state["agent_input"] = ""

    # ---- 输入区 ----
    user_input = st.text_input("和 AI 聊聊这张卡", key="agent_input")
    c_send, c_clear = st.columns([3, 1])
    with c_send:
        btn_send = st.button("发送", key="btn_agent_send", use_container_width=True)
    with c_clear:
        btn_clear = st.button("清空", key="btn_agent_clear", use_container_width=True)

    if btn_clear:
        st.session_state.agent_messages = []
        st.session_state.agent_last_tool_calls = []
        st.session_state.agent_degraded = False
        st.session_state["agent_input_clear"] = True
        st.rerun()

    if btn_send and user_input.strip():
        if not st.session_state.get("agent_session_id"):
            import uuid
            st.session_state.agent_session_id = uuid.uuid4().hex
        st.session_state.agent_messages.append(
            {"role": "user", "content": user_input.strip()})
        with st.spinner("AI 助手思考中（可能需要联网查询卡淘）..."):
            from src.assistant.agent import CardAgent
            result = CardAgent().chat(st.session_state.agent_messages)
        st.session_state.agent_messages.append(
            {"role": "assistant", "content": result["reply"]})
        st.session_state.agent_last_tool_calls = result["tool_calls"]
        st.session_state.agent_degraded = result["degraded"]
        st.session_state["agent_input_clear"] = True
        st.rerun()


if __name__ == "__main__":
    main()
