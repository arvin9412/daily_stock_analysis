#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量运行所有分析技能，汇总结果到大模型进行结构化总结

使用方法:
    python scripts/run_all_analysis_api.py --stock 600519
    python scripts/run_all_analysis_api.py --stock AMZN --market us
    python scripts/run_all_analysis_api.py --stock 600519 --summarize
"""

import argparse
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 所有要运行的分析技能（对应 strategies/ 目录下的 yaml 文件名）
ANALYSIS_SKILLS = [
    "bull_trend",            # 默认多头趋势
    "ma_golden_cross",       # 均线金叉
    "volume_breakout",       # 放量突破
    "shrink_pullback",       # 缩量回踩
    "box_oscillation",       # 箱体震荡
    "bottom_volume",         # 底部放量
    "chan_theory",           # 缠论
    "wave_theory",           # 波浪理论
    "dragon_head",           # 龙头策略
    "emotion_cycle",         # 情绪周期
    "one_yang_three_yin",    # 一阳夹三阴
]

# 默认 API 配置
DEFAULT_API_BASE = "http://127.0.0.1:8000"


async def run_single_skill(
    session: aiohttp.ClientSession,
    skill_id: str,
    stock_code: str,
    api_base: str = DEFAULT_API_BASE,
    max_retries: int = 1,
) -> Dict[str, Any]:
    """通过 API 运行单个分析技能 - 使用流式接口并在空结果时重试。"""
    logger.info(f"开始运行分析技能：{skill_id} - {stock_code}")

    for attempt in range(max_retries + 1):
        try:
            # 为每个技能生成独立的 session_id，避免并发冲突
            skill_session_id = f"{skill_id}_{stock_code}_{uuid.uuid4().hex[:8]}"

            # 使用流式接口，和 test_single_skill 保持一致
            url = f"{api_base}/api/v1/agent/chat/stream"
            payload = {
                "message": f"请用{skill_id}策略分析{stock_code}，给出详细的技能分析结果",
                "session_id": skill_session_id,
                "skills": [skill_id],
            }

            full_content = ""
            event_error = None

            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=300)) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"技能 {skill_id} API 调用失败：{response.status} - {error_text}")
                    return {
                        "skill_id": skill_id,
                        "success": False,
                        "result": None,
                        "error": f"HTTP {response.status}: {error_text}",
                    }

                async for line in response.content:
                    line = line.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    event_type = data.get("type")
                    if event_type == "done":
                        full_content = data.get("content", "") or ""
                        break
                    if event_type == "error":
                        event_error = data.get("message") or "SSE error event"
                        break

            if full_content:
                logger.info(
                    "技能 %s 分析完成(尝试%d/%d)，返回 %d 字符",
                    skill_id,
                    attempt + 1,
                    max_retries + 1,
                    len(full_content),
                )
                return {
                    "skill_id": skill_id,
                    "success": True,
                    "result": full_content,
                    "error": None,
                }

            if event_error:
                logger.error("技能 %s 分析失败(尝试%d/%d): %s", skill_id, attempt + 1, max_retries + 1, event_error)
                if attempt >= max_retries:
                    return {
                        "skill_id": skill_id,
                        "success": False,
                        "result": None,
                        "error": event_error,
                    }
            else:
                logger.warning("技能 %s 返回空内容(尝试%d/%d)", skill_id, attempt + 1, max_retries + 1)
                if attempt >= max_retries:
                    return {
                        "skill_id": skill_id,
                        "success": False,
                        "result": None,
                        "error": "Empty response",
                    }

            await asyncio.sleep(attempt + 1)

        except asyncio.TimeoutError as exc:
            logger.warning("技能 %s 超时(尝试%d/%d): %s", skill_id, attempt + 1, max_retries + 1, exc)
            if attempt >= max_retries:
                return {
                    "skill_id": skill_id,
                    "success": False,
                    "result": None,
                    "error": f"Timeout: {exc}",
                }
            await asyncio.sleep(attempt + 1)
        except Exception as exc:
            logger.error("技能 %s 分析失败(尝试%d/%d): %s", skill_id, attempt + 1, max_retries + 1, exc)
            if attempt >= max_retries:
                return {
                    "skill_id": skill_id,
                    "success": False,
                    "result": None,
                    "error": str(exc),
                }
            await asyncio.sleep(attempt + 1)

    return {
        "skill_id": skill_id,
        "success": False,
        "result": None,
        "error": "Unknown error",
    }


async def run_all_analysis(
    stock_code: str,
    api_base: str = DEFAULT_API_BASE,
    output_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """通过 API 运行所有分析技能并汇总结果 - 顺序执行以保证稳定性"""
    logger.info(f"开始批量分析：{stock_code} (顺序执行模式)")
    
    # 生成一个 batch ID 用于这一轮分析
    batch_id = f"batch_{stock_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    async with aiohttp.ClientSession() as session:
        # 顺序执行每个技能，避免并发问题
        results = []
        for skill_id in ANALYSIS_SKILLS:
            result = await run_single_skill(session, skill_id, stock_code, api_base)
            results.append(result)
    
    # 汇总结果
    summary = {
        "stock_code": stock_code,
        "batch_id": batch_id,
        "analysis_time": datetime.now().isoformat(),
        "total_skills": len(ANALYSIS_SKILLS),
        "success_count": sum(1 for r in results if r["success"]),
        "failed_count": sum(1 for r in results if not r["success"]),
        "results": results
    }
    
    # 保存结果
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"analysis_{stock_code}_{timestamp}.json"
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        logger.info(f"分析结果已保存到：{output_file}")
        summary["output_file"] = str(output_file)
    
    return summary


def _get_skill_texts(analysis_results: Dict[str, Any]) -> Dict[str, str]:
    texts: Dict[str, str] = {}
    for item in analysis_results.get("results", []):
        if item.get("success") and item.get("result"):
            texts[item["skill_id"]] = str(item["result"])
    return texts


def _safe_text(value: Optional[str], fallback: str = "信息不足，无法判断") -> str:
    stripped = (value or "").strip()
    return stripped if stripped else fallback


def _render_inputs(inputs: Dict[str, str]) -> str:
    parts: List[str] = []
    for name, content in inputs.items():
        parts.append(f"### {name}\n{_safe_text(content)}")
    return "\n\n".join(parts)


async def summarize_with_llm(
    analysis_results: Dict[str, Any],
    output_file: Optional[str] = None
) -> str:
    """按需求定义逐步请求大模型，并记录每步输入/输出到 JSON。"""
    from openai import AsyncOpenAI

    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("AIHUBMIX_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or "https://api.aihubmix.com/v1"
    model = os.getenv("OPENAI_MODEL") or "gpt-4o"

    if not api_key:
        logger.error("未找到 API Key，请检查 .env 文件中的 OPENAI_API_KEY 或 AIHUBMIX_KEY")
        return "错误：未配置 API Key"

    logger.info("使用 API Base: %s, 模型：%s", base_url, model)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    stock_code = analysis_results.get("stock_code", "UNKNOWN")
    skill_texts = _get_skill_texts(analysis_results)
    step_records: List[Dict[str, Any]] = []
    step_outputs: Dict[str, str] = {}

    def skill(skill_id: str) -> str:
        return skill_texts.get(skill_id, "")

    async def run_step(
        step_id: str,
        title: str,
        inputs: Dict[str, str],
        logic: str,
        output_requirements: str,
        temperature: float = 0.4,
    ) -> str:
        user_prompt = (
            f"你正在执行股票分析结构化抽取流程中的一步。\n\n"
            f"股票代码：{stock_code}\n"
            f"步骤标识：{step_id}\n"
            f"步骤名称：{title}\n\n"
            f"任务目标：\n{title}\n\n"
            f"输入信息：\n{_render_inputs(inputs)}\n\n"
            f"内在逻辑：\n{logic}\n\n"
            f"输出要求：\n{output_requirements}\n\n"
            f"约束：\n"
            f"1. 严格基于输入，不要编造事实。\n"
            f"2. 如信息不足，明确写“信息不足，无法判断”。\n"
            f"3. 只输出本步骤结果正文，不要回显“输入信息”字样。\n"
        )
        system_prompt = "你是严谨的股票研究助理，擅长按固定流程做结构化归纳。"

        output_text: str
        error_message: Optional[str] = None
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
            output_text = _safe_text(response.choices[0].message.content)
        except Exception as exc:
            error_message = str(exc)
            output_text = f"步骤失败：{error_message}"
            logger.error("步骤 %s 调用失败：%s", step_id, exc)

        step_records.append(
            {
                "step_id": step_id,
                "title": title,
                "inputs": inputs,
                "logic": logic,
                "output_requirements": output_requirements,
                "prompt": {
                    "system": system_prompt,
                    "user": user_prompt,
                },
                "output": output_text,
                "error": error_message,
            }
        )
        step_outputs[step_id] = output_text
        return output_text

    # ===== 第 1 组：单项抽取 =====
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
        "输出 3 段：宏观主结论、证据要点、风险提示。",
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
        "对形态进行并行归纳，先识别可交易信号，再识别冲突信号与失效条件。",
        "输出 3 段：形态共识、冲突点、执行优先级。",
    )

    # ===== 第 2 组：进一步概括总结 =====
    await run_step(
        "structure_side_analysis",
        "总结股票走势的结构侧分析",
        {
            "波浪理论分析结果": skill("wave_theory"),
            "缠论分析结果": skill("chan_theory"),
        },
        "先给出长周期波浪形态，再给出中期多空博弈（缠论）并综合。",
        "输出“长期结构 + 中期结构 + 结构结论”三段。",
    )

    await run_step(
        "macro_trend_summary",
        "总结股票整体宏观走势",
        {
            "结构侧分析": step_outputs.get("structure_side_analysis", ""),
            "多头趋势分析结果": skill("bull_trend"),
            "通用分析结果（若缺失请标注）": skill("dragon_head"),
        },
        "先长期结构，再中期趋势，最后以通用分析补充验证。",
        "输出“趋势方向 + 运行阶段 + 关键风险/拐点”。",
    )

    await run_step(
        "current_view_summary",
        "总结整个股票当前看法",
        {
            "股票宏观走势总结": step_outputs.get("macro_trend_summary", ""),
            "股票基本面总结（来自 Trading_agent）": "",
        },
        "若走势与基本面一强一弱，先写强项后写弱项；两者都强则偏长线机会；都弱则偏短线机会。",
        "输出“当前看法结论 + 多空平衡判断 + 操作倾向”。",
    )

    await run_step(
        "past_view_summary",
        "总结整个股票过去看法",
        {
            "股票宏观走势总结": step_outputs.get("macro_trend_summary", ""),
            "近期股价波动原因（来自 Trading_agent）": "",
            "近期大事件分析（来自 Trading_agent）": "",
            "股票基本面总结（来自 Trading_agent）": "",
        },
        "结合事件与波动复盘最近一年及最近三个月表现，提炼驱动因素。",
        "输出“过去一年表现 + 近三个月表现 + 关键驱动因素”。",
    )

    await run_step(
        "future_view_summary",
        "总结整个股票未来看法",
        {
            "股票宏观走势总结": step_outputs.get("macro_trend_summary", ""),
            "后续重要时间点大事件（来自 Trading_agent）": "",
            "股票基本面总结（来自 Trading_agent）": "",
        },
        "结合后续时间点和当前宏观走势，提炼未来关注点与潜在催化剂。",
        "输出“未来主线 + 关键时间节点 + 风险/催化清单”。",
    )

    # ===== 第 3 组：点位与策略抽取 =====
    await run_step(
        "key_levels_extraction",
        "关键点位提取",
        {
            "通用分析结果": skill("bull_trend"),
            "缠论分析结果": skill("chan_theory"),
        },
        "抽取 2 个关键阻力和 2 个关键支撑，并说明每个点位依据。",
        "输出一个 Markdown 表格：类型/价位/原因理由。",
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
        "按形态到机会映射抽取短线机会，并给出执行点位细节。",
        (
            "逐条输出短线机会，每条包含：机会类型、入场点位、止损位、止盈位、仓位建议。"
            "若无机会，明确说明触发条件未满足。"
        ),
    )

    await run_step(
        "long_term_opportunities",
        "总结长线机会",
        {
            "股票整体宏观走势": step_outputs.get("macro_trend_summary", ""),
            "股票基本面总结（来自 Trading_agent）": "",
            "整个股票未来看法": step_outputs.get("future_view_summary", ""),
        },
        "先判断是否存在长线机会，再按重仓/轻仓/无仓三种持仓状态给建议。",
        "输出“是否有长线机会 + 三种持仓状态下的操作建议 + 等待条件”。",
    )

    # ===== 最终五点输出 =====
    final_summary = await run_step(
        "final_five_point_report",
        "最终五点产出",
        {
            "单个宏观分析结果总结": step_outputs.get("macro_single_summary", ""),
            "单个特殊形态结果总结": step_outputs.get("pattern_single_summary", ""),
            "结构侧分析": step_outputs.get("structure_side_analysis", ""),
            "整体宏观走势": step_outputs.get("macro_trend_summary", ""),
            "当前看法": step_outputs.get("current_view_summary", ""),
            "过去看法": step_outputs.get("past_view_summary", ""),
            "未来看法": step_outputs.get("future_view_summary", ""),
            "关键点位提取": step_outputs.get("key_levels_extraction", ""),
            "短线机会": step_outputs.get("short_term_opportunities", ""),
            "长线机会": step_outputs.get("long_term_opportunities", ""),
        },
        "把前面所有步骤结果整合为最终报告，保持逻辑一致且可执行。",
        (
            "严格输出 5 部分："
            "1) 详细版；2) 一句话总结分析；3) 三句话总结分析；"
            "4) 潜在交易策略与关键点位；5) Reference（具体 link，若无则写信息不足）。"
        ),
        temperature=0.5,
    )

    analysis_results["llm_pipeline"] = {
        "model": model,
        "base_url": base_url,
        "generated_at": datetime.now().isoformat(),
        "steps": step_records,
    }
    analysis_results["structured_summary"] = final_summary

    if output_file:
        # 将包含分步输入输出的完整结构回写到同一个 JSON
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(analysis_results, f, ensure_ascii=False, indent=2)
        logger.info("已将分步 LLM 输入输出写回 JSON：%s", output_file)

        summary_file = Path(output_file).with_suffix(".md")
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write("# 股票分析结构化总结\n\n")
            f.write(f"**股票**: {analysis_results.get('stock_code', '')}\n\n")
            f.write(f"**分析时间**: {analysis_results.get('analysis_time', '')}\n\n")
            f.write("---\n\n")
            f.write(final_summary)
        logger.info("结构化总结已保存到：%s", summary_file)

    return final_summary


async def main():
    parser = argparse.ArgumentParser(description="通过 API 批量运行所有分析技能并汇总结果")
    parser.add_argument("--stock", required=True, help="股票代码")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="API 基础地址")
    parser.add_argument("--output-dir", default=None, help="输出目录")
    parser.add_argument("--summarize", action="store_true", help="是否使用大模型进行结构化总结")
    
    args = parser.parse_args()
    
    # 设置输出目录
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(__file__).resolve().parent.parent / "data" / "analysis_results"
    
    # 运行所有分析
    analysis_results = await run_all_analysis(
        args.stock,
        args.api_base,
        output_dir
    )
    
    print("\n" + "=" * 60)
    print("分析完成!")
    print(f"股票：{analysis_results['stock_code']}")
    print(f"成功：{analysis_results['success_count']}/{analysis_results['total_skills']}")
    print(f"输出文件：{analysis_results.get('output_file', 'N/A')}")
    print("=" * 60 + "\n")
    
    # 使用大模型总结
    if args.summarize:
        print("正在使用大模型进行结构化总结...")
        summary = await summarize_with_llm(
            analysis_results,
            analysis_results.get("output_file")
        )
        print("\n" + "=" * 60)
        print("结构化总结:")
        print("=" * 60)
        print(summary)
        print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
