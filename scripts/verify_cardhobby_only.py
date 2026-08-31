"""验证：展示层只留卡淘 + AI 助手聊天面板（无网络、无 LLM Key 依赖）

前提：环境变量中不要设置 OPENAI_API_KEY（否则聊天面板会真实调 LLM）
"""
import io
import os
import sys

sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from streamlit.testing.v1 import AppTest

# 隔离 agent.env 中的真实 key：本测试只验证降级路径，不真调 LLM
os.environ["OPENAI_API_KEY"] = ""

print("=== 1) 启动应用 ===")
at = AppTest.from_file("app.py", default_timeout=120).run()
assert not at.exception, [e.value for e in at.exception]

print("=== 2) 全页无 eBay 字样 ===")
all_text = []
for el in list(at.markdown) + list(at.caption) + list(at.tabs) + list(at.expander):
    all_text.append(str(getattr(el, "label", "") or getattr(el, "value", "")))
for b in at.button:
    all_text.append(str(getattr(b, "label", "") or getattr(b, "value", "")))
for el in list(at.sidebar.markdown) + list(at.sidebar.caption):
    all_text.append(str(getattr(el, "value", "")))
joined = " | ".join(all_text)
assert "eBay" not in joined, f"FAIL: 页面仍出现 eBay 字样: {joined}"
assert "ebay" not in joined.lower() or "cardhobby" in joined.lower()
print("  页面文本无 eBay 字样 ✓")

print("=== 3) 无 tabs（结果区不再双 tab）===")
assert len(at.tabs) == 0, f"FAIL: 页面仍有 {len(at.tabs)} 个 tabs"
print("  页面无 tabs ✓")

print("=== 4) 侧边栏 5 条卡淘样本 ===")
sidebar_captions = [str(c.value) for c in at.sidebar.caption]
print(f"  侧边栏 captions: {sidebar_captions}")
assert any("卡淘" in c for c in sidebar_captions), "FAIL: 侧边栏未标注卡淘来源"
btn_count = sum(1 for el in list(at.sidebar) if getattr(el, "type", None) == "button")
print(f"  侧边栏样本按钮数: {btn_count}")
assert btn_count >= 4, f"FAIL: 侧边栏样本按钮不足 ({btn_count})"

print("=== 5) 点 Bouknight → 评估 → 结果区为卡淘单容器 ===")
elems = list(at.sidebar)
btn_key = None
for i, el in enumerate(elems):
    if getattr(el, "type", None) == "markdown" and "James Bouknight" in str(getattr(el, "value", "")):
        nxt = elems[i + 1]
        if getattr(nxt, "type", None) == "button":
            btn_key = nxt.key
        break
assert btn_key, "侧边栏未找到 Bouknight 案例"
at.button(key=btn_key).click()
at.run()
assert not at.exception, [e.value for e in at.exception]

ev_btn = None
for b in at.button:
    if "开始评估" in str(getattr(b, "label", "") or getattr(b, "value", "")):
        ev_btn = b
        break
assert ev_btn is not None, "未找到评估按钮"
ev_btn.click()
at.run()
assert not at.exception, [e.value for e in at.exception]

md_texts = [str(m.value) for m in at.markdown]
assert any("卡淘" in t and "成交" in t for t in md_texts), "FAIL: 结果区未见卡淘成交标题"
assert len(at.tabs) == 0, "FAIL: 评估后页面出现 tabs"
assert not any("eBay" in t for t in md_texts), "FAIL: 评估后结果区出现 eBay"
print("  结果区为卡淘单容器、无 eBay、无 tabs ✓")

print("=== 6) AI 助手聊天面板（无 Key → 降级回复）===")
# 聊天面板标题
exp_labels = [e.label for e in at.expander]
assert any("AI 助手" in lbl for lbl in exp_labels), "FAIL: AI 助手 expander 未出现"
# 聊天输入框 + 发送
assert at.text_input(key="agent_input") is not None, "FAIL: 聊天输入框不存在"
at.text_input(key="agent_input").set_value("文班亚马 Prizm 银折值多少钱？")
at.button(key="btn_agent_send").click()
at.run()
assert not at.exception, [e.value for e in at.exception]

msgs = []
for cm in at.chat_message:
    for m in cm.markdown:
        msgs.append(str(m.value))
print(f"  聊天消息数: {len(msgs)}")
assert len(msgs) == 2, f"FAIL: 期望 2 条消息（user+assistant），实际 {len(msgs)}"
assert "文班亚马" in msgs[0], "FAIL: 用户消息未渲染"
assert "OPENAI_API_KEY" in msgs[1], "FAIL: 降级回复未包含配置指引"
# 降级提示 info
infos = [str(i.value) for i in at.info]
assert any("OPENAI_API_KEY" in i for i in infos), "FAIL: 降级提示未显示"
print("  聊天面板：user 消息 + 降级回复（含配置指引）+ 降级提示 ✓")

print("\nALL_CARDHOBBY_ASSERTS_PASS")
