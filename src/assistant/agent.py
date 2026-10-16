"""
CardAgent：OpenAI 兼容 LLM 智能助手（function calling）
=====================================================
默认对接 DeepSeek（国内直连）；任何 OpenAI 兼容服务只需改环境变量。

配置（环境变量，双进程共享）:
    OPENAI_API_KEY   必填，未配置时降级返回配置指引（degraded=True）
    OPENAI_BASE_URL  可选，默认 https://api.deepseek.com
    AGENT_MODEL      可选，默认 deepseek-chat

工具:
    evaluate_card           评估卡片价值（pricing_service，输出美元）
    resolve_player          球员识别（本地 → 缓存 → 联网）
    search_price_reference  卡淘成交参考（本地数据库 → 卡淘实时列表）

用法:
    from src.assistant.agent import CardAgent
    result = CardAgent().chat([{"role": "user", "content": "文班亚马 Prizm 银折估价"}])
    # -> {reply, tool_calls, degraded}
"""

import json
import os
from typing import Dict, List, Optional, Any

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

# ---- 配置文件 agent.env（项目根目录，免设环境变量；环境变量优先于文件） ----
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ENV_FILE = os.path.join(_PROJECT_ROOT, "agent.env")


def _load_env_file() -> None:
    """从项目根 agent.env 读取 LLM 配置（每行 KEY=VALUE，# 开头为注释）"""
    try:
        if not os.path.exists(_ENV_FILE):
            return
        with open(_ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    # setdefault：PowerShell 已设的 $env: 优先，文件仅兜底
                    os.environ.setdefault(key, value)
    except Exception:
        pass


_load_env_file()

_CONFIGURE_GUIDE = (
    "尚未配置 LLM API Key，AI 估价助手处于降级模式（只能做卡片评估，无法智能对话）。\n\n"
    "配置方法（PowerShell）：\n"
    "  $env:OPENAI_API_KEY = \"sk-...\"                # 必填，例如 DeepSeek 的 key\n"
    "  $env:OPENAI_BASE_URL = \"https://api.deepseek.com\"   # 可选，默认已是 DeepSeek\n"
    "  $env:AGENT_MODEL = \"deepseek-chat\"            # 可选\n"
    "配置完成后重启 Streamlit / API 服务即可生效。"
)

SYSTEM_PROMPT = """你是球星卡估价助手，服务于一个球星卡价值分析系统。

可用工具：
1. evaluate_card —— 按卡片属性评估价值。传入完整属性（球员、产品、年份、折射等级、限量、签字、物料、评级等）。模型估价单位为【美元 USD】。
2. resolve_player —— 识别球员信息（球队/位置/新秀年/等级），用于本地球员库没有的冷门球员。
3. search_price_reference —— 查询该球员近期真实成交参考，来源为【卡淘 CardHobby 人民币 CNY】。

币种规则（务必遵守）：
- 模型估价 = 美元；卡淘真实成交参考 = 人民币（≈ ×7.25 换算）。
- 回答时注明币种，例如"模型估价约 $300（≈ ¥2,175），卡淘近期成交 ¥1,800"。

行为准则：
- 只在需要时才调用工具，不要为了展示而调用。
- 不要编造价格；工具未返回真实数据时明确说明。
- 回答使用简体中文，简洁友好。
"""

# ---- 工具 schema（OpenAI 兼容 function calling） ----

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_card",
            "description": "评估一张球星卡的价值（模型估价，单位美元 USD）。给出完整卡片属性。",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "球员英文名，如 Victor Wembanyama"},
                    "product": {"type": "string", "description": "产品系列: Prizm / Select / National Treasures / Donruss / Mosaic"},
                    "card_year": {"type": "integer", "description": "卡片年份", "minimum": 1986, "maximum": 2025},
                    "is_rookie": {"type": "boolean", "description": "是否新秀年卡片", "default": False},
                    "refraction_level": {"type": "integer", "description": "折射等级 0=Base 1=Silver 2=Gold 3=Mojo 4=Black 5=1of1", "minimum": 0, "maximum": 5, "default": 0},
                    "serial_number": {"type": "integer", "description": "编号（0=未编号）", "minimum": 0, "default": 0},
                    "serial_max": {"type": "integer", "description": "限量总数（0=未编号）", "minimum": 0, "default": 0},
                    "is_jersey_match": {"type": "boolean", "description": "是否同背编号（编号=球衣号）", "default": False},
                    "has_auto": {"type": "boolean", "description": "是否有签字", "default": False},
                    "auto_type": {"type": "integer", "description": "签字类型 0=无 1=贴签 2=卡签 3=铭文签", "minimum": 0, "maximum": 3, "default": 0},
                    "has_material": {"type": "boolean", "description": "是否有物料", "default": False},
                    "material_windows": {"type": "integer", "description": "Patch窗口数", "minimum": 0, "maximum": 10, "default": 0},
                    "material_colors": {"type": "integer", "description": "Patch颜色数", "minimum": 0, "maximum": 10, "default": 0},
                    "is_logoman": {"type": "boolean", "description": "是否Logoman", "default": False},
                    "is_tag": {"type": "boolean", "description": "是否Tag", "default": False},
                    "material_source": {"type": "integer", "description": "物料来源 0=无 1=球衣 2=比赛穿 3=Prime", "minimum": 0, "maximum": 3, "default": 0},
                    "has_grade": {"type": "boolean", "description": "是否已评级", "default": False},
                    "grade_score": {"type": "number", "description": "评级分数 (0=未评级)", "minimum": 0, "maximum": 10, "default": 0},
                    "grade_grader": {"type": "integer", "description": "评级公司 0=无 1=PSA 2=BGS 3=SGC", "minimum": 0, "maximum": 3, "default": 0},
                },
                "required": ["player_name", "product", "card_year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_player",
            "description": "识别球员信息：本地球员库 → 联网识别（球队/位置/新秀年/等级）。用于冷门球员。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "球员名（中英文均可）"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_price_reference",
            "description": "查询球员近期卡淘真实成交参考（人民币 CNY）。本地数据库优先，无命中时实时采集卡淘列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "球员英文名"},
                    "max_pages": {"type": "integer", "description": "实时采集页数（1-3，默认2）", "minimum": 1, "maximum": 3, "default": 2},
                },
                "required": ["player_name"],
            },
        },
    },
]

CONFIG_GUIDE_REPLY = _CONFIGURE_GUIDE


class CardAgent:
    """OpenAI 兼容 LLM 估价助手（function calling 循环）"""

    def __init__(self, client: Optional[Any] = None, assistant: Optional[Any] = None):
        """
        Args:
            client: 可注入的 OpenAI 客户端（测试用）；None 时惰性创建
            assistant: 可注入的 CardAssistant（工具后端）；None 时默认创建
        """
        self._client = client
        self._assistant = assistant
        self.base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or DEFAULT_BASE_URL
        self.model = os.environ.get("AGENT_MODEL", "").strip() or DEFAULT_MODEL

    # ============================================================
    # 配置与客户端
    # ============================================================

    def is_configured(self) -> bool:
        """是否已配置 LLM API Key"""
        return bool(os.environ.get("OPENAI_API_KEY", "").strip())

    def _make_client(self) -> Any:
        """惰性创建 OpenAI 兼容客户端（openai>=1.30，支持 base_url）；库缺失返回 None"""
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError:
            return None  # chat() 会给出降级提示
        self._client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=self.base_url,
            timeout=30,
        )
        return self._client

    # ============================================================
    # 工具执行
    # ============================================================

    def _backend(self):
        """惰性创建 CardAssistant 工具后端"""
        if self._assistant is None:
            from src.assistant.card_assistant import CardAssistant
            self._assistant = CardAssistant()
        return self._assistant

    def run_tool(self, name: str, arguments: dict) -> dict:
        """执行单个工具，返回 {ok, summary, data}"""
        try:
            if name == "evaluate_card":
                from src.services.pricing_service import evaluate_card_dict
                r = evaluate_card_dict(arguments)
                return {
                    "ok": True,
                    "summary": (f"估价 ${r['price']:,.0f} (95% CI ${r['ci_low']:,.0f}~"
                                f"${r['ci_high']:,.0f}); 特殊: {', '.join(r['special_flags']) or '无'}"),
                    "data": {k: r[k] for k in ("price", "ci_low", "ci_high", "special_flags")},
                }
            if name == "resolve_player":
                info = self._backend().resolve_player(str(arguments.get("name", "")))
                if not info:
                    return {"ok": False, "summary": "未能识别该球员", "data": None}
                summary = (f"{info.get('name')} | {info.get('team') or '球队未知'} | "
                           f"位置 {info.get('position') or '-'} | "
                           f"新秀年 {info.get('rookie_year') or '-'} | "
                           f"来源 {info.get('source', '')}")
                return {"ok": True, "summary": summary, "data": info}
            if name == "search_price_reference":
                max_pages = min(int(arguments.get("max_pages", 2)), 3)
                hits = self._backend().search_price_reference(
                    str(arguments.get("player_name", "")), max_pages=max_pages)
                if not hits:
                    return {"ok": True, "summary": "未找到该球员的卡淘成交记录", "data": []}
                lines = []
                for h in hits[:5]:
                    price = h.get("price_cny")
                    lines.append(f"{h.get('title', '')[:30]} ¥{price if price is not None else '?'}"
                                 f" ({h.get('source', '')})")
                return {
                    "ok": True,
                    "summary": f"找到 {len(hits)} 条卡淘参考:\n" + "\n".join(lines),
                    "data": hits,
                }
            return {"ok": False, "summary": f"未知工具: {name}", "data": None}
        except Exception as e:
            return {"ok": False, "summary": f"工具执行失败: {e}", "data": None}

    # ============================================================
    # 对话主循环
    # ============================================================

    def chat(self, messages: List[Dict[str, Any]], max_tool_rounds: int = 4,
             context: str = "") -> Dict[str, Any]:
        """
        单轮对话（内部可能多轮工具调用）

        Args:
            messages: OpenAI 风格消息列表（session 已含 system/user/assistant/tool 历史）
            max_tool_rounds: 工具调用轮数上限（防死循环）
            context: 附加系统上下文（如界面同步的当前卡片信息），拼在系统提示之后

        Returns:
            {reply, tool_calls(已执行记录), degraded}
        """
        if not self.is_configured():
            return {"reply": CONFIG_GUIDE_REPLY, "tool_calls": [], "degraded": True}

        history = list(messages)[-_MAX_HISTORY:]
        if not any(m.get("role") == "system" for m in history):
            system_content = SYSTEM_PROMPT + (f"\n\n{context}" if context else "")
            history = [{"role": "system", "content": system_content}] + history

        client = self._make_client()
        if client is None:
            return {
                "reply": ("缺少 openai 库。请在项目目录执行:\n"
                          "  pip install -r requirements.txt\n"
                          "（或 pip install openai）\n然后重启本应用。"),
                "tool_calls": [],
                "degraded": True,
            }

        executed: List[Dict[str, Any]] = []

        for _round in range(max_tool_rounds + 1):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=history,
                    tools=TOOLS,
                    tool_choice="auto",
                )
            except Exception as e:
                return {
                    "reply": f"调用 LLM 失败：{e}\n\n请检查 OPENAI_API_KEY 是否有效、网络是否可达。",
                    "tool_calls": executed,
                    "degraded": True,
                }

            msg = resp.choices[0].message
            if not msg.tool_calls:
                # 最终自然语言回复
                return {
                    "reply": msg.content or "（模型未返回内容）",
                    "tool_calls": executed,
                    "degraded": False,
                }

            # ---- 模型请求工具调用：把 assistant 消息 + 工具结果追加进历史 ----
            assistant_entry: Dict[str, Any] = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            history.append(assistant_entry)

            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self.run_tool(tc.function.name, args)
                executed.append({
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                    "result_summary": result["summary"],
                })
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"ok": result["ok"], "summary": result["summary"]},
                                          ensure_ascii=False),
                })

            # 截断历史（保留 system 消息）
            if len(history) > _MAX_HISTORY:
                history = [history[0]] + history[-(_MAX_HISTORY - 1):]

        return {
            "reply": "本轮工具调用次数已达上限，请换个问法再试。",
            "tool_calls": executed,
            "degraded": False,
        }


_MAX_HISTORY = 20
