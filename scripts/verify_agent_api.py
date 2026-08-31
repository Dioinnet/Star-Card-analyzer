"""验证：/api/agent/chat 接口（降级 / 会话递增 / 工具透传）+ /evaluate /health 回归

前提：环境变量中不要设置 OPENAI_API_KEY（否则会真实调 LLM）
"""
import io
import os
import sys
from unittest.mock import patch

sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient

from src.api import main as api_main

# 隔离 agent.env 中的真实 key：本测试只验证降级路径与透传，不真调 LLM
os.environ["OPENAI_API_KEY"] = ""

BOUKNIGHT_PAYLOAD = {
    "player_name": "James Bouknight", "product": "Prizm", "card_year": 2021,
    "is_rookie": True, "refraction_level": 5, "serial_max": 1,
}

with TestClient(api_main.app) as c:
    print("=== 1) /health 回归 ===")
    h = c.get("/health").json()
    assert h["status"] == "ok" and h["model_loaded"] is True
    print(f"  health: {h}")

    print("=== 2) /evaluate 回归（pricing_service 抽取后逐字段一致）===")
    ev = c.post("/evaluate", json=BOUKNIGHT_PAYLOAD).json()
    assert abs(ev["estimated_price"] - 410.98) < 0.01, f"FAIL: price={ev['estimated_price']}"
    assert abs(ev["ci_low"] - 31.26) < 0.01 and abs(ev["ci_high"] - 3826.52) < 0.01
    assert ev["attribution"] and ev["attribution"][0]["feature"] == "折射等级"
    assert ev["special_flags"] == ["新秀 1/1 (顶级稀有)"]
    print(f"  /evaluate: ${ev['estimated_price']} CI {ev['ci_low']}~{ev['ci_high']} "
          f"attribution[0]={ev['attribution'][0]} ✓")

    print("=== 3) /api/agent/chat 无 Key → 降级 ===")
    r = c.post("/api/agent/chat", json={
        "messages": [{"role": "user", "content": "Bouknight 1/1 估价"}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["degraded"] is True, body
    assert body["session_id"], "FAIL: session_id 为空"
    assert "OPENAI_API_KEY" in body["reply"], "FAIL: 降级回复无配置指引"
    print(f"  degraded=True, session_id={body['session_id'][:8]}..., reply 含配置指引 ✓")

    print("=== 4) 同 session_id 二次调用 → 会话递增 ===")
    sid = body["session_id"]
    len_before = len(api_main._SESSIONS[sid])
    r2 = c.post("/api/agent/chat", json={
        "session_id": sid,
        "messages": [{"role": "user", "content": "再估一下文班亚马"}],
    })
    assert r2.status_code == 200
    len_after = len(api_main._SESSIONS[sid])
    assert len_after == len_before + 2, f"FAIL: 会话未递增 {len_before}->{len_after}"
    print(f"  会话长度 {len_before} -> {len_after} ✓")

    print("=== 5) monkeypatch 假 CardAgent → 透传 ===")
    received = {}

    class FakeAgent:
        def __init__(self):
            pass

        def chat(self, messages):
            received["messages"] = list(messages)
            return {"reply": "测试回复", "tool_calls": [
                {"name": "evaluate_card", "arguments": "{}",
                 "result_summary": "估价 $1"}],
                "degraded": False}

    with patch("src.assistant.agent.CardAgent", FakeAgent):
        r3 = c.post("/api/agent/chat", json={
            "session_id": sid,
            "messages": [{"role": "user", "content": "透传测试"}],
        })
        assert r3.status_code == 200
        b3 = r3.json()
        assert b3["reply"] == "测试回复" and b3["degraded"] is False
        assert b3["tool_calls"][0]["name"] == "evaluate_card"
        # 假 Agent 收到的是服务端会话（含历史，而非客户端伪造的完整 messages）
        got = received["messages"]
        assert got[-1] == {"role": "user", "content": "透传测试"}, got[-1]
        assert len(got) >= 4, "FAIL: 服务端会话未带上历史"
        roles = [m["role"] for m in got]
        # chat() 收到的 store 以本次 user 结尾（assistant 回复在 chat 返回后才追加）
        assert roles.count("user") == roles.count("assistant") + 1, roles
        assert roles[-1] == "user", roles
        print(f"  透传 OK：服务端会话 {len(got)} 条，仅追加最后一条 user ✓")

    print("=== 6) 缺 user 消息 → 422 ===")
    r4 = c.post("/api/agent/chat", json={"messages": [{"role": "assistant", "content": "hi"}]})
    assert r4.status_code == 422
    print("  422 ✓")

print("\nALL_AGENT_API_ASSERTS_PASS")
