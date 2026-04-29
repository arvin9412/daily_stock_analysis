"""
Chatbot API Server for daily_stock_analysis

基于 Chatbot.md 需求设计：
- 角色：股票专家 + 用户的老朋友，专业但口语化
- 输入：两份 JSON 分析结果 + 对话历史 + 用户画像
- 功能：意图识别 → 回复生成 → 个性化润色 → 反问收集画像
"""

import json
import os
import time
import uuid
import asyncio
from pathlib import Path
from typing import Optional, Union
from contextlib import asynccontextmanager

# Auto-load .env from project root
_root_dir = Path(__file__).resolve().parent.parent.parent
_env_path = _root_dir / ".env"
print(f"[DEBUG] Checking .env at: {_env_path}")
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()
else:
    print(f"[WARNING] .env file not found at {_env_path}")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "chatbot_web" / "data"
WEB_DIR = BASE_DIR / "chatbot_web"

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", os.getenv("OPENAI_API_KEY", ""))
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
)
DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", os.getenv("OPENAI_MODEL", "qwen-plus"))


# ──────────────────────────────────────────────
# Data Loader
# ──────────────────────────────────────────────
class ChatbotKnowledge:
    """加载并合并两份 JSON，构建统一知识库"""

    def __init__(self, ticker: str = "AMZN"):
        self.ticker = ticker
        self.summary_json = {}
        self.structured_json = {}
        self.merged = {}
        self.load(ticker)

    def load(self, ticker: str):
        """加载新的嵌套结构 JSON 文件，支持递归查找最新日期的文件"""
        self.ticker = ticker
        ticker_dir = DATA_DIR / ticker
        if not ticker_dir.exists():
            print(f"[DEBUG] Ticker directory not found: {ticker_dir}")
            return

        # 找到所有匹配 {ticker}_{DATE}.json 的文件
        all_files = list(ticker_dir.rglob(f"{ticker}_*.json"))
        if not all_files:
            print(f"[DEBUG] No JSON files found for {ticker} in {ticker_dir}")
            return

        # 按日期排序，找到最新的
        # 文件名格式: AMZN_2026-04-22.json
        def extract_date(p: Path):
            name = p.stem  # AMZN_2026-04-22
            parts = name.split("_")
            dt = parts[-1] if len(parts) > 1 else ""
            return dt if dt.replace("-", "").isdigit() else ""

        # 找到最新的日期
        latest_files = sorted(all_files, key=lambda p: extract_date(p), reverse=True)
        latest_date = extract_date(latest_files[0])
        print(f"[DEBUG] Found latest date: {latest_date}")

        # 加载两个分析文件
        for p in all_files:
            if extract_date(p) != latest_date:
                continue

            if "tradingAgent_analysis" in str(p):
                print(f"[DEBUG] Loading tradingAgent_analysis: {p}")
                with open(p, "r", encoding="utf-8") as f:
                    self.summary_json = json.load(f)
            elif "daily_analysis" in str(p):
                print(f"[DEBUG] Loading daily_analysis: {p}")
                with open(p, "r", encoding="utf-8") as f:
                    self.structured_json = json.load(f)

        self._merge()

    def _merge(self):
        """合并 daily_analysis 和 tradingAgent_analysis 的数据"""
        # 1. 准备默认的空 merged 数据结构，防止 KeyError
        self.merged = {
            "ticker": self.ticker,
            "trade_date": "",
            "market_snapshot": "",
            "fundamentals_one": "暂无数据",
            "fundamentals_three": "暂无数据",
            "fundamentals_detailed": "暂无数据",
            "market_one": "暂无数据",
            "market_three": "暂无数据",
            "market_detailed": "暂无数据",
            "events_one": "暂无数据",
            "events_three": "暂无数据",
            "events_detailed": "暂无数据",
            "upcoming_one": "暂无数据",
            "upcoming_three": "暂无数据",
            "upcoming_detailed": "暂无数据",
            "macro_trend_one": "暂无数据",
            "macro_trend_three": "暂无数据",
            "macro_trend_detailed": "暂无数据",
            "investment_ideas_one": "暂无数据",
            "investment_ideas_three": "暂无数据",
            "investment_ideas_detailed": "暂无数据",
            "levels_one": "暂无数据",
            "levels_three": "暂无数据",
            "levels_detailed": "暂无数据",
            "strategy_empty_one": "暂无数据",
            "strategy_light_one": "暂无数据",
            "strategy_heavy_one": "暂无数据",
            "short_term_one": "暂无数据",
            "short_term_three": "暂无数据",
            "short_term_detailed": "暂无数据",
            "overall_one": "",
            "overall_three": "",
            "overall_detailed": "",
            "strategy_levels": "",
            "structure_analysis": {},
            "pattern_summary": {},
            "bull_points": [],
            "bear_points": [],
            "manager_points": [],
        }

        # 2. 尝试定位目录 (支持 data/{ticker}/{date}/... 和 data/{ticker}/... 两种结构)
        base_dir = DATA_DIR / self.ticker
        if not base_dir.exists():
            return

        # 寻找最近的日期文件夹
        date_dirs = sorted(
            [d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith("20")],
            reverse=True,
        )

        daily_dir = None
        trading_dir = None

        if date_dirs:
            latest_date_dir = date_dirs[0]
            daily_dir = latest_date_dir / "daily_analysis"
            trading_dir = latest_date_dir / "tradingAgent_analysis"

        # 如果没找到日期文件夹，直接在 ticker 目录下找
        if not daily_dir or not daily_dir.exists():
            daily_dir = base_dir / "daily_analysis"
        if not trading_dir or not trading_dir.exists():
            trading_dir = base_dir / "tradingAgent_analysis"

        # 2. 加载 tradingAgent_analysis (作为 summary_json)
        self.summary_json = {}
        if trading_dir and trading_dir.exists():
            trading_files = sorted(trading_dir.glob("*.json"), reverse=True)
            if trading_files:
                try:
                    with open(trading_files[0], "r") as f:
                        self.summary_json = json.load(f)
                except Exception:
                    pass

        # 3. 加载 daily_analysis (作为 structured_json)
        self.structured_json = {}
        if daily_dir and daily_dir.exists():
            daily_files = sorted(daily_dir.glob("*.json"), reverse=True)
            if daily_files:
                try:
                    with open(daily_files[0], "r") as f:
                        self.structured_json = json.load(f)
                except Exception:
                    pass

        s = self.summary_json
        d = self.structured_json

        def get_field_depth(data, level_key, default=""):
            if data is None:
                return default
            if isinstance(data, dict):
                return data.get(level_key, default)
            return str(data) if level_key == "one" else default

        # 1. 提取 tradingAgent_analysis 中的字段
        macro_trend = s.get("macro_trend", {})
        investment_ideas = s.get("investment_ideas", {})
        fundamentals = s.get("fundamentals", {})
        market = s.get("market", {})
        events = s.get("events", {})
        upcoming = s.get("upcoming", {})
        levels = s.get("levels", {})
        strategy = s.get("strategy", {})
        debate = s.get("debate", {})

        # 2. 准备 daily_analysis 的内容
        self.steps = []
        market_snapshot = ""
        pipeline = d.get("llm_pipeline", {})
        market_snapshot = pipeline.get("market_snapshot", "")
        self.steps = pipeline.get("steps", [])

        # 3. 匹配几个核心的 daily_analysis step
        overall_output = {}
        structure_analysis = {}
        pattern_summary = {}
        for step in self.steps:
            title = step.get("title", "")
            output = step.get("output_json", {})
            if not output:
                continue
            if any(
                k in title for k in ["整体宏观走势", "宏观分析结果总结", "总体分析结论"]
            ):
                overall_output = output
            elif "结构侧分析" in title:
                structure_analysis = output
            elif "特殊形态" in title:
                pattern_summary = output

        if not overall_output and self.steps:
            overall_output = self.steps[0].get("output_json", {})

        self.merged = {
            "ticker": self.ticker,
            "trade_date": s.get("date", d.get("date", "")),
            "market_snapshot": market_snapshot,
            "fundamentals_one": get_field_depth(fundamentals, "one"),
            "fundamentals_three": get_field_depth(fundamentals, "three"),
            "fundamentals_detailed": get_field_depth(fundamentals, "detailed"),
            "market_one": get_field_depth(market, "one"),
            "market_three": get_field_depth(market, "three"),
            "market_detailed": get_field_depth(market, "detailed"),
            "events_one": get_field_depth(events, "one"),
            "events_three": get_field_depth(events, "three"),
            "events_detailed": get_field_depth(events, "detailed"),
            "upcoming_one": get_field_depth(upcoming, "one"),
            "upcoming_three": get_field_depth(upcoming, "three"),
            "upcoming_detailed": get_field_depth(upcoming, "detailed"),
            "macro_trend_one": get_field_depth(macro_trend, "one"),
            "macro_trend_three": get_field_depth(macro_trend, "three"),
            "macro_trend_detailed": get_field_depth(macro_trend, "detailed"),
            "investment_ideas_one": get_field_depth(investment_ideas, "one"),
            "investment_ideas_three": get_field_depth(investment_ideas, "three"),
            "investment_ideas_detailed": get_field_depth(investment_ideas, "detailed"),
            "levels_one": get_field_depth(levels, "one"),
            "levels_three": get_field_depth(levels, "three"),
            "levels_detailed": get_field_depth(levels, "detailed"),
            "strategy_empty_one": get_field_depth(strategy.get("empty"), "one"),
            "strategy_light_one": get_field_depth(strategy.get("light"), "one"),
            "strategy_heavy_one": get_field_depth(strategy.get("heavy"), "one"),
            "short_term_one": get_field_depth(s.get("short_term_strategy"), "one"),
            "short_term_three": get_field_depth(s.get("short_term_strategy"), "three"),
            "short_term_detailed": get_field_depth(
                s.get("short_term_strategy"), "detailed"
            ),
            "overall_one": overall_output.get("one", ""),
            "overall_three": overall_output.get("three", ""),
            "overall_detailed": overall_output.get("detailed", ""),
            "strategy_levels": overall_output.get("strategy_levels", ""),
            "structure_analysis": structure_analysis,
            "pattern_summary": pattern_summary,
            "bull_points": debate.get("bull", []) if isinstance(debate, dict) else [],
            "bear_points": debate.get("bear", []) if isinstance(debate, dict) else [],
            "manager_points": debate.get("manager", [])
            if isinstance(debate, dict)
            else [],
        }

    def get_knowledge_text(self) -> str:
        """生成供 LLM 使用的知识文本"""
        m = self.merged
        if not m:
            return "暂无此股票的详细分析数据，请根据一般市场常识回答。"

        text = f"""
以下是针对 {self.ticker} 的最新分析报告（供参考）：

【1. Fundamentals (公司基本面分析)】
- {m.get("fundamentals_detailed", "暂无数据")}

【2. Market Trend (市场走势分析)】
- {m.get("market_detailed", "暂无数据")}

【3. Key Events (重大事件影响)】
- {m.get("events_detailed", "暂无数据")}

【4. Upcoming (预期展望)】
- {m.get("upcoming_detailed", "暂无数据")}

【5. Support & Resistance (关键点位)】
- {m.get("levels_detailed", "暂无数据")}

【6. Long-term Strategy (长线交易策略)】
- 轻仓建议：{m.get("strategy_light_one", "暂无建议")}
- 重仓建议：{m.get("strategy_heavy_one", "暂无建议")}
- 空仓/待买：{m.get("strategy_empty_one", "暂无建议")}

【7. Short-term Strategy (短线策略建议)】
- 核心建议：{m.get("short_term_detailed", "暂无建议")}

【8. Debate (多空观点对抗)】
- 看多理由：{"; ".join(m.get("bull_points", [])) if m.get("bull_points") else "暂无"}
- 看空理由：{"; ".join(m.get("bear_points", [])) if m.get("bear_points") else "暂无"}
- 专家点评：{"; ".join(m.get("manager_points", [])) if m.get("manager_points") else "暂无"}
"""
        return text

    def get_prepared_questions(self) -> list[str]:
        """返回预置问题列表"""
        return [
            "当前走势怎么看？",
            "基本面怎么样？",
            "近期有什么大事件？",
            "未来有什么看点？",
            "关键支撑阻力位在哪？",
            "短线有机会吗？",
            "长线值得拿吗？",
            "现在该买还是该卖？",
            "持仓怎么办？",
            "风险在哪？",
        ]

    def get_topic_json_fields(self) -> dict[str, dict[str, str]]:
        """话题到 JSON 字段的映射，支持渐进式读取 (主要针对 Trading Agent 数据)"""
        return {
            "总结：总结股票整体宏观走势分析": {
                "one": "macro_trend_one",
                "three": "macro_trend_three",
                "detailed": "macro_trend_detailed",
            },
            "总结：总结股票整体长期投资思路": {
                "one": "investment_ideas_one",
                "three": "investment_ideas_three",
                "detailed": "investment_ideas_detailed",
            },
            "基本面与股价：公司基本面情况": {
                "one": "fundamentals_one",
                "three": "fundamentals_three",
                "detailed": "fundamentals_detailed",
            },
            "基本面与股价：近期股价波动原因": {
                "one": "market_one",
                "three": "market_three",
                "detailed": "market_detailed",
            },
            "基本面与股价：近期大事件分析": {
                "one": "events_one",
                "three": "events_three",
                "detailed": "events_detailed",
            },
            "基本面与股价：后续重要时间点大事件": {
                "one": "upcoming_one",
                "three": "upcoming_three",
                "detailed": "upcoming_detailed",
            },
            "技术面：当前关键支撑与阻力位": {
                "one": "levels_one",
                "three": "levels_three",
                "detailed": "levels_detailed",
            },
        }

    def get_direct_answer(self, topic: str, depth: int) -> Optional[str]:
        """直接从 JSON 获取对应深度的答案（不调用 LLM）

        depth: 0=一句话, 1=三句话, 2=详细版
        """
        depth_key = {0: "one", 1: "three", 2: "detailed"}[depth]
        depth_label = {0: "一句话", 1: "三句话", 2: "详细"}[depth]

        # 1. 处理 Fusion 逻辑 (TA + DA)
        fusion_topics = {
            "总结：总结股票整体宏观走势分析",
            "总结：总结股票整体长期投资思路",
            "技术面：当前关键支撑与阻力位",
        }

        # 2. 定义 DA 标题映射 (4/29 最新 taxonomy)
        title_map = {
            "总结：总结股票整体宏观走势分析": ["总结股价整体宏观走势分析"],
            "总结：总结股票整体长期投资思路": ["总结股票宏观长期投资思路"],
            "技术面：当前关键支撑与阻力位": ["关键点位提取"],
            "技术面：走势的结构侧分析": ["总结股票走势的结构侧分析"],
            "技术面：走势的趋势分析": ["总结股价走势的趋势侧分析"],
            "技术面：近期走势出现的特殊形态": ["单个特殊形态结果总结"],
            "综合评估：总结整个股票当前走势看法": ["总结整个股票当前看法"],
            "综合评估：总结整个股票过去走势看法": ["总结整个股票过去看法"],
            "综合评估：总结整个股票未来走势看法": ["总结整个股票未来看法"],
            "交易策略：对当前空仓者建议长线交易策略": ["长线投资-空仓（底仓）操作指引"],
            "交易策略：对当前轻仓者建议长线交易策略": ["长线投资-轻仓操作指引"],
            "交易策略：对当前重仓者建议长线交易策略": ["长线投资-重仓操作指引"],
            "交易策略：建议短线交易策略": ["总结所有短线机会"],
        }

        # 获取 DA 结果
        da_answer = None
        target_titles = title_map.get(topic, [])
        if target_titles and hasattr(self, "steps"):
            for step in self.steps:
                title = step.get("title", "")
                for target_title in target_titles:
                    if target_title in title or title in target_title:
                        output = step.get("output_json", {})
                        # 特殊处理：如果是详细版且有 strategy_levels，优先返回它
                        if (
                            depth == 2
                            and "strategy_levels" in output
                            and output["strategy_levels"] != "信息不足，无法判断"
                        ):
                            da_answer = output["strategy_levels"]
                        else:
                            da_answer = output.get(depth_key)
                        break
                if da_answer:
                    break

        # 获取 TA 结果
        ta_answer = None
        mapping = self.get_topic_json_fields()
        if topic in mapping:
            field_name = mapping[topic].get(depth_key)
            if field_name and field_name in self.merged:
                ta_answer = self.merged[field_name]

        # Fusion 组合逻辑
        if topic in fusion_topics:
            if (
                ta_answer
                and da_answer
                and ta_answer != "信息不足，无法判断"
                and da_answer != "信息不足，无法判断"
            ):
                return (
                    f"{depth_label}\n"
                    f"1. TradingAgent反馈：{ta_answer}\n"
                    f"2. DailyStockAnalysis反馈：{da_answer}"
                )
            return da_answer or ta_answer

        # 非 Fusion 逻辑
        return da_answer or ta_answer


# ──────────────────────────────────────────────
# Session Manager
# ──────────────────────────────────────────────
class ChatSession:
    """单个聊天会话"""

    def __init__(self, session_id: str, ticker: str = ""):
        self.session_id = session_id
        self.ticker = ticker
        self.history: list[dict] = []
        self.selected_category: Optional[str] = (
            None  # 记录用户选择的大类：None / "Market" / "Stock"
        )
        self.last_topic: str = ""  # 记住上一次的话题，用于追问场景（如"具体呢"）
        # 每个话题独立的渐进深度：{topic_name: level}，level 0=一句话, 1=三句话, 2=详细, 3+=LLM扩展
        self.topic_depth: dict[str, int] = {}
        self.user_profile: dict = {
            "investment_goals": [],  # 短期/中期/价值投资
            "investment_style": "",  # 快进快出/拿着不动/跟随消息
            "investment_level": "",  # 技术面量化/基本面金融
            "capital_range": "",  # 资金量级
            "stocks": {},  # 个股情况: {ticker: {interest, position, mood}}
            "last_active": time.time(),
        }
        self.message_count = 0

    def add_message(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        self.message_count += 1
        self.last_active = time.time()

    def should_update_profile(self, interval: int = 5) -> bool:
        """每 N 次对话后更新用户画像"""
        return self.message_count > 0 and self.message_count % interval == 0

    def get_topic_depth(self, topic: str) -> tuple[int, str]:
        """获取当前话题的深度级别和对应指令

        渐进式回复：
        - level 0: 一句话（直接从 JSON 取）
        - level 1: 三句话（直接从 JSON 取）
        - level 2: 详细版（直接从 JSON 取）
        - level 3+: 大模型扩展
        """
        level = self.topic_depth.get(topic, 0)

        instruction = {
            0: "【严格限制一句话】用一句话回答，不超过 40 字。只说核心结论，不要铺垫、不要解释、不要分段落，像朋友聊天一样简短直接。",
            1: "【严格限制三句话】用三句话回答，80-120 字。第一句说结论，第二句说原因，第三句给操作建议。不要超过三句话，不要分段落。",
            2: "【详细分析】给出完整分析，200-300 字，分段叙述：先结论、再原因分析、最后操作建议。逻辑链要完整。",
        }.get(
            level,
            "【自由扩展】基于已有分析，进一步展开详细解读，可以展开更多细节、多角度分析，字数不限。",
        )

        return level, instruction

    def advance_topic_depth(self, topic: str):
        """用户追问同一话题时，深度+1"""
        current = self.topic_depth.get(topic, 0)
        self.topic_depth[topic] = current + 1

    def reset_depth(self):
        """切换股票或话题时重置深度"""
        self.topic_depth = {}
        self.last_topic = ""

    def reset_topic_depth(self, topic: str):
        """重置单个话题的深度（切换话题时调用）"""
        if topic in self.topic_depth:
            del self.topic_depth[topic]

    def to_system_prompt(
        self,
        knowledge: Optional["ChatbotKnowledge"],
        user_message: str = "",
        intent: dict = None,
        realtime_price: str = "",
        suggestions: list = None,
        direct_answer: str = None,
    ) -> str:
        """生成系统 Prompt — 分两阶段"""
        p = self.user_profile
        stock_info = ""
        for ticker, info in p["stocks"].items():
            stock_info += f"- {ticker}: 兴趣={info.get('interest', '未知')}, 持仓={info.get('position', '未知')}, 心态={info.get('mood', '未知')}\n"

        # 实时价格信息
        price_info = ""
        if realtime_price:
            price_info = f"\n## 📊 实时股价信息\n{realtime_price}\n"

        # 渐进式深度指令
        topic = intent.get("topic", "NA") if intent else "NA"
        depth_level, depth_instruction = (
            self.get_topic_depth(topic)
            if topic != "NA"
            else (0, "请用简洁口语化回复。")
        )

        if knowledge:
            # 第二阶段：有 JSON 数据
            return f"""你是股票投资专家，也是用户的老朋友。你的任务是给用户专业但口语化的答疑解惑。

## ⚡ 回复长度限制（最高优先级，必须遵守）
{depth_instruction}

## 角色
- 你是股票专家，也是用户的老朋友
- 语言风格：简短专业，口语化，不要有AI味
- 像跟朋友聊天一样直接说事

## 引导指令
{self._get_guidance_prompt(intent, suggestions)}

## 约束
- 避免给确定性的涨跌预测
- 强调适应市场变化，制定两手准备的交易策略
- 该止盈止盈，该止损止损

## 用户画像
- 投资目标：{", ".join(p["investment_goals"]) or "未知"}
- 投资风格：{p["investment_style"] or "未知"}
- 投资水平：{p["investment_level"] or "未知"}
- 资金量级：{p["capital_range"] or "未知"}
- 关注个股：
{stock_info or "暂无记录"}

## 当前股票数据（{knowledge.ticker}）
{knowledge.get_knowledge_text()}

## 预设答案（优先使用此答案）
{direct_answer or ""}

## 回复要求
- 回复要连贯，不要分点列举，用自然段落
- 不要称呼"各位股民朋友"、"兄弟们"等，直接说事
- 如果有预设答案，直接输出预设答案，不需要额外发挥
- 如果用户情绪低落或焦虑，自然地给予心理安慰"""
        else:
            # 第一阶段：没有 JSON 数据，纯聊天
            return f"""你是股票投资专家，也是用户的老朋友。

## 角色
- 你是股票专家，也是用户的老朋友
- 语言风格：简短专业，口语化，不要有AI味
- 像跟朋友聊天一样直接说事

## 引导指令
{self._get_guidance_prompt(intent, suggestions)}

## 用户画像
- 投资目标：{", ".join(p["investment_goals"]) or "未知"}
- 投资风格：{p["investment_style"] or "未知"}
- 投资水平：{p["investment_level"] or "未知"}
- 资金量级：{p["capital_range"] or "未知"}
- 关注个股：
{stock_info or "暂无记录"}

## 约束
- 避免给确定性的涨跌预测
- 不要编造具体数据或点位
- 可以聊投资理念、市场感觉，但不要假装你有具体股票的分析报告"""

    def _get_guidance_prompt(self, intent: dict, suggestions: list) -> str:
        """根据当前意图状态生成引导指令"""
        if not intent:
            return ""

        ticker = intent.get("ticker", "NA")
        topic = intent.get("topic", "NA")
        category = self.selected_category  # Use session state

        # 引导语逻辑
        if not category:
            return "用户刚来，引导用户选择：是想看【大盘分析】，还是【个股分析】？"
        elif category == "Market":
            return "用户选了大盘。简述大盘情况，并引导选择下方的大盘问题。"
        elif category == "Stock":
            if not ticker or ticker == "NA":
                return "用户想看个股。询问具体代码，并引导点击下方股票列表选择。"
            else:
                if topic == "NA":
                    return f"用户提到了 {ticker}。简述现状，并引导用户点击下方 15 个专业维度选择。不要输出 Markdown 链接，自然语言引导即可。"
                else:
                    return f"用户已选定 {ticker} 的 {topic} 维度，请直接给出专业解答。"

    def get_profile_update_prompt(self) -> str:
        """生成用户画像更新 Prompt"""
        history_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in self.history[-20:]
        )
        return f"""根据以下对话历史，分析并更新用户画像。返回 JSON 格式。

现有画像：{json.dumps(self.user_profile, ensure_ascii=False, indent=2)}

对话历史：
{history_text}

请分析：
1. 投资目标：短期/中期/价值投资（可以多选，从对话中推断）
2. 投资风格：快进快出/拿着不动/跟随消息
3. 投资水平：技术面量化知识/基本面金融知识
4. 资金量级：大致范围
5. 对 "{
            self.ticker
        }" 这只股票的兴趣度（无/有一点/很关注）、持仓（空仓/轻仓/重仓）、心态（乐观/恐惧/FOMO/谨慎等）

返回格式（JSON）：
{{
  "investment_goals": ["短期", "价值投资"],
  "investment_style": "拿着不动",
  "investment_level": "基本面金融知识",
  "capital_range": "50-100万",
  "stocks": {
            "{self.ticker}": {
                "interest": "很关注",
      "position": "轻仓",
      "mood": "谨慎"
    }
  }
}}

只返回 JSON，不要其他内容。如果有字段无法判断，保持原有值或填"未知"。"""


import re
import urllib.request


# ──────────────────────────────────────────────
# Real-time Price Tool
# ──────────────────────────────────────────────
def get_realtime_price(ticker: str) -> Optional[dict]:
    """通过 Yahoo Finance 获取实时股价"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            meta = data["chart"]["result"][0]["meta"]
            return {
                "price": meta.get("regularMarketPrice"),
                "prev_close": meta.get("chartPreviousClose"),
                "change": meta.get("regularMarketPrice", 0)
                - meta.get("chartPreviousClose", 0),
                "change_pct": round(
                    (
                        meta.get("regularMarketPrice", 0)
                        - meta.get("chartPreviousClose", 0)
                    )
                    / max(meta.get("chartPreviousClose", 1), 0.01)
                    * 100,
                    2,
                ),
                "currency": meta.get("currency", "USD"),
                "market_time": meta.get("regularMarketTime"),
            }
    except Exception as e:
        return {"error": str(e)}


def is_price_related_question(msg: str) -> bool:
    """判断用户是否在问价格相关问题"""
    price_keywords = [
        "当前价格",
        "现价",
        "现在多少钱",
        "现在什么价",
        "最新价",
        "实时价格",
        "今天价格",
        "股价",
        "现在股价",
        "当前股价",
        "多少钱",
        "什么价",
        "多少",
        "什么价格",
        "最新价格",
        "价格",
        "现价多少",
        "现在多少钱",
        "目前价格",
        "what",
        "price",
        "how much",
        "current price",
    ]
    return any(kw in msg.lower() for kw in price_keywords)


# ──────────────────────────────────────────────
# Pre-configured Questions (from Chatbot_v1.md merged questions)
# ──────────────────────────────────────────────
INITIAL_QUESTIONS = ["大盘分析", "个股分析", "随便聊聊"]
PRE_CONFIGURED_QUESTIONS = [
    "总结：总结股票整体宏观走势分析",
    "总结：总结股票整体长期投资思路",
    "基本面与股价：公司基本面情况",
    "基本面与股价：近期股价波动原因",
    "基本面与股价：近期大事件分析",
    "基本面与股价：后续重要时间点大事件",
    "技术面：当前关键支撑与阻力位",
    "技术面：走势的结构侧分析",
    "技术面：走势的趋势分析",
    "技术面：近期走势出现的特殊形态",
    "综合评估：总结整个股票当前走势看法",
    "综合评估：总结整个股票过去走势看法",
    "综合评估：总结整个股票未来走势看法",
    "交易策略：对当前空仓者建议长线交易策略",
    "交易策略：对当前轻仓者建议长线交易策略",
    "交易策略：对当前重仓者建议长线交易策略",
    "交易策略：建议短线交易策略",
]

MARKET_QUESTIONS = [
    "今日大盘点评",
    "美股主要指数走势",
    "当前市场热点及板块",
    "宏观经济环境解读",
    "最近有哪些重要数据发布？",
]


# 支持的股票代码列表（从新需求目录中扫描）
SUPPORTED_TICKERS: list[str] = []


def _scan_supported_tickers():
    """扫描 DATA_DIR 下支持的股票文件夹"""
    global SUPPORTED_TICKERS
    try:
        if DATA_DIR.exists():
            for d in DATA_DIR.iterdir():
                if d.is_dir():
                    ticker = d.name.upper()
                    if ticker not in SUPPORTED_TICKERS:
                        SUPPORTED_TICKERS.append(ticker)
        print(f"[DEBUG] Scanned supported tickers: {SUPPORTED_TICKERS}")
    except Exception as e:
        print(f"[DEBUG] Error scanning tickers: {e}")


def extract_ticker_from_message(msg: str) -> Optional[str]:
    """从用户消息中提取股票代码，增加中文支持"""
    msg_upper = msg.upper().strip()

    # 1. 大盘关键词
    if any(kw in msg for kw in ["大盘", "市场", "指数"]):
        return "Market"

    # 2. 常见中文名映射
    chinese_map = {
        "特斯拉": "TSLA",
        "亚马逊": "AMZN",
        "苹果": "AAPL",
        "谷歌": "GOOGL",
        "微软": "MSFT",
        "英伟达": "NVDA",
        "腾讯": "HK00700",
        "茅台": "600519",
    }
    for cn_name, ticker in chinese_map.items():
        if cn_name in msg:
            return ticker

    # 3. 优先检查已知支持的股票代码 (从文件夹扫描出来的)
    for ticker in SUPPORTED_TICKERS:
        if ticker in msg_upper:
            return ticker

    # 4. 模糊匹配：寻找符合美股代码规则的连续大写字母
    import re

    codes = re.findall(r"\b[A-Z]{1,5}\b", msg_upper)
    for code in codes:
        if code in {"AM", "PM", "OK", "HI", "HELLO", "STOCK", "THANKS"}:
            continue
        # 检查 DATA_DIR 下是否存在该股票的目录
        if (DATA_DIR / code).exists():
            if code not in SUPPORTED_TICKERS:
                SUPPORTED_TICKERS.append(code)
            return code

    return None


def match_pre_configured_question(msg: str) -> str:
    """判断用户问题属于 15 个预设问题中的哪一个"""
    msg_clean = msg.replace("？", "").replace("?", "").strip()
    # 关键词映射 — 每个关键词都是 2+ 个汉字，避免误匹配股票代码
    keyword_map = {
        "总结：总结股票整体宏观走势分析": ["宏观走势分析", "整体走势分析", "走势总结"],
        "总结：总结股票整体长期投资思路": ["长期投资思路", "投资思路", "投资逻辑"],
        "基本面与股价：公司基本面情况": ["公司基本面", "财务状况", "盈利能力", "基本面情况"],
        "基本面与股价：近期股价波动原因": ["股价波动原因", "近期波动", "为什么涨跌", "波动因素"],
        "基本面与股价：近期大事件分析": ["近期大事件", "重大事件", "新闻分析", "热点事件"],
        "基本面与股价：后续重要时间点大事件": ["后续大事件", "重要时间点", "未来看点", "预期展望"],
        "技术面：当前关键支撑与阻力位": ["支撑与阻力位", "关键点位", "压力位", "支撑位"],
        "技术面：走势的结构侧分析": ["结构侧分析", "波浪形态", "结构判断"],
        "技术面：走势的趋势分析": ["走势的趋势", "趋势分析", "趋势判断"],
        "技术面：近期走势出现的特殊形态": ["特殊形态", "金叉", "死叉", "放量"],
        "综合评估：总结整个股票当前走势看法": ["当前看法", "当前走势", "现在怎么看"],
        "综合评估：总结整个股票过去走势看法": ["过去看法", "过去走势", "复盘分析"],
        "综合评估：总结整个股票未来走势看法": ["未来看法", "未来走势", "后市看点"],
        "交易策略：对当前空仓者建议长线交易策略": ["空仓建议", "无仓建仓", "怎么买入"],
        "交易策略：对当前轻仓者建议长线交易策略": ["轻仓建议", "如何加仓", "轻仓策略"],
        "交易策略：对当前重仓者建议长线交易策略": ["重仓建议", "如何止盈", "重仓策略"],
        "交易策略：建议短线交易策略": ["短线策略", "短线机会", "波段机会"],
    }

    # 如果消息很短或只包含英文/数字（股票代码），直接跳过匹配
    # 注意：Python 的 isalnum() 把中文也算字母，所以要加 isascii() 限制
    cleaned = msg_clean.replace(" ", "")
    if len(msg_clean) < 3 or (cleaned.isascii() and cleaned.isalnum()):
        print(
            f"[DEBUG] match_pre_configured_question: msg='{msg_clean}' 太短或纯英文/数字，跳过匹配"
        )
        return "NA"

    # 第一优先级：完全匹配
    for q in PRE_CONFIGURED_QUESTIONS:
        if q in msg_clean:
            print(
                f"[DEBUG] match_pre_configured_question (Exact): msg='{msg_clean}' -> matched '{q}'"
            )
            return q

    # 第二优先级：关键词匹配
    for question, keywords in keyword_map.items():
        if any(kw in msg_clean for kw in keywords):
            print(
                f"[DEBUG] match_pre_configured_question (Keyword): msg='{msg_clean}' -> matched '{question}'"
            )
            return question
    print(
        f"[DEBUG] match_pre_configured_question: msg='{msg_clean}' -> no match, returning NA"
    )
    return "NA"


def get_stock_list() -> list[str]:
    """获取当前支持的所有股票列表"""
    return SUPPORTED_TICKERS


def get_suggestions(intent: dict, session: "ChatSession") -> list[str]:
    """根据当前意图和会话状态，返回应该显示的建议问题列表"""
    ticker = intent.get("ticker", "NA")

    # 如果明确有股票，展示 15 个维度
    if ticker and ticker != "NA" and ticker != "Market":
        return PRE_CONFIGURED_QUESTIONS

    # 1. 还没选方向
    if not session.selected_category:
        return ["大盘分析", "个股分析"]

    # 2. 选了个股，但还没指定具体代码 -> 显示股票代码列表
    if session.selected_category == "Stock" and (not ticker or ticker == "NA"):
        stocks = get_stock_list()
        if stocks:
            return stocks
        else:
            return ["请输入股票代码 (如 TSLA)"]

    # 3. 选了大盘
    if session.selected_category == "Market" or ticker == "Market":
        return MARKET_QUESTIONS

    # 4. 已指定具体股票 -> 显示 15 个详细问题
    if ticker and ticker != "NA" and ticker != "Market":
        return PRE_CONFIGURED_QUESTIONS

    return PRE_CONFIGURED_QUESTIONS


def recognize_intent(user_message: str, session: "ChatSession") -> dict:
    """根据 Chatbot_v1.md 需求进行意图识别"""
    msg = user_message.strip()

    # 1. 识别股票
    detected_ticker = extract_ticker_from_message(msg)

    # 检测用户是否在选类别
    if any(kw in msg for kw in ["大盘", "市场", "指数"]):
        session.selected_category = "Market"
    elif any(kw in msg for kw in ["个股", "股票", "个股分析"]):
        session.selected_category = "Stock"

    # 只有明确检测到才用检测到的，否则如果有会话上下文则沿用
    ticker = detected_ticker
    if not ticker and session.ticker:
        # 用户在已有上下文中追问，沿用已有股票
        ticker = session.ticker
    elif not ticker:
        ticker = "NA"

    # 2. 匹配预设问题
    topic = match_pre_configured_question(msg)

    # 2.5 追问场景：当前没匹配到话题，但上次有话题，且用户消息是追问类型
    if topic == "NA" and session.last_topic:
        follow_up_keywords = [
            "具体",
            "然后",
            "详细",
            "展开",
            "继续",
            "再说",
            "再问",
            "什么意思",
            "怎么理解",
            "怎么看",
            "进一步",
            "深入",
            "讲讲",
        ]
        is_follow_up = (
            any(kw in msg for kw in follow_up_keywords) or len(msg) <= 4
        )  # 短消息也视为追问
        if is_follow_up:
            topic = session.last_topic
            print(f"[DEBUG] 追问场景: msg='{msg}', 沿用 last_topic='{topic}'")

    # 3. 切换话题时重置该话题的深度（由 chat 接口中的 session.reset_depth() 处理 ticker 切换）
    # 这里不再根据 detected_ticker 重置，避免用户在追问时提到股票名导致深度重置

    # 4. 判断是否需要收集投资目标
    extra_input_goal = "NA"
    profile = session.user_profile
    stock_for_goal = detected_ticker or session.ticker
    if topic in (
        "交易策略：对当前空仓者建议长线交易策略",
        "交易策略：对当前轻仓者建议长线交易策略",
        "交易策略：对当前重仓者建议长线交易策略",
        "交易策略：建议短线交易策略",
        "技术面：当前关键支撑与阻力位",
    ):
        if stock_for_goal and stock_for_goal != "NA":
            existing_goals = (
                profile.get("stocks", {})
                .get(stock_for_goal, {})
                .get("investment_goals", [])
            )
            if not existing_goals and not profile.get("investment_goals"):
                extra_input_goal = "需要"

    # 5. 判断是否需要收集仓位信息
    extra_input_holding = "NA"
    if topic in ("建议长线交易策略", "建议短线交易策略"):
        if stock_for_goal and stock_for_goal != "NA":
            existing_holding = (
                profile.get("stocks", {}).get(stock_for_goal, {}).get("position", "")
            )
            if not existing_holding:
                extra_input_holding = "需要"

    # 6. 判断回复颗粒度（只有确认股票+维度才使用话题深度，否则默认简单回复）
    if detected_ticker != "NA" and detected_ticker != "Market" and topic != "NA":
        depth_level, _ = session.get_topic_depth(topic)
        print(
            f"[DEBUG] 确认股票+维度: ticker={detected_ticker}, topic={topic}, depth={depth_level}"
        )
    else:
        depth_level = 0  # 未确认股票或未匹配维度，默认简单回复
        print(
            f"[DEBUG] 未确认条件: detected_ticker={detected_ticker}, topic={topic}, depth=0 (reset)"
        )
    granularity_map = {
        0: "简单回复",
        1: "展开回复",
        2: "详细解读",
        3: "详细解读",
        4: "详细解读",
    }
    granularity = granularity_map.get(depth_level, "详细解读")

    # 7. 是否需要获取实时股价
    needs_realtime_price = is_price_related_question(msg)

    # 8. 记住本次话题（用于下次追问）
    if topic != "NA":
        session.last_topic = topic

    return {
        "ticker": ticker,
        "topic": topic,
        "granularity": granularity,
        "extra_input_goal": extra_input_goal,
        "extra_input_holding": extra_input_holding,
        "needs_realtime_price": needs_realtime_price,
    }


# ──────────────────────────────────────────────
# Global State
# ──────────────────────────────────────────────
sessions: dict[str, ChatSession] = {}
# 局部缓存，用于存储不同股票的知识库实例
_kb_cache: dict[str, ChatbotKnowledge] = {}

def get_kb(ticker: str) -> Optional[ChatbotKnowledge]:
    """获取或创建指定股票的知识库实例"""
    if not ticker or ticker == "NA":
        return None
    if ticker not in _kb_cache:
        try:
            # 如果是 Market 且没有对应数据目录，直接返回 None 让模型自由回答
            ticker_dir = DATA_DIR / ticker
            if not ticker_dir.exists() and (ticker == "Market" or ticker == "NA"):
                return None

            _kb_cache[ticker] = ChatbotKnowledge(ticker)
            print(f"[DEBUG] Loaded new knowledge base for: {ticker}")
        except Exception as e:
            print(f"[ERROR] Failed to load knowledge base for {ticker}: {e}")
            return None
    return _kb_cache[ticker]
client: Optional[AsyncOpenAI] = None


def get_or_create_session(
    session_id: Optional[str] = None, ticker: str = ""
) -> ChatSession:
    if not session_id or session_id not in sessions:
        session_id = session_id or str(uuid.uuid4())
        sessions[session_id] = ChatSession(session_id, ticker if ticker else "")
    return sessions[session_id]


# ──────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global knowledge_base, client
    _scan_supported_tickers()  # 扫描支持的股票
    knowledge_base = None  # 初始不加载任何股票
    client = AsyncOpenAI(
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
    )
    yield


app = FastAPI(title="Stock Chatbot API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Models ──
class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    session_id: Optional[str] = Field(None, description="会话 ID（首次为空）")
    ticker: str = Field("AMZN", description="股票代码")
    detail_level: Optional[str] = Field(
        None, description="回复颗粒度：simple/normal/detailed"
    )


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    ticker: str
    prepared_questions: list[str]
    user_profile: dict
    intent: dict  # 意图识别结果


class ProfileResponse(BaseModel):
    success: bool
    user_profile: dict


# ── Endpoints ──
@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """聊天 API 端点"""
    if not client:
        raise HTTPException(status_code=503, detail="LLM client not configured")

    session = get_or_create_session(req.session_id)

    # 第一步：意图识别（不加载 JSON）
    intent = recognize_intent(req.message, session)

    # 第二步：判断是否需要加载 JSON 数据
    detected_ticker = intent.get("ticker", "NA")
    detected_topic = intent.get("topic", "NA")

    # 始终保存 ticker 到 session（即使用户只发了股票代码，还没选维度）
    if detected_ticker and detected_ticker != "NA":
        if detected_ticker == "Market":
            pass
        else:
            if session.ticker != detected_ticker:
                session.ticker = detected_ticker
                session.reset_depth()
                print(f"[DEBUG] Session ticker updated to: {detected_ticker}")

    # 强制确保当前使用的知识库与 session.ticker 一致
    current_ticker = session.ticker or (detected_ticker if detected_ticker != "NA" else "AMZN")
    knowledge_base = get_kb(current_ticker)

    # 添加用户消息
    session.add_message("user", req.message)

    # 获取当前应该显示的建议列表
    suggestions = get_suggestions(intent, session)

    # 如果需要实时股价，获取并格式化
    realtime_price_text = ""
    if (
        intent.get("needs_realtime_price")
        and detected_ticker
        and detected_ticker != "Market"
        and detected_ticker != "NA"
    ):
        price_data = get_realtime_price(detected_ticker)
        if price_data and "error" not in price_data:
            realtime_price_text = (
                f"{detected_ticker} 实时行情：\n"
                f"- 现价：${price_data['price']}\n"
                f"- 涨跌：{price_data['change']:+.2f} ({price_data['change_pct']:+.2f}%)\n"
                f"- 昨收：${price_data['prev_close']}\n"
                f"- 货币：{price_data['currency']}"
            )
        else:
            realtime_price_text = f"无法获取 {detected_ticker} 实时行情。"

    # 尝试从 JSON 直接获取答案（depth 0-2）
    direct_answer = None
    depth_level = 0
    if knowledge_base and detected_topic != "NA":
        depth_level, _ = session.get_topic_depth(detected_topic)
        if depth_level <= 2:
            direct_answer = knowledge_base.get_direct_answer(
                detected_topic, depth_level
            )
            print(
                f"[DEBUG] Direct answer lookup: topic='{detected_topic}', depth={depth_level}, found={'YES' if direct_answer else 'NO'}"
            )
        else:
            print(f"[DEBUG] Depth level {depth_level} > 2, falling back to LLM")

    # 构建对话上下文
    system_prompt = session.to_system_prompt(
        knowledge_base,
        req.message,
        intent,
        realtime_price_text,
        suggestions,
        direct_answer,
    )

    # 如果有直接答案且 depth <= 2，直接用直接答案回复（不调用 LLM）
    if direct_answer and depth_level <= 2:
        print(f"[DEBUG] Using direct answer from JSON")
        reply = direct_answer
    else:
        print(f"[DEBUG] Calling LLM for response")
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        for h in session.history[-10:]:
            messages.append(h)

        try:
            response = await client.chat.completions.create(
                model=DASHSCOPE_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=1500,
                extra_body={"enable_thinking": False, "thinking_enabled": False},
            )
            reply = response.choices[0].message.content
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM error: {str(e)}")

    # 添加 AI 回复到历史
    session.add_message("assistant", reply)

    # 定期更新用户画像
    if session.should_update_profile():
        asyncio.create_task(update_user_profile(session))

    # 推进话题深度（追问时 +1）
    # 只有确认了具体股票 + 具体维度，才推进深度
    if (
        detected_ticker != "NA"
        and detected_ticker != "Market"
        and detected_topic != "NA"
    ):
        session.advance_topic_depth(detected_topic)

    return ChatResponse(
        session_id=session.session_id,
        reply=reply,
        ticker=detected_ticker if detected_ticker != "NA" else "",
        prepared_questions=suggestions,
        user_profile=session.user_profile,
        intent=intent,
    )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """流式聊天 API 端点（SSE）"""
    from fastapi.responses import StreamingResponse

    if not client:
        raise HTTPException(status_code=503, detail="LLM client not configured")

    session = get_or_create_session(req.session_id)

    # 第一步：意图识别（不加载 JSON）
    intent = recognize_intent(req.message, session)

    # 第二步：判断是否需要加载 JSON 数据
    detected_ticker = intent.get("ticker", "NA")
    detected_topic = intent.get("topic", "NA")

    # 始终保存 ticker 到 session（即使用户只发了股票代码，还没选维度）
    if detected_ticker and detected_ticker != "NA":
        if detected_ticker == "Market":
            pass
        else:
            if session.ticker != detected_ticker:
                session.ticker = detected_ticker
                session.reset_depth()
                print(f"[DEBUG] (Stream) Session ticker updated to: {detected_ticker}")

    # 强制确保当前使用的知识库与 session.ticker 一致
    current_ticker = session.ticker or (detected_ticker if detected_ticker != "NA" else "AMZN")
    knowledge_base = get_kb(current_ticker)

    session.add_message("user", req.message)

    # 获取当前应该显示的建议列表
    suggestions = get_suggestions(intent, session)

    # 如果需要实时股价，获取并格式化
    realtime_price_text = ""
    if (
        intent.get("needs_realtime_price")
        and detected_ticker
        and detected_ticker != "Market"
        and detected_ticker != "NA"
    ):
        price_data = get_realtime_price(detected_ticker)
        if price_data and "error" not in price_data:
            realtime_price_text = (
                f"{detected_ticker} 实时行情：\n"
                f"- 现价：${price_data['price']}\n"
                f"- 涨跌：{price_data['change']:+.2f} ({price_data['change_pct']:+.2f}%)\n"
                f"- 昨收：${price_data['prev_close']}\n"
                f"- 货币：{price_data['currency']}"
            )
        else:
            realtime_price_text = f"无法获取 {detected_ticker} 实时行情。"

    # 尝试从 JSON 直接获取答案（depth 0-2）
    direct_answer = None
    depth_level = 0
    if knowledge_base and detected_topic != "NA":
        depth_level, _ = session.get_topic_depth(detected_topic)
        if depth_level <= 2:
            direct_answer = knowledge_base.get_direct_answer(
                detected_topic, depth_level
            )
            print(
                f"[DEBUG] (Stream) Direct answer lookup: topic='{detected_topic}', depth={depth_level}, found={'YES' if direct_answer else 'NO'}"
            )
        else:
            print(
                f"[DEBUG] (Stream) Depth level {depth_level} > 2, falling back to LLM"
            )

    system_prompt = session.to_system_prompt(
        knowledge_base,
        req.message,
        intent,
        realtime_price_text,
        suggestions,
        direct_answer,
    )

    # 如果有直接答案且 depth <= 2，直接返回（不走流式）
    if direct_answer and depth_level <= 2:
        print(f"[DEBUG] (Stream) Using direct answer from JSON")

        async def direct_event_generator():
            full_reply = direct_answer
            # 逐字符模拟流式（保持前端兼容）
            for char in full_reply:
                yield f"data: {json.dumps({'type': 'token', 'content': char}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.01)

            session.add_message("assistant", full_reply)

            # 推进话题深度（只有确认股票+维度才推进）
            if (
                detected_ticker != "NA"
                and detected_ticker != "Market"
                and detected_topic != "NA"
            ):
                session.advance_topic_depth(detected_topic)

            yield f"data: {json.dumps({'type': 'done', 'session_id': session.session_id, 'ticker': detected_ticker if detected_ticker != 'NA' else '', 'prepared_questions': suggestions, 'intent': intent}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            direct_event_generator(), media_type="text/event-stream"
        )

    messages = [{"role": "system", "content": system_prompt}]
    for h in session.history[-10:]:
        messages.append(h)

    async def event_generator():
        full_reply = ""
        try:
            stream = await client.chat.completions.create(
                model=DASHSCOPE_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=1500,
                stream=True,
                extra_body={"enable_thinking": False, "thinking_enabled": False},
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_reply += content
                    yield f"data: {json.dumps({'type': 'token', 'content': content}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            return

        session.add_message("assistant", full_reply)

        # 推进话题深度（只有确认股票+维度才推进）
        if (
            detected_ticker != "NA"
            and detected_ticker != "Market"
            and detected_topic != "NA"
        ):
            session.advance_topic_depth(detected_topic)

        # 发送 session_id 和元数据（包含意图识别结果）
        yield f"data: {json.dumps({'type': 'done', 'session_id': session.session_id, 'ticker': detected_ticker if detected_ticker != 'NA' else '', 'prepared_questions': suggestions, 'intent': intent}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/profile", response_model=ProfileResponse)
async def update_profile_endpoint(req: ChatRequest):
    """手动触发用户画像更新"""
    if req.session_id and req.session_id in sessions:
        session = sessions[req.session_id]
        await update_user_profile(session)
        return ProfileResponse(success=True, user_profile=session.user_profile)
    raise HTTPException(status_code=404, detail="Session not found")


@app.get("/api/sessions/{session_id}/profile")
async def get_profile(session_id: str):
    """获取用户画像"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id].user_profile


@app.get("/api/sessions/{session_id}/history")
async def get_history(session_id: str):
    """获取聊天历史"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id].history


@app.post("/api/sessions/{session_id}/clear")
async def clear_history(session_id: str):
    """清空聊天历史（保留 session 和用户画像）"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sessions[session_id]
    session.history = []
    session.message_count = 0
    session.topic_depth = {}  # 重置所有话题深度
    session.last_topic = ""  # 重置上次话题
    session.selected_category = None  # 重置分类选择
    session.ticker = ""  # 重置股票
    return {"success": True, "message": "Chat history cleared"}


async def update_user_profile(session: ChatSession):
    """后台更新用户画像"""
    if not client:
        return
    try:
        response = await client.chat.completions.create(
            model=DASHSCOPE_MODEL,
            messages=[{"role": "user", "content": session.get_profile_update_prompt()}],
            temperature=0.3,
            max_tokens=500,
            response_format={"type": "json_object"},
            extra_body={"enable_thinking": False, "thinking_enabled": False},
        )
        content = response.choices[0].message.content
        profile_data = json.loads(content)
        # 合并更新
        for key in [
            "investment_goals",
            "investment_style",
            "investment_level",
            "capital_range",
        ]:
            if key in profile_data:
                session.user_profile[key] = profile_data[key]
        if "stocks" in profile_data:
            session.user_profile["stocks"].update(profile_data["stocks"])
    except Exception:
        pass  # 静默失败，不影响主流程


# ── Static Web UI ──
@app.get("/")
async def index():
    """提供 Web UI"""
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>Chatbot Web UI not found</h1>")


@app.get("/chatbot_web/{file_path:path}")
async def static_files(file_path: str):
    """提供静态文件"""
    full_path = WEB_DIR / file_path
    if full_path.exists() and full_path.is_file():
        return FileResponse(full_path)
    raise HTTPException(status_code=404)


# ── Main ──
if __name__ == "__main__":
    import uvicorn

    print(f"Starting Chatbot API server...")
    print(f"  Model: {DASHSCOPE_MODEL}")
    print(f"  Base URL: {DASHSCOPE_BASE_URL}")
    print(
        f"  API Key: {DASHSCOPE_API_KEY[:8]}..."
        if DASHSCOPE_API_KEY
        else "  API Key: NOT SET"
    )
    print(f"  Web UI: http://localhost:8899")
    print(f"  API Docs: http://localhost:8899/docs")
    uvicorn.run(app, host="0.0.0.0", port=8899)
