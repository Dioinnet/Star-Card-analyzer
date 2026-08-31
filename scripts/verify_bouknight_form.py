"""验证 1/2：Bouknight 案例点击 → 表单正确填入 + 评估（无网络依赖）"""
import io
import sys

sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
from streamlit.testing.v1 import AppTest

print("=== 1) 启动应用 ===")
at = AppTest.from_file("app.py", default_timeout=120).run()
assert not at.exception, [e.value for e in at.exception]

print("=== 2) 点击侧边栏 Bouknight 案例 ===")
elems = list(at.sidebar)
btn_key = None
for i, el in enumerate(elems):
    if getattr(el, "type", None) == "markdown" and "James Bouknight" in str(getattr(el, "value", "")):
        nxt = elems[i + 1]
        if getattr(nxt, "type", None) == "button":
            btn_key = nxt.key
        break
assert btn_key, "侧边栏未找到 Bouknight 参考案例"
print(f"  找到样本按钮: {btn_key}")
at.button(key=btn_key).click()
at.run()
assert not at.exception, [e.value for e in at.exception]

print("=== 3) 表单球员检查（核心 bug 修复点）===")
sel = at.selectbox(key="widget_player")
print(f"  表单球员 = {sel.value!r}")
assert sel.value == "James Bouknight", f"FAIL: 表单球员仍是 {sel.value!r}"
assert at.session_state["sel_player"] == "James Bouknight"
extra = at.session_state["extra_players"] if "extra_players" in at.session_state else []
from app import PLAYER_LIST as _PL
assert "James Bouknight" in extra or "James Bouknight" in _PL
print("  表单球员正确 = James Bouknight（不再回退 AJ Green）✓")

print("=== 4) 点击「开始评估」===")
ev_btn = None
for b in at.button:
    if getattr(b, "label", None) == "🔍 开始评估" or getattr(b, "value", None) == "🔍 开始评估":
        ev_btn = b
        break
assert ev_btn is not None, "未找到评估按钮"
ev_btn.click()
at.run()
assert not at.exception, [e.value for e in at.exception]

ec = at.session_state["eval_card"]
print(f"  评估卡片: player={ec['player_name']} | is_rookie={ec['is_rookie']} | "
      f"year={ec['card_year']} | serial 1/{ec['serial_max']} | ref={ec['refraction_level']}")
assert ec["player_name"] == "James Bouknight"
assert ec["is_rookie"] == 1, "FAIL: RC 溢价丢失（修复前 AJ Green 年份不匹配导致 is_rookie=0）"

print("=== 5) 价格对比：Bouknight(RC) vs 修复前 AJ Green(非RC) ===")
from src.features.card_encoder import CardEncoder
from src.models.pricing_engine import PricingEngine

encoder = CardEncoder.load("models/card_encoder.joblib")
engine = PricingEngine.load("models/xgb_card_pricing.joblib")

X = encoder.transform_single(ec)
star = X[0, 0]
expected = np.log(15.0)  # tier3 兜底（Bouknight 无训练样本）
print(f"  star_power = {star:.4f}（期望 log(15)={expected:.4f}，不在训练库: "
      f"{'James Bouknight' not in encoder.star_power_map}）")
assert abs(star - expected) < 1e-6, "FAIL: star_power 不是 tier3 兜底值"

pred_bouknight = float(engine.predict(X, return_attribution=False)["price"])
ec_aj = dict(ec)
ec_aj["player_name"] = "AJ Green"
ec_aj["is_rookie"] = 0  # 修复前表单强制取消 RC 的状态
pred_ajgreen = float(engine.predict(encoder.transform_single(ec_aj), return_attribution=False)["price"])
print(f"  Bouknight 2021 1/1 RC 预估 = ${pred_bouknight:,.2f}")
print(f"  修复前(AJ Green 非RC)      = ${pred_ajgreen:,.2f}")
assert pred_bouknight != pred_ajgreen, "FAIL: 两场景价格相同"
assert pred_bouknight > pred_ajgreen, "FAIL: RC 溢价未体现"

print("=== 6) AI 价格参考区（Bouknight 无训练样本 → 显示联网参考入口）===")
exp_labels = [e.label for e in at.expander]
print(f"  expanders: {exp_labels}")
assert any("AI 助手" in lbl and "参考价" in lbl for lbl in exp_labels), "FAIL: 联网查价 expander 未出现"
price_btn = at.button(key="btn_ai_price")
print(f"  联网查价按钮存在: {bool(price_btn)}")
assert price_btn

print("=== 7) 本地价格参考（in-process，不触发慢速实时采集）===")
from src.assistant.card_assistant import CardAssistant

refs = CardAssistant().search_price_reference("James Bouknight")
for r in refs:
    print(f"  - ¥{r.get('price_cny')} / ${r.get('price_usd')} | {r.get('title')} | {r.get('source')}")
assert any("卡淘" in r["source"] for r in refs), "FAIL: 本地卡淘数据库未命中 Bouknight 成交"

print("\nALL_FORM_ASSERTS_PASS")
