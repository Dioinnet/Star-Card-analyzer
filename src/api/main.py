"""
FastAPI 球星卡估价服务
=====================
提供 REST API 接口用于球星卡价值评估与 AI 助手对话。

启动方式:
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000
    uvicorn src.api.main:app --reload  # 开发模式

接口:
    GET  /health          — 健康检查
    POST /evaluate        — 评估卡片价值
    POST /api/agent/chat  — AI 助手对话（OpenAI 兼容 LLM，工具调用评估/识别/卡淘参考）
"""

import sys
import os
import uuid
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.services.pricing_service import (
    load_models as _svc_load_models,
    evaluate_card_dict as _svc_evaluate,
    is_loaded as _svc_is_loaded,
)

# ============================================================
# 请求/响应模型
# ============================================================

class CardRequest(BaseModel):
    """卡片评估请求"""
    player_name: str = Field(..., description="球员名称，如 LeBron James, Victor Wembanyama")
    product: str = Field(..., description="产品系列: Prizm / Select / National Treasures / Donruss / Mosaic")
    card_year: int = Field(..., ge=1986, le=2025, description="卡片年份")
    is_rookie: bool = Field(False, description="是否新秀年卡片")
    refraction_level: int = Field(0, ge=0, le=5, description="折射等级 0=Base 1=Silver 2=Gold 3=Mojo 4=Black 5=1of1")
    serial_number: int = Field(0, ge=0, description="编号 (0表示未编号)")
    serial_max: int = Field(0, ge=0, description="限量总数 (0表示未编号)")
    is_jersey_match: bool = Field(False, description="是否同背编号 (编号=球衣号)")
    has_auto: bool = Field(False, description="是否有签字")
    auto_type: int = Field(0, ge=0, le=3, description="签字类型 0=无 1=贴签 2=卡签 3=铭文签")
    has_material: bool = Field(False, description="是否有物料")
    material_windows: int = Field(0, ge=0, le=10, description="Patch窗口数")
    material_colors: int = Field(0, ge=0, le=10, description="Patch颜色数")
    is_logoman: bool = Field(False, description="是否Logoman")
    is_tag: bool = Field(False, description="是否Tag")
    material_source: int = Field(0, ge=0, le=3, description="物料来源 0=无 1=球衣 2=比赛穿 3=Prime")
    has_grade: bool = Field(False, description="是否已评级")
    grade_score: float = Field(0.0, ge=0.0, le=10.0, description="评级分数 (0.0表示未评级)")
    grade_grader: int = Field(0, ge=0, le=3, description="评级公司 0=无 1=PSA 2=BGS 3=SGC")


class AttributionItem(BaseModel):
    """归因项"""
    feature: str = Field(..., description="特征名称（中文）")
    contribution: float = Field(..., description="价格贡献 (¥)")


class EvaluationResponse(BaseModel):
    """评估结果"""
    estimated_price: float = Field(..., description="预估价格 (¥)")
    ci_low: float = Field(..., description="置信区间下界 (¥)")
    ci_high: float = Field(..., description="置信区间上界 (¥)")
    attribution: List[AttributionItem] = Field(default_factory=list, description="SHAP归因列表")
    special_flags: List[str] = Field(default_factory=list, description="特殊标记 (RPA, Logoman1/1等)")


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    model_loaded: bool
    encoder_loaded: bool


# ---- AI 助手对话 ----

class AgentMessage(BaseModel):
    """对话消息（OpenAI 兼容）"""
    role: str = Field(..., description="system/user/assistant/tool")
    content: str = Field("", description="消息内容")
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class AgentChatRequest(BaseModel):
    """AI 助手对话请求"""
    messages: List[AgentMessage] = Field(..., min_length=1, description="对话消息（取最后一条 user 消息追加进会话）")
    session_id: str = Field("", description="会话 ID，留空自动生成")


class AgentChatResponse(BaseModel):
    """AI 助手对话响应"""
    reply: str = Field(..., description="助手回复")
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list, description="本次执行的工具调用记录")
    session_id: str = Field(..., description="会话 ID")
    degraded: bool = Field(False, description="是否降级模式（未配置 LLM API Key）")


# ============================================================
# AI 助手会话管理（内存实现；重启即失，后续可换 Redis/DB）
# ============================================================
_SESSIONS: Dict[str, List[Dict[str, Any]]] = {}
_MAX_SESSIONS = 200
_MAX_SESSION_LEN = 20


def _get_session(sid: str) -> List[Dict[str, Any]]:
    store = _SESSIONS.setdefault(sid, [])
    if len(_SESSIONS) > _MAX_SESSIONS:
        _SESSIONS.pop(next(iter(_SESSIONS)))  # 简单 LRU-ish 淘汰
    return store


# ============================================================
# FastAPI 应用
# ============================================================

app = FastAPI(
    title="球星卡价值分析系统",
    description="基于XGBoost和SHAP的球星卡价值评估API",
    version="1.1.0",
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """应用启动时加载模型"""
    _svc_load_models()


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    loaded = _svc_is_loaded()
    return HealthResponse(
        status="ok",
        model_loaded=loaded,
        encoder_loaded=loaded,
    )


@app.post("/evaluate", response_model=EvaluationResponse)
async def evaluate_card(card: CardRequest):
    """
    评估一张球星卡的价值

    接收卡片属性，返回预估价格、置信区间和特征归因。
    """
    try:
        result = _svc_evaluate(card.model_dump())
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评估失败: {str(e)}")

    return EvaluationResponse(
        estimated_price=result["price"],
        ci_low=result["ci_low"],
        ci_high=result["ci_high"],
        attribution=[AttributionItem(**item) for item in result["attribution"]],
        special_flags=result["special_flags"],
    )


@app.post("/api/agent/chat", response_model=AgentChatResponse)
def agent_chat(req: AgentChatRequest):
    """
    AI 助手对话（预留接口）

    请求体兼容 OpenAI 消息格式；只取最后一条 user 消息追加进会话
    （避免客户端伪造历史）。未配置 OPENAI_API_KEY 时降级返回配置指引。
    """
    sid = req.session_id or uuid.uuid4().hex
    store = _get_session(sid)

    last_user = ""
    for m in reversed(req.messages):
        if m.role == "user" and m.content.strip():
            last_user = m.content.strip()
            break
    if not last_user:
        raise HTTPException(status_code=422, detail="messages 中缺少 user 消息")

    store.append({"role": "user", "content": last_user})

    from src.assistant.agent import CardAgent
    result = CardAgent().chat(store)

    store.append({"role": "assistant", "content": result["reply"]})
    del store[:-_MAX_SESSION_LEN]  # 截断

    return AgentChatResponse(**result, session_id=sid)


# ============================================================
# 直接运行
# ============================================================
if __name__ == "__main__":
    import uvicorn
    print("启动球星卡价值分析 API 服务...")
    print(f"接口: /health /evaluate /api/agent/chat")
    uvicorn.run(app, host="0.0.0.0", port=8000)
