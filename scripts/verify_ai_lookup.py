"""验证 2/2：AI 助手联网识别（删除缓存 → 未收录警告 → 联网识别 → 缓存写回）"""
import io
import json
import os
import sys

sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from streamlit.testing.v1 import AppTest

CACHE = "data/player_extra.json"
if os.path.exists(CACHE):
    os.remove(CACHE)
    print("已删除联网缓存（模拟全新环境）")

print("=== 1) 启动应用（Bouknight 不在本地球员库）===")
at = AppTest.from_file("app.py", default_timeout=180).run()
assert not at.exception, [e.value for e in at.exception]

print("=== 2) 点击 Bouknight 案例 → 出现未收录警告 + 联网识别按钮 ===")
elems = list(at.sidebar)
btn_key = None
for i, el in enumerate(elems):
    if getattr(el, "type", None) == "markdown" and "James Bouknight" in str(getattr(el, "value", "")):
        nxt = elems[i + 1]
        if getattr(nxt, "type", None) == "button":
            btn_key = nxt.key
        break
assert btn_key, "侧边栏未找到 Bouknight 样本"
at.button(key=btn_key).click()
at.run()
assert not at.exception, [e.value for e in at.exception]

warns = [str(w.value) for w in at.warning]
print(f"  warnings: {warns}")
assert any("未收录于本地球员库" in w for w in warns), "FAIL: 未收录警告未出现"

lk = at.button(key="btn_ai_lookup")
assert lk, "FAIL: 联网识别按钮未出现"
print("  未收录警告 + 联网识别按钮均出现 ✓")

print("=== 3) 点击「🔍 联网识别该球员」（TheSportsDB 联网）===")
lk.click()
at.run()
assert not at.exception, [e.value for e in at.exception]

info = at.session_state["ai_player_info"] if "ai_player_info" in at.session_state else None
print(f"  ai_player_info = {info}")
assert info and info["name"] == "James Bouknight", "FAIL: 未识别到 Bouknight"
assert info.get("position") == "SG", f"FAIL: 位置={info.get('position')}"
assert info.get("rookie_year") == 2021, f"FAIL: 新秀年={info.get('rookie_year')}"
assert info.get("source") == "联网搜索", f"FAIL: 来源={info.get('source')}"
print("  识别结果: SG / 新秀 2021 / tier3（来源: 联网搜索）✓")

print("=== 4) 缓存已写回 + 本地球员库已注册 ===")
assert os.path.exists(CACHE), "FAIL: 缓存文件未写回"
data = json.load(open(CACHE, encoding="utf-8"))
print(f"  缓存内容: {data.get('James Bouknight')}")
assert "James Bouknight" in data

from src.data.player_db import get_player_by_name
p = get_player_by_name("James Bouknight")
print(f"  get_player_by_name → {p is not None}")
assert p is not None, "FAIL: 注册后本地库仍查不到"

print("=== 5) 表单成功提示框 ===")
succ = [str(m.value) for m in at.markdown if "AI 助手识别" in str(m.value)]
for s in succ:
    print(f"  success: {s[:160]}")
assert any("AI 助手识别" in s and "SG" in s for s in succ), "FAIL: 识别成功提示框未出现"

print("\nALL_LOOKUP_ASSERTS_PASS")
