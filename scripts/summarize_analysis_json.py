#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于已完成的技能分析 JSON，按需求.md 进行分步大模型总结，并保存每步输入/输出。

使用方法:
  python scripts/summarize_analysis_json.py --input data/analysis_results/analysis_AMZN_xxx.json
  python scripts/summarize_analysis_json.py --input data/analysis_results/analysis_AMZN_xxx.json --output data/analysis_results/analysis_AMZN_xxx.structured.json
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import html
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import markdown2
from dotenv import load_dotenv
from openai import AsyncOpenAI

project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

ROLE = (
    "你是实战派资深股票专家，现在跟股民进行一对一答疑。"
    "必须严格基于给定报告内容，不得臆造任何价格、日期或事件；"
    "币种必须与报告一致（如 AMZN 使用美元），禁止输出人民币“元”口径。"
)

REQUIREMENTS = """- 用口语化、接地气的大白话总结，像微信语音转文字一样自然，不要有翻译腔
- 不要称呼"各位股民朋友"、"兄弟们"等，直接说事
- 结论必须完整，不能话说到一半断掉。宁可少说点，也要把话说全
- “三句话总结”只是一个分类名称，要求把核心三个重点揉进“一个连贯的口语长段落”里，读起来是一口气说完的，严禁分点（1. 2. 3.）
- 字数严格控制：一句话 ≤30字，三句话 ≤80字，详细 ≤200字
- 数字、价格、区间、日期必须保持输入原格式，优先使用阿拉伯数字与原符号（如 246-250美元）；禁止改写成中文数字（如“两百四十六至二百五十美元”）
- 美股价格尽量统一使用“$数字”格式，避免同段落出现无币种裸价格"""

FORMAT_LINES = """**输出格式**：
- 一句话总结：连贯一句，≤30字
- 三句话总结：连贯一段话，≤80字
- 详细总结：连贯分析，≤200字"""

BASE_JSON_FORMAT = """JSON 输出格式：
{
  "one": "核心结论一句话，绝对禁止以逗号结尾，必须是完整且嘴替感强的句子，≤30字",
  "three": "揉成一个连贯的完整段落（不要分点），像语音转文字一样顺滑，绝对禁止以逗号结尾，≤80字",
  "detailed": "深度分析，逻辑链通顺，必须结尾完整，≤200字"
}
"""

JSON_FORMAT = """JSON 输出格式：
{
  "market": "今日行情快照（必须包含日期 YYYY-MM-DD + O/H/C/L 与关键波动）",
  "one": "一句话核心结论（≤30字，禁止逗号结尾）",
  "three": "三句话逻辑总结（合并成一个嘴替感强的段落，≤80字，禁止逗号结尾）",
  "detailed": "详细深度版分析（逻辑链完整，≤200字）",
  "strategy_levels": "潜在交易策略与各位置执行细节（涉及多项机会时请用 - 或 * 分条列出，每个机会必须含入场位/止损位/目标位，或重/轻/空仓的具体分仓指引）",
  "reference": "参考来源 link（若无则写“信息不足，无法判断”）"
}
"""

STEP_KEYS = ("market", "one", "three", "detailed", "strategy_levels", "reference")


def _safe_text(value: Optional[str], fallback: str = "信息不足，无法判断") -> str:
    text = (value or "").strip()
    return text if text else fallback


def _render_inputs(inputs: Dict[str, str]) -> str:
    parts: List[str] = []
    for name, content in inputs.items():
        parts.append(f"### {name}\n{_safe_text(content)}")
    return "\n\n".join(parts)


def _get_skill_texts(analysis_json: Dict[str, Any]) -> Dict[str, str]:
    texts: Dict[str, str] = {}
    for item in analysis_json.get("results", []):
        if item.get("success") and item.get("result"):
            texts[str(item["skill_id"])] = str(item["result"])
    return texts


def _extract_json_object(text: str) -> Dict[str, Any]:
    stripped = (text or "").strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", stripped)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _normalize_step_output(raw_text: str) -> Dict[str, str]:
    parsed = _extract_json_object(raw_text)
    if parsed:
        return {k: _safe_text(str(parsed.get(k, ""))) for k in STEP_KEYS}

    fallback = {k: "信息不足，无法判断" for k in STEP_KEYS}
    fallback["detailed"] = _safe_text(raw_text)
    return fallback


def _ends_with_comma(text: str) -> bool:
    stripped = text.rstrip()
    return stripped.endswith(",") or stripped.endswith("，")


def _is_us_ticker(stock_code: str) -> bool:
    code = (stock_code or "").strip().upper()
    if not code:
        return False
    if re.fullmatch(r"[A-Z]{1,6}(?:\.[A-Z]{1,3})?", code):
        return True
    return False


def _normalize_currency_text(text: str, *, us_ticker: bool) -> str:
    value = _safe_text(text)
    if not us_ticker:
        return value

    # 价格+美元 => $价格美元
    # 修复：(?<![\$\.\d]) 增加对点号的回溯屏蔽，防止 $376.30 变成 $376.$30
    value = re.sub(r"(?<![\$\.\d])(\d+(?:\.\d+)?)\s*美元", r"$\1美元", value)

    # O/H/C/L关键词后的裸数字补 $
    value = re.sub(
        r"(开盘价?|最高价?|最低价?|收盘价?|开|高|低|收|阻力位\d*|支撑位\d*|止损|止盈|目标位|目标价)\s*[:：]?\s*(?!\$)(\d+(?:\.\d+)?)",
        r"\1$\2",
        value,
    )

    # 区间“234-242美元” => "$234-$242美元"
    value = re.sub(
        r"(?<!\$)(\d+(?:\.\d+)?)\s*[-~至]\s*(?<!\$)(\d+(?:\.\d+)?)\s*美元",
        r"$\1-$\2美元",
        value,
    )
    # 区间“$260-265” => "$260-$265"
    value = re.sub(
        r"\$(\d+(?:\.\d+)?)\s*[-~至]\s*(?!\$)(\d+(?:\.\d+)?)", r"$\1-$\2", value
    )

    return value


def _validate_step_output(payload: Dict[str, str], *, market_text: str) -> List[str]:
    issues: List[str] = []
    one = _safe_text(payload.get("one"))
    three = _safe_text(payload.get("three"))
    detailed = _safe_text(payload.get("detailed"))

    # market 由统一快照填充，若快照本身不足，不应在这里拦截导致后续步骤无效重试
    # 因为 market_snapshot 在 run_step 外部生成，重试 LLM 也不会改变它
    if not market_text or market_text == "信息不足，无法判断":
        # 记录但不计入阻塞 issue
        pass

    if len(one) > 30:
        issues.append(f"one 超长：{len(one)} > 30")
    if len(three) > 80:
        issues.append(f"three 超长：{len(three)} > 80")
    if len(detailed) > 200:
        issues.append(f"detailed 超长：{len(detailed)} > 200")

    if _ends_with_comma(one):
        issues.append("one 不能以逗号结尾")
    if _ends_with_comma(three):
        issues.append("three 不能以逗号结尾")
    if _ends_with_comma(detailed):
        issues.append("detailed 不能以逗号结尾")

    return issues


def _validate_step_uniqueness(
    step_id: str, payload: Dict[str, str], existing: Dict[str, Dict[str, str]]
) -> List[str]:
    # 定义每个步骤需要和哪些前置步骤进行“深度差异化”校验
    compare_map = {
        "pattern_single_summary": ["macro_single_summary"],
        "structure_side_analysis": ["macro_single_summary", "pattern_single_summary"],
        "trend_side_analysis": ["macro_single_summary"],
        "macro_trend_summary": [
            "structure_side_analysis",
            "trend_side_analysis",
            "macro_single_summary",
        ],
        "current_view_summary": ["macro_trend_summary", "macro_single_summary"],
        "past_view_summary": ["current_view_summary", "macro_trend_summary"],
        "future_view_summary": [
            "current_view_summary",
            "past_view_summary",
            "macro_trend_summary",
        ],
        "long_term_investment_idea": [
            "macro_trend_summary",
            "future_view_summary",
        ],
        "short_term_opportunities": [
            "current_view_summary",
            "macro_trend_summary",
            "pattern_single_summary",
        ],
        "long_term_light_summary": [
            "short_term_opportunities",
            "current_view_summary",
            "macro_trend_summary",
            "future_view_summary",
        ],
        "long_term_heavy_summary": [
            "long_term_light_summary",
            "short_term_opportunities",
            "current_view_summary",
            "macro_trend_summary",
        ],
        "long_term_empty_summary": [
            "long_term_heavy_summary",
            "long_term_light_summary",
            "short_term_opportunities",
            "current_view_summary",
        ],
        "final_five_point_report": [
            "current_view_summary",
            "past_view_summary",
            "future_view_summary",
            "short_term_opportunities",
            "long_term_light_summary",
            "long_term_heavy_summary",
            "long_term_empty_summary",
        ],
    }
    refs = compare_map.get(step_id, [])
    issues: List[str] = []
    if not refs:
        return issues

    cur_three = _safe_text(payload.get("three"), fallback="")
    cur_detail = _safe_text(payload.get("detailed"), fallback="")
    cur_strategy = _safe_text(payload.get("strategy_levels"), fallback="")

    THRESHOLD_THREE = 0.72
    THRESHOLD_DETAIL = 0.70
    THRESHOLD_STRATEGY = 0.65

    for ref in refs:
        ref_payload = existing.get(ref) or {}
        if not ref_payload:
            continue
        ref_three = _safe_text(ref_payload.get("three"), fallback="")
        ref_detail = _safe_text(ref_payload.get("detailed"), fallback="")
        ref_strategy = _safe_text(ref_payload.get("strategy_levels"), fallback="")

        if cur_three and ref_three:
            ratio = difflib.SequenceMatcher(None, cur_three, ref_three).ratio()
            if ratio >= THRESHOLD_THREE:
                issues.append(f"three 与步骤 {ref} 过度相似 ({ratio:.2f})，请换表达。")

        if cur_detail and ref_detail:
            ratio = difflib.SequenceMatcher(None, cur_detail, ref_detail).ratio()
            if ratio >= THRESHOLD_DETAIL:
                issues.append(
                    f"detailed 与步骤 {ref} 过度相似 ({ratio:.2f})，请挖掘独有细节。"
                )

        if cur_strategy and ref_strategy and cur_strategy != "信息不足，无法判断":
            ratio = difflib.SequenceMatcher(None, cur_strategy, ref_strategy).ratio()
            if ratio >= THRESHOLD_STRATEGY:
                issues.append(
                    f"strategy_levels 与步骤 {ref} 过度相似 ({ratio:.2f})，"
                    f"本步骤({step_id})必须给出完全不同的操作建议和点位。"
                )
    return issues


def _step_json_to_text(step_payload: Dict[str, str]) -> str:
    return (
        f"0. 今日行情\n{_safe_text(step_payload.get('market'))}\n\n"
        f"1. 一句话总结\n{_safe_text(step_payload.get('one'))}\n\n"
        f"2. 三句话总结\n{_safe_text(step_payload.get('three'))}\n\n"
        f"3. 详细版\n{_safe_text(step_payload.get('detailed'))}\n\n"
        f"4. 潜在交易策略与关键点位\n{_safe_text(step_payload.get('strategy_levels'))}\n\n"
        f"5. Reference\n{_safe_text(step_payload.get('reference'))}"
    )


def _extract_latest_date_from_text(text: str) -> Optional[str]:
    full_matches = re.findall(r"\b(20\d{2})[-/](\d{2})[-/](\d{2})\b", text or "")
    normalized = []
    for y, m, d in full_matches:
        # 校验月份和日期的合法性
        if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            normalized.append(f"{y}-{m}-{d}")

    md_matches = re.findall(r"\b(\d{2})[-/](\d{2})\b", text or "")
    current_year = datetime.now().year
    for m, d in md_matches:
        # 校验月份和日期的合法性，避免捕获类似 50-80% 的数据
        if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            normalized.append(f"{current_year}-{m}-{d}")
            
    if not normalized:
        return None
    # 返回字典序最大的日期作为最新日期
    return sorted(normalized)[-1]


def _fetch_ohlc_via_yfinance(stock_code: str) -> Optional[str]:
    """
    通过 yfinance 直接获取最近交易日的 OHLC 数据。
    美股直接用 ticker，A股/港股按项目内既有规则转换。
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.debug("yfinance 未安装，跳过在线 OHLC 获取")
        return None

    try:
        ticker_symbol = stock_code
        # A股代码转换：600519 -> 600519.SS, 000001 -> 000001.SZ
        if re.match(r"^\d{6}$", stock_code):
            suffix = ".SS" if stock_code.startswith(("6", "9")) else ".SZ"
            ticker_symbol = f"{stock_code}{suffix}"
        # 港股代码转换：hk00700 -> 0700.HK
        elif stock_code.lower().startswith("hk"):
            num = stock_code[2:].lstrip("0") or "0"
            ticker_symbol = f"{num}.HK"

        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="5d")
        if hist.empty:
            logger.warning("yfinance 返回空数据: %s", ticker_symbol)
            return None

        # 取最后一行（最新交易日）
        last = hist.iloc[-1]
        trade_date = str(hist.index[-1].date())
        o = f"{last['Open']:.2f}"
        h = f"{last['High']:.2f}"
        l = f"{last['Low']:.2f}"
        c = f"{last['Close']:.2f}"

        us = _is_us_ticker(stock_code)
        prefix = "$" if us else ""
        logger.info("从 yfinance 获取 OHLC: %s 日期 %s (O=%s H=%s L=%s C=%s)",
                     ticker_symbol, trade_date, o, h, l, c)
        return (
            f"{trade_date} 行情：开盘{prefix}{o}，"
            f"最高{prefix}{h}，"
            f"最低{prefix}{l}，"
            f"收盘{prefix}{c}。"
        )
    except Exception as exc:
        logger.warning("yfinance 获取 OHLC 失败 (%s): %s", stock_code, exc)
        return None




def _fallback_market_snapshot(stock_code: str, skill_texts: Dict[str, str]) -> str:
    # 尝试从已有技能文本里拼一个兜底行情摘要
    sample = "\n".join(skill_texts.values())
    date_value = _extract_latest_date_from_text(sample)

    # Helper to clean up price text (remove commas, $, etc.)
    def pick_price(patterns: List[str]) -> Optional[str]:
        for pat in patterns:
            # Modified regex to skip potential Markdown formatting like ** and handle currency symbols
            m = re.search(pat, sample, flags=re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    # Flexible regex to skip markdown bolding/styling characters
    price_val_pat = r"(?:[\s\*：:]|\$)*(\d+(?:\.\d+)?)"

    open_price = pick_price([
        r"开盘价?" + price_val_pat,
        r"开盘价?\s*\|\s*\$?(\d+(?:\.\d+)?)",
        r"\b开\s*" + price_val_pat,
    ])
    high_price = pick_price([
        r"最高价?" + price_val_pat,
        r"最高价?\s*\|\s*\$?(\d+(?:\.\d+)?)",
        r"\b高\s*" + price_val_pat,
    ])
    low_price = pick_price([
        r"最低价?" + price_val_pat,
        r"最低价?\s*\|\s*\$?(\d+(?:\.\d+)?)",
        r"\b低\s*" + price_val_pat,
    ])
    close_price = pick_price([
        r"收盘价?" + price_val_pat,
        r"收盘价?\s*\|\s*\$?(\d+(?:\.\d+)?)",
        r"\b收\s*" + price_val_pat,
        r"当前价格" + price_val_pat,
        r"最新价格" + price_val_pat,
        r"现价" + price_val_pat,
    ])

    if not close_price and all([open_price, high_price, low_price]):
        # 某些技能只给了当前价格，没写“收盘”；此时保守降级为 high/low/open 已有，close 用当前价格再二次尝试
        close_price = pick_price(
            [
                r"当前价格\s*[:：]?\s*\$?(\d+(?:\.\d+)?)",
                r"最新价格\s*[:：]?\s*\$?(\d+(?:\.\d+)?)",
                r"现价\s*[:：]?\s*\$?(\d+(?:\.\d+)?)",
            ]
        )

    if not date_value:
        return "信息不足，无法判断"

    us = _is_us_ticker(stock_code)
    prefix = "$" if us else ""
    unit = "美元" if us else ""

    if not all([open_price, high_price, low_price, close_price]):
        # 如果 OHLC 不全，但至少有一个价格，也返回降级版，不直接报错
        any_price = close_price or open_price or high_price or low_price
        if not any_price:
            return "信息不足，无法判断"
        return f"{date_value} 行情：当前/参考价格 {prefix}{any_price}{unit} (部分 OHLC 数据缺失)。"

    return (
        f"{date_value} 行情：开盘{prefix}{open_price}{unit}，"
        f"最高{prefix}{high_price}{unit}，"
        f"最低{prefix}{low_price}{unit}，"
        f"收盘{prefix}{close_price}{unit}。"
    )


def _step_json_to_text_styled(step_payload: Dict[str, str]) -> str:
    # 优化 HTML/Markdown 里的呈现，增加视觉引导
    return (
        f"**0. 今日行情** {_safe_text(step_payload.get('market'))}\n\n"
        f"**1. 一句话总结** {_safe_text(step_payload.get('one'))}\n\n"
        f"**2. 三句话总结** {_safe_text(step_payload.get('three'))}\n\n"
        f"**3. 详细版** {_safe_text(step_payload.get('detailed'))}\n\n"
        f"**4. 潜在交易策略与关键点位** {_safe_text(step_payload.get('strategy_levels'))}\n\n"
        f"**5. Reference** {_safe_text(step_payload.get('reference'))}"
    )


def build_markdown_report(enriched: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"# {enriched.get('stock_code', '')} 股票分析结构化总结")
    lines.append("")
    lines.append(f"**分析时间**: {enriched.get('analysis_time', '')}")
    lines.append("")

    final_json = enriched.get("structured_summary_json") or {}
    if isinstance(final_json, dict) and final_json:
        normalized = {k: _safe_text(str(final_json.get(k, ""))) for k in STEP_KEYS}
        final_text = _step_json_to_text_styled(normalized)
    else:
        final_text = _safe_text(enriched.get("structured_summary"))

    lines.append("## 最终输出摘要")
    lines.append("")
    lines.append(final_text)
    lines.append("")

    steps = enriched.get("llm_pipeline", {}).get("steps", [])
    if steps:
        lines.append("## 分步总结明细")
        lines.append("")
        for idx, step in enumerate(steps, start=1):
            title = step.get("title") or step.get("step_id") or f"Step {idx}"
            lines.append(f"### {idx}. {title}")
            lines.append("")

            output_json = step.get("output_json")
            if isinstance(output_json, dict):
                normalized = {
                    k: _safe_text(str(output_json.get(k, ""))) for k in STEP_KEYS
                }
                lines.append(_step_json_to_text_styled(normalized))
            else:
                lines.append(_safe_text(step.get("output")))
            lines.append("")

            if step.get("validation_issues"):
                lines.append(
                    "> **AI 校验提示**: " + "; ".join(step["validation_issues"])
                )
                lines.append("")
            if step.get("error"):
                lines.append(f"> **执行错误**: {step['error']}")
                lines.append("")

    return "\n".join(lines).strip() + "\n"


def _build_toc_from_content(content_html: str) -> str:
    headings = re.findall(
        r"<h([1-3])[^>]*id=\"([^\"]+)\"[^>]*>(.*?)</h\1>", content_html
    )
    if not headings:
        return "<p style='margin:0;color:#64748b;'>当前文档没有可导航标题</p>"

    items: List[str] = ["<ul>"]
    for level, hid, inner in headings:
        text = re.sub(r"<.*?>", "", inner)
        cls = (
            "toc-root" if level == "1" else ("toc-main" if level == "2" else "toc-sub")
        )
        items.append(f"<li class='{cls}'><a href='#{hid}'>{html.escape(text)}</a></li>")
    items.append("</ul>")
    return "".join(items)


def build_html_report(markdown_text: str, title: str = "股票分析结构化总结") -> str:
    html_body = markdown2.markdown(
        markdown_text,
        extras=["fenced-code-blocks", "tables", "break-on-newline", "header-ids"],
    )
    toc_html = _build_toc_from_content(html_body)
    safe_title = html.escape(title)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{safe_title}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@500;600;700;800&display=swap');

    :root {{
      --bg: #f8fafc;
      --surface: #ffffff;
      --text: #1e293b;
      --muted: #64748b;
      --primary: #4f46e5;
      --primary-soft: #eef2ff;
      --line: #e2e8f0;
      --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
    }}

    * {{ box-sizing: border-box; scroll-behavior: smooth; }}

    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', -apple-system, system-ui, sans-serif;
      line-height: 1.4;
      -webkit-font-smoothing: antialiased;
    }}

    .wrap {{
      max-width: 1100px;
      margin: 15px auto;
      padding: 0 15px 30px;
      display: grid;
      grid-template-columns: 240px 1fr;
      gap: 15px;
    }}

    /* Sidebar / TOC */
    .side {{
      position: sticky;
      top: 15px;
      align-self: start;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 10px;
      box-shadow: var(--shadow-sm);
      padding: 12px;
      max-height: calc(100vh - 30px);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}

    .side h2 {{
      margin: 0 0 8px;
      font-family: 'Outfit', sans-serif;
      font-size: 15px;
      font-weight: 700;
      color: var(--primary);
    }}

    .side .tip {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 10.5px;
      background: var(--primary-soft);
      padding: 3px 8px;
      border-radius: 5px;
    }}

    .side ul {{
      margin: 0;
      padding: 0;
      list-style: none;
      overflow-y: auto;
      overflow-x: hidden;
      flex: 1;
    }}

    .side li {{ margin: 1px 0; }}
    .side .toc-root {{ font-weight: 700; margin-top: 8px; border-top: 1px solid var(--line); padding-top: 6px; }}
    .side .toc-main {{ font-weight: 600; padding-left: 0; }}
    .side .toc-sub {{ padding-left: 12px; color: var(--muted); font-size: 11.5px; }}

    .side a {{
      display: block;
      color: #475569;
      text-decoration: none;
      font-size: 12.5px;
      padding: 5px 8px;
      border-radius: 6px;
      transition: all 0.15s ease;
      line-height: 1.3;
      word-break: break-all;
    }}

    .side a:hover {{
      color: var(--primary);
      background: var(--primary-soft);
    }}

    .side a.is-active {{
      color: #ffffff;
      background: var(--primary);
      font-weight: 600;
    }}

    /* Main Content */
    .main {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 10px;
      box-shadow: var(--shadow-sm);
      padding: 24px 32px;
    }}

    .main h1 {{
      margin: 0 0 10px;
      font-family: 'Outfit', sans-serif;
      font-size: 24px;
      font-weight: 800;
      color: var(--primary);
    }}

    .main h2 {{
      margin: 14px 0 6px;
      font-family: 'Outfit', sans-serif;
      font-size: 18px;
      font-weight: 700;
      color: var(--text);
      border-bottom: 2px solid var(--primary-soft);
      padding-bottom: 4px;
    }}

    .main h3 {{
      margin: 18px 0 6px;
      font-family: 'Outfit', sans-serif;
      font-size: 16px;
      font-weight: 700;
      color: #1e1b4b;
      background: #f8fafc;
      padding: 4px 10px;
      border-radius: 6px;
      border-left: 4px solid var(--primary);
    }}

    .main p {{
      margin: 0.3em 0;
      color: #334155;
      font-size: 14.5px;
      line-height: 1.6;
    }}

    /* 6-point structure highlight */
    .main p strong {{
      color: var(--primary);
      font-weight: 700;
      font-family: 'Outfit', sans-serif;
      display: block;
      margin-top: 14px;
      margin-bottom: 2px;
      font-size: 14.5px;
    }}

    .main table {{
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0;
      font-size: 13.5px;
      border: 1px solid var(--line);
    }}

    .main th, .main td {{
      padding: 8px 12px;
      border: 1px solid var(--line);
      text-align: left;
    }}

    .main th {{
      background: #f8fafc;
      font-weight: 700;
      color: var(--muted);
      font-size: 11.5px;
    }}

    .main code {{
      background: #f1f5f9;
      color: #e11d48;
      padding: 1px 4px;
      border-radius: 3px;
      font-size: 0.85em;
    }}

    .main pre {{
      background: #0f172a;
      color: #f8fafc;
      padding: 12px;
      border-radius: 8px;
      overflow: auto;
      font-size: 12.5px;
      margin: 12px 0;
    }}

    .main blockquote {{
      margin: 12px 0;
      padding: 10px 16px;
      border-left: 4px solid var(--primary);
      background: var(--primary-soft);
      border-radius: 0 6px 6px 0;
      color: #3730a3;
      font-size: 13.5px;
    }}

    .main [id] {{ scroll-margin-top: 60px; }}

    @media (max-width: 900px) {{
      .wrap {{ grid-template-columns: 1fr; margin: 8px auto; padding: 0 10px; }}
      .side {{ position: static; max-height: none; margin-bottom: 12px; }}
      .main {{ padding: 20px 16px; }}
      .main h1 {{ font-size: 22px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <aside class="side">
      <h2>报告导航</h2>
      <p class="tip">Stock Analysis Report v3.0</p>
      {toc_html}
    </aside>
    <main class="main">{html_body}</main>
  </div>
  <script>
    (function () {{
      const links = Array.from(document.querySelectorAll('.side a[href^="#"]'));
      if (!links.length) return;

      const targets = links
        .map((a) => document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1))))
        .filter(Boolean);
      if (!targets.length) return;

      function setActive(id) {{
        links.forEach((a) => {{
          const hit = a.getAttribute('href') === '#' + id;
          a.classList.toggle('is-active', hit);
        }});
      }}

      links.forEach((a) => {{
        a.addEventListener('click', (e) => {{
          const href = a.getAttribute('href') || '';
          const id = decodeURIComponent(href.slice(1));
          const el = document.getElementById(id);
          if (!el) return;
          e.preventDefault();
          const y = el.getBoundingClientRect().top + window.scrollY - 60;
          window.scrollTo({{ top: y, behavior: 'smooth' }});
          history.replaceState(null, '', '#' + id);
          setActive(id);
        }});
      }});

      const observer = new IntersectionObserver(
        (entries) => {{
          const visible = entries
            .filter((entry) => entry.isIntersecting)
            .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
          if (visible.length) {{
            setActive(visible[0].target.id);
          }}
        }},
        {{ root: null, rootMargin: '-10% 0px -85% 0px', threshold: [0, 1] }}
      );
      targets.forEach((el) => observer.observe(el));

      const initialId = decodeURIComponent(location.hash.replace('#', ''));
      if (initialId && document.getElementById(initialId)) {{
        setActive(initialId);
      }} else if (targets[0]) {{
        setActive(targets[0].id);
      }}
    }})();
  </script>
</body>
</html>
"""


async def summarize_analysis_json(
    analysis_json: Dict[str, Any],
    *,
    model: str,
    base_url: str,
    api_key: str,
    market_cache: Optional[str] = None,
) -> Dict[str, Any]:

    stock_code = str(analysis_json.get("stock_code", "UNKNOWN"))
    us_ticker = _is_us_ticker(stock_code)
    skill_texts = _get_skill_texts(analysis_json)

    step_records: List[Dict[str, Any]] = []
    step_outputs: Dict[str, Dict[str, str]] = {}
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    def skill(skill_id: str) -> str:
        return skill_texts.get(skill_id, "")

    def step_text(step_id: str) -> str:
        payload = step_outputs.get(step_id, {})
        if not payload:
            return "信息不足，无法判断"
        return _step_json_to_text(payload)

    async def ask_llm_json(user_prompt: str, *, temperature: float = 0.3) -> str:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": f"{ROLE}\n你是严谨的股票研究助理，只能返回合法 JSON。",
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )
        return _safe_text(response.choices[0].message.content)

    # 只生成一次今日行情快照，后续步骤全部复用
    market_prompt = (
        f"股票代码：{stock_code}\n"
        "请仅根据以下输入，抽取并整理‘今日行情’一句话，必须含：行情日期(YYYY-MM-DD)、开盘/最高/最低/收盘、关键波动。\n"
        "若缺任一关键字段，输出‘信息不足，无法判断’。\n"
        "美股请统一使用$，不要裸价格。\n"
        f"输入：\n{_render_inputs(skill_texts)}\n\n"
        'JSON 输出：{"market":"..."}'
    )
    try:
        market_raw = await ask_llm_json(market_prompt, temperature=0.2)
        market_parsed = _extract_json_object(market_raw)
        market_snapshot = _safe_text(str(market_parsed.get("market", "")))
    except Exception as exc:
        logger.warning("生成 market 快照失败，将使用本地兜底：%s", exc)
        market_snapshot = ""

    if not market_snapshot or market_snapshot == "信息不足，无法判断":
        # 优先通过 yfinance 直接获取精确 OHLC
        yf_ohlc = _fetch_ohlc_via_yfinance(stock_code)
        if yf_ohlc:
            market_snapshot = yf_ohlc
        else:
            # 最后兜底：从技能文本正则提取
            market_snapshot = _fallback_market_snapshot(stock_code, skill_texts)

    market_snapshot = _normalize_currency_text(market_snapshot, us_ticker=us_ticker)

    async def run_step(
        step_id: str,
        title: str,
        inputs: Dict[str, str],
        logic: str,
        output_requirements: str,
        scope_constraints: str = "",
        strategy_hint: str = "",
        temperature: float = 0.4,
        max_retries: int = 2,
    ) -> Dict[str, str]:
        base_user_prompt = (
            f"你正在执行股票分析结构化抽取流程中的一步。\n\n"
            f"股票代码：{stock_code}\n"
            f"步骤标识：{step_id}\n"
            f"步骤名称：{title}\n\n"
            f"任务目标：\n{title}\n\n"
            f"输入信息：\n{_render_inputs(inputs)}\n\n"
            f"固定今日行情（必须原样保留）：\n{market_snapshot}\n\n"
            f"内在逻辑：\n{logic}\n\n"
            f"输出要求：\n{output_requirements}\n\n"
            f"范围边界（必须严格遵守）：\n{scope_constraints or '仅按本步骤标题回答，不扩展到其他步骤。'}\n\n"
            f"角色设定：\n{ROLE}\n\n"
            f"表达要求：\n{REQUIREMENTS}\n\n"
            f"{FORMAT_LINES}\n\n"
            f"{BASE_JSON_FORMAT}\n\n"
            "【边界约束 - 极其重要】\n"
            "1) market 字段直接使用上面的“固定今日行情”。\n"
            "2) 禁止输出 markdown 代码块，禁止额外解释，只输出 JSON。\n"
            "3) 任何字段信息不足统一写：信息不足，无法判断。\n"
            "4) 严格区分时间/空间边界：\n"
            "   - 若是‘过去’，只准复盘历史；\n"
            "   - 若是‘当前’，只准谈快照现状；\n"
            "   - 若是‘未来’，只准谈预测和催化剂；\n"
            "   - 若是‘短线/长线’，必须区分持仓节奏，严禁混谈。\n"
            "5) 禁止复用任何前序步骤的原句，哪怕意思相近，也必须重构表述，禁止复读机行为。\n"
            "6) 违反边界约束（如在‘未来’步骤写‘最近涨了不少’）将导致系统重试并扣分。\n"
            f"7) 输出必须是合法 JSON，结构为：\n{JSON_FORMAT}\n"
            f"8) 【strategy_levels 字段专项约束】{strategy_hint or '请根据本步骤标题和场景，给出与其他步骤完全不同的策略建议。不同步骤的策略必须在操作方向、仓位逻辑、点位选择上体现本质差异。'}"
        )

        raw_output = ""
        output_json: Dict[str, str] = {k: "信息不足，无法判断" for k in STEP_KEYS}
        error_message: Optional[str] = None
        validation_issues: List[str] = []
        used_attempts = 0
        repair_hint = ""

        for attempt in range(max_retries + 1):
            used_attempts = attempt + 1

            # 动态生成“禁止复用”列表，放在提示词最显眼位置
            avoidance_context = []
            # 自动获取 compare_map 里的参考步骤内容注入 prompt
            # 这里先手动在 run_step 里定义逻辑，或者在 run_step 外部根据 step_outputs 拼装
            # 我们直接在 build_prompt 时，把 existing 里的相关步骤也贴出来

            ref_steps_content = ""
            # 从外部作用域或逻辑中找出需要避开的已生成内容
            # 这里简化处理：把之前所有步骤的结论都列出来作为“已输出参考”，要求不得近似
            if step_outputs:
                ref_parts = []
                for sid, sop in step_outputs.items():
                    ref_parts.append(
                        f"--- 步骤 {sid} 已有结论 (禁止重复) ---\n{sop.get('three')}\n{sop.get('detailed')}"
                    )
                ref_steps_content = "\n".join(ref_parts)

            user_prompt = base_user_prompt
            if ref_steps_content:
                user_prompt = (
                    f"【参考：以下是你已经在前面步骤中输出过的内容，本步骤绝对禁止复用下文的原句、原逻辑或原话术，必须寻找差异化侧重点】\n{ref_steps_content}\n\n"
                    + user_prompt
                )

            if repair_hint:
                user_prompt = (
                    f"{user_prompt}\n\n"
                    "⚠️ 严重警告：上一版输出因内容重复或不合规被拦截。请立即修正以下问题：\n"
                    f"{repair_hint}\n"
                    "请使用全新的切入点、全新的动词和句式重新描述。重点检查时间维度（过去/当前/未来）是否严格区分。"
                )
            try:
                raw_output = await ask_llm_json(user_prompt, temperature=temperature)
                output_json = _normalize_step_output(raw_output)

                # 统一 market，不让每一步自行生成
                output_json["market"] = market_snapshot

                # 币种规范化
                for key in ("market", "one", "three", "detailed", "strategy_levels"):
                    output_json[key] = _normalize_currency_text(
                        output_json.get(key, ""), us_ticker=us_ticker
                    )

                validation_issues = _validate_step_output(
                    output_json, market_text=market_snapshot
                )
                validation_issues.extend(
                    _validate_step_uniqueness(step_id, output_json, step_outputs)
                )
                if not validation_issues:
                    break

                if attempt < max_retries:
                    repair_hint = "\n".join(f"- {x}" for x in validation_issues)
                    logger.warning(
                        "步骤 %s 校验失败（第 %d/%d 次）：%s",
                        step_id,
                        attempt + 1,
                        max_retries + 1,
                        "; ".join(validation_issues),
                    )
            except Exception as exc:
                error_message = str(exc)
                raw_output = f"步骤失败：{error_message}"
                output_json = _normalize_step_output(raw_output)
                output_json["market"] = market_snapshot
                validation_issues = []
                if attempt >= max_retries:
                    logger.error(
                        "步骤 %s 调用失败（第 %d/%d 次）：%s",
                        step_id,
                        attempt + 1,
                        max_retries + 1,
                        exc,
                    )
                    break

        step_records.append(
            {
                "step_id": step_id,
                "title": title,
                "inputs": inputs,
                "logic": logic,
                "output_requirements": output_requirements,
                "output": raw_output,
                "output_json": output_json,
                "validation_issues": validation_issues,
                "attempts": used_attempts,
                "error": error_message,
            }
        )
        step_outputs[step_id] = output_json
        return output_json

    await run_step(
        "macro_single_summary",
        "单个宏观分析结果总结",
        {
            "波浪理论分析结果": skill("wave_theory"),
            "缠论分析结果": skill("chan_theory"),
            "情绪周期分析结果": skill("emotion_cycle"),
            "多头趋势分析结果": skill("bull_trend"),
        },
        "宏观判断先看长期结构与中期节奏，再结合情绪和趋势强弱形成统一结论。",
        "必须输出 6 点结构（含今日行情/OHCL、一句话、三句话、详细版、策略点位、reference）。",
        scope_constraints="只总结四个宏观技能的共同结论，不讨论短线形态细节，不输出过去/未来展望。",
    )

    await run_step(
        "pattern_single_summary",
        "单个特殊形态结果总结",
        {
            "均线金叉": skill("ma_golden_cross"),
            "放量突破": skill("volume_breakout"),
            "缩量回踩": skill("shrink_pullback"),
            "箱体震荡": skill("box_oscillation"),
            "底部放量": skill("bottom_volume"),
        },
        "先识别可交易信号，再识别冲突信号与失效条件。",
        "必须输出 6 点结构（同上 JSON 格式）。",
        scope_constraints="只回答特殊形态信号，不讨论宏观长期结构，不展开过去/未来大叙事。",
    )

    await run_step(
        "structure_side_analysis",
        "总结股票走势的结构侧分析",
        {
            "波浪理论分析结果": skill("wave_theory"),
            "缠论分析结果": skill("chan_theory"),
        },
        "先给出长周期波浪形态，再给出中期多空博弈（缠论）并综合。",
        "必须输出 6 点结构（同上 JSON 格式）。",
        scope_constraints="只做结构侧分析（波浪+缠论），不要混入情绪周期、短线形态和仓位建议模板化复读。",
    )

    await run_step(
        "trend_side_analysis",
        "总结股价走势的趋势侧分析",
        {
            "多头趋势分析结果": skill("bull_trend"),
        },
        "直接总结多头趋势分析结果。",
        "必须输出 6 点结构（同上 JSON 格式）。",
        scope_constraints="只做趋势侧分析，不要混入结构侧分析或宏观结论。",
    )

    await run_step(
        "macro_trend_summary",
        "总结股价整体宏观走势分析",
        {
            "结构侧分析": step_text("structure_side_analysis"),
            "多头趋势分析结果": skill("bull_trend"),
            "通用分析结果（若缺失请标注）": skill("dragon_head"),
        },
        "股票宏观走势一般先看长期结构侧分析，再看中期趋势分析，最后以通用分析结果作为补充。",
        "必须输出 6 点结构（同上 JSON 格式）。",
        scope_constraints="只回答整体宏观走势结论，不要复述‘当前/过去/未来’或短长线分仓建议。",
    )

    await run_step(
        "current_view_summary",
        "总结整个股票当前看法",
        {
            "股票宏观走势总结": step_text("macro_trend_summary"),
            "股票基本面总结（来自 Trading_agent）": "",
        },
        "若走势与基本面一强一弱，先写强项后写弱项；两者都强则偏长线机会；都弱则偏短线机会。若基本面输入缺失，要明确写信息不足，不允许脑补。",
        "必须输出 6 点结构（同上 JSON 格式）。重点回答“当前看法（现在）”。",
        scope_constraints="只谈当前（近5-20交易日）的定性看法和操作状态。绝对禁止提及过去几个月的复盘细节，也绝对禁止预测下个季度的利好，只关注‘此时此刻’。",
    )

    await run_step(
        "past_view_summary",
        "总结整个股票过去看法",
        {
            "股票宏观走势总结": step_text("macro_trend_summary"),
            "近期股价波动原因（来自 Trading_agent）": "",
            "近期大事件分析（来自 Trading_agent）": "",
            "股票基本面总结（来自 Trading_agent）": "",
        },
        "结合事件与波动复盘最近一年及最近三个月表现，提炼驱动因素。若事件输入缺失，明确写信息不足并仅保留可证据部分。",
        "必须输出 6 点结构（同上 JSON 格式）。重点回答“过去看法（复盘）”。",
        scope_constraints="只负责复盘历史（最近一年+最近三个月）。绝对禁止谈论‘所以现在应该买’或‘未来会涨到哪’，只描述已经发生的波动和原因。",
    )

    await run_step(
        "future_view_summary",
        "总结整个股票未来看法",
        {
            "股票宏观走势总结": step_text("macro_trend_summary"),
            "后续重要时间点大事件（来自 Trading_agent）": "",
            "股票基本面总结（来自 Trading_agent）": "",
        },
        "结合后续时间点和当前宏观走势，提炼未来关注点与潜在催化剂。若未来事件输入缺失，明确写信息不足并给出需等待的条件。",
        "必须输出 6 点结构（同上 JSON 格式）。重点回答“未来看法（展望）”。",
        scope_constraints="只负责展望（后续季度/半年）。绝对禁止重复描述当前的涨跌现状，也禁止复述过去发生的事件，只谈‘接下来要看什么、等什么’。",
    )

    await run_step(
        "long_term_investment_idea",
        "总结股票宏观长期投资思路",
        {
            "股价整体宏观走势": step_text("macro_trend_summary"),
            "股票基本面总结": "",
            "整个股票未来看法": step_text("future_view_summary"),
        },
        "股票长期投资思路一般基于股票基本面总结以及对整个股票未来看法产生投资目标，然后结合股价宏观走势判断投资节奏。",
        "必须输出 6 点结构（同上 JSON 格式）。",
        scope_constraints="专注长期投资思路，区分目标与节奏，不要复述短期行情。",
    )

    await run_step(
        "key_levels_extraction",
        "关键点位提取",
        {
            "通用分析结果": skill("bull_trend"),
            "缠论分析结果": skill("chan_theory"),
        },
        "抽取 2 个关键阻力和 2 个关键支撑，并说明每个点位依据（来自输入证据）。",
        "必须输出 6 点结构（同上 JSON 格式）。",
        scope_constraints="只做关键点位提取与依据说明，不要扩写成完整宏观报告。",
    )

    await run_step(
        "short_term_opportunities",
        "总结所有短线机会",
        {
            "均线金叉": skill("ma_golden_cross"),
            "放量突破": skill("volume_breakout"),
            "缩量回踩": skill("shrink_pullback"),
            "箱体震荡": skill("box_oscillation"),
            "底部放量": skill("bottom_volume"),
        },
        "按形态到机会映射抽取短线机会，并给出执行点位细节：均线金叉=反转、放量突破=跟随、缩量回踩=趋势回调、箱体震荡=高抛低吸、底部放量=超跌反弹。",
        "必须输出 6 点结构。在 strategy_levels 字段中，必须针对每一个识别出的形态（如均线金叉、箱体震荡等）分别列出具体的【入场点】、【止损点】和【目标点】，禁止泛泛而谈。",
        scope_constraints="只写短线机会（1-20交易日），禁止写长线持仓三情景。每一项策略必须有明确的数字点位。",
        strategy_hint="本步骤是【短线机会】。strategy_levels 必须按形态逐一列出（如均线金叉、箱体震荡等），每个形态独立一条，包含入场价/止损价/目标价。禁止写稳健型/激进型/空仓型分类，那是长线步骤的格式。",
    )

    await run_step(
        "long_term_light_summary",
        "长线投资-轻仓操作指引",
        {
            "股票整体宏观走势": step_text("macro_trend_summary"),
            "股票基本面总结（来自 Trading_agent）": "",
            "整个股票未来看法": step_text("future_view_summary"),
        },
        "核心逻辑：针对‘已有轻仓’的情况，分析长线是否值得加仓、何时加仓，或者是否需要保持现状。若基本面/宏观不佳，是否需要减仓。",
        "必须输出完整的 6 点结构。重点解答：长线投资 + 现在轻仓，怎么操作？",
        scope_constraints="只针对【轻仓】场景。禁止讨论重仓 or 空仓的情况。必须给出明确的加仓/减仓点位或分仓逻辑。",
        strategy_hint="本步骤是【长线轻仓】。strategy_levels 必须围绕'已有轻仓如何加仓'展开：在什么价位加第二笔、加仓比例多少、加仓后总仓位上限、加仓失败的止损位。禁止写短线形态策略，禁止写空仓建仓方案。",
    )

    await run_step(
        "long_term_heavy_summary",
        "长线投资-重仓操作指引",
        {
            "股票整体宏观走势": step_text("macro_trend_summary"),
            "股票基本面总结（来自 Trading_agent）": "",
            "整个股票未来看法": step_text("future_view_summary"),
        },
        "核心逻辑：针对‘已有重仓’的情况，分析长线持仓风险，是否需要逢高止盈、腾挪仓位，或者坚定持仓。评估回撤压力。",
        "必须输出完整的 6 点结构。重点解答：长线投资 + 现在重仓，怎么操作？",
        scope_constraints="只针对【重仓】场景。禁止讨论轻仓 or 空仓的情况。必须给出明确的止盈位、防守位或调仓逻辑。",
        strategy_hint="本步骤是【长线重仓】。strategy_levels 必须围绕'已有重仓如何防守和止盈'展开：逢高减仓的触发价位、减仓比例、剩余仓位的防守止损位、跌破哪里必须清仓。禁止写加仓或建仓方案。",
    )

    await run_step(
        "long_term_empty_summary",
        "长线投资-空仓（底仓）操作指引",
        {
            "股票整体宏观走势": step_text("macro_trend_summary"),
            "股票基本面总结（来自 Trading_agent）": "",
            "整个股票未来看法": step_text("future_view_summary"),
        },
        "核心逻辑：针对‘目前空仓’的情况，寻找长线底仓入场点，评估当前估值是否合理，是否需要分批建仓或继续等待。",
        "必须输出完整的 6 点结构。重点解答：长线投资 + 现在空仓，怎么操作？",
        scope_constraints="只针对【空仓/无仓】场景。禁止讨论持仓者的盈亏心态。必须给出具体的长线建仓价位和批次建议。",
        strategy_hint="本步骤是【长线空仓建底仓】。strategy_levels 必须围绕'从零开始分批建仓'展开：第一笔试探价位和仓位比例、第二笔加仓价位、总建仓完成的目标仓位、建仓期间的硬止损。禁止写减仓止盈方案。",
    )

    final_json = await run_step(
        "final_five_point_report",
        "最终综合报告",
        {
            "单个宏观分析结果总结": step_text("macro_single_summary"),
            "单个特殊形态结果总结": step_text("pattern_single_summary"),
            "趋势侧分析": step_text("trend_side_analysis"),
            "结构侧分析": step_text("structure_side_analysis"),
            "整体宏观走势": step_text("macro_trend_summary"),
            "当前看法": step_text("current_view_summary"),
            "过去看法": step_text("past_view_summary"),
            "未来看法": step_text("future_view_summary"),
            "长期投资思路": step_text("long_term_investment_idea"),
            "关键点位提取": step_text("key_levels_extraction"),
            "短线机会": step_text("short_term_opportunities"),
            "长线-轻仓建议": step_text("long_term_light_summary"),
            "长线-重仓建议": step_text("long_term_heavy_summary"),
            "长线-空仓建议": step_text("long_term_empty_summary"),
        },
        "整合所有步骤结果，形成最终一份全方位的投资研究摘要。必须清晰体现当前快照、过去复盘、未来展望、短线机会（带操作点位）、长线三类持仓部署（轻/重/空）的差异。",
        "必须输出 6 点结构。在 strategy_levels 字段中，必须综合体现短线入场/止损以及长线三类场景（轻/重/空）的最核心操作动作。",
        scope_constraints="这是唯一允许跨维度整合的步骤。必须确保最终报告能针对不同情况的阅读者提供直接指导，不得遗漏长线三类分仓方案的差异。",
        strategy_hint="本步骤是【最终综合】。strategy_levels 必须分四个明确小节输出：1)短线机会(按形态列入场/止损/目标)、2)长线轻仓(加仓逻辑)、3)长线重仓(减仓止盈逻辑)、4)长线空仓(建仓逻辑)。四个小节缺一不可，且每个小节的内容必须与对应前序步骤的结论一致但表述精炼。",
        temperature=0.5,
    )

    enriched = dict(analysis_json)
    enriched["llm_pipeline"] = {
        "model": model,
        "base_url": base_url,
        "generated_at": datetime.now().isoformat(),
        "json_format": JSON_FORMAT,
        "market_snapshot": market_snapshot,
        "steps": step_records,
    }
    enriched["structured_summary_json"] = final_json
    enriched["structured_summary"] = _step_json_to_text(final_json)

    # 4/29 新增 3 个专项分析输出到 top-level
    enriched["trend_side_analysis"] = step_outputs.get("trend_side_analysis")
    enriched["macro_trend_analysis"] = step_outputs.get("macro_trend_summary")
    enriched["long_term_investment_idea"] = step_outputs.get("long_term_investment_idea")

    return enriched


async def main() -> None:
    parser = argparse.ArgumentParser(description="读取分析 JSON 并按需求分步总结")
    parser.add_argument(
        "--input", required=True, help="run_all_analysis_api.py 输出的 JSON 路径"
    )
    parser.add_argument(
        "--output", default=None, help="输出 JSON 路径（默认：<input>.structured.json）"
    )
    parser.add_argument(
        "--output-md", default=None, help="输出 Markdown 路径（默认：<output>.md）"
    )
    parser.add_argument(
        "--output-html", default=None, help="输出 HTML 路径（默认：<output>.html）"
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="仅根据已有 JSON 渲染 Markdown/HTML，不调用大模型",
    )
    parser.add_argument(
        "--model", default=os.getenv("OPENAI_MODEL") or "gpt-4o", help="总结模型"
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPENAI_BASE_URL") or "https://api.aihubmix.com/v1",
        help="LLM Base URL",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENAI_API_KEY") or os.getenv("AIHUBMIX_KEY"),
        help="LLM API Key",
    )
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        analysis_json = json.load(f)

    output_path_val = args.output
    if not output_path_val:
        stock_code = str(analysis_json.get("stock_code", "UNKNOWN"))
        # 尝试从文件名或内容提取日期
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", input_path.name)
        if date_match:
            date_str = date_match.group(1)
        else:
            analysis_time = analysis_json.get("analysis_time", "")
            if analysis_time:
                date_str = (
                    analysis_time.split("T")[0] if "T" in analysis_time else analysis_time
                )
            else:
                date_str = datetime.now().strftime("%Y-%m-%d")

        # 构造新路径: data/analysis/TICKER/日期/daily_analysis/TICKER_日期.json
        base_dir = Path("data/analysis") / stock_code / date_str / "daily_analysis"
        output_path = base_dir / f"{stock_code}_{date_str}.json"
    else:
        output_path = Path(output_path_val).expanduser().resolve()

    output_md_path = (
        Path(args.output_md).expanduser().resolve()
        if args.output_md
        else output_path.with_suffix(".md")
    )
    output_html_path = (
        Path(args.output_html).expanduser().resolve()
        if args.output_html
        else output_path.with_suffix(".html")
    )

    if args.render_only:
        logger.info("仅渲染 Markdown/HTML: input=%s", input_path)
        enriched = analysis_json
        if not args.output_md and not args.output:
            output_md_path = input_path.with_suffix(".md")
        if not args.output_html and not args.output:
            output_html_path = input_path.with_suffix(".html")
    else:
        if not args.api_key:
            raise ValueError(
                "未找到 API Key，请传 --api-key 或配置 OPENAI_API_KEY / AIHUBMIX_KEY"
            )

        logger.info("开始分步总结: input=%s", input_path)
        enriched = await summarize_analysis_json(
            analysis_json,
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(enriched, f, ensure_ascii=False, indent=2)
        logger.info("分步总结 JSON 已保存: %s", output_path)

    markdown_report = build_markdown_report(enriched)

    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write(markdown_report)
    logger.info("最终总结 Markdown 已保存: %s", output_md_path)

    output_html_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(
            build_html_report(
                markdown_report, title=f"{enriched.get('stock_code', '')} 结构化总结"
            )
        )
    logger.info("最终总结 HTML 已保存: %s", output_html_path)

    print("\n" + "=" * 60)
    print("分步总结完成")
    print(f"输入文件: {input_path}")
    if not args.render_only:
        print(f"输出 JSON: {output_path}")
    print(f"输出 Markdown: {output_md_path}")
    print(f"输出 HTML: {output_html_path}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
