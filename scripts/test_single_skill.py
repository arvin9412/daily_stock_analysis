#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单技能分析测试脚本 - 确保能正确调用 API 并保存结果

使用方法:
    python scripts/test_single_skill.py --stock AMZN --skill bull_trend
"""

import argparse
import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 11 个分析技能的中文名称
SKILL_NAMES = {
    "bull_trend": "默认多头趋势",
    "ma_golden_cross": "均线金叉",
    "volume_breakout": "放量突破",
    "shrink_pullback": "缩量回踩",
    "box_oscillation": "箱体震荡",
    "bottom_volume": "底部放量",
    "chan_theory": "缠论",
    "wave_theory": "波浪理论",
    "dragon_head": "龙头策略",
    "emotion_cycle": "情绪周期",
    "one_yang_three_yin": "一阳夹三阴",
}


async def analyze_single_skill(
    stock_code: str,
    skill_id: str,
    api_base: str = "http://127.0.0.1:8000",
    output_dir: Path = None
) -> dict:
    """
    调用单个技能分析接口，保存结果到 JSON
    """
    logger.info(f"开始分析：{stock_code} - {SKILL_NAMES.get(skill_id, skill_id)}")
    
    # 生成独立的 session_id
    session_id = f"{skill_id}_{stock_code}_{uuid.uuid4().hex[:8]}"
    
    result = {
        "stock_code": stock_code,
        "skill_id": skill_id,
        "skill_name": SKILL_NAMES.get(skill_id, skill_id),
        "session_id": session_id,
        "analysis_time": datetime.now().isoformat(),
        "api_base": api_base,
        "success": False,
        "content": None,
        "error": None,
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # 调用流式接口
            url = f"{api_base}/api/v1/agent/chat/stream"
            payload = {
                "message": f"分析一下{stock_code}",
                "session_id": session_id,
                "skills": [skill_id],
            }
            
            logger.info(f"请求 URL: {url}")
            logger.info(f"请求参数：{json.dumps(payload, ensure_ascii=False)}")
            
            full_content = ""
            line_count = 0
            
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=300)) as response:
                logger.info(f"响应状态码：{response.status}")
                
                if response.status == 200:
                    # 解析 SSE 流
                    async for line in response.content:
                        line = line.decode('utf-8').strip()
                        line_count += 1
                        
                        if line.startswith('data: '):
                            data_str = line[6:]
                            try:
                                data = json.loads(data_str)
                                event_type = data.get("type", "unknown")
                                
                                # 显示关键事件
                                if event_type in ["thinking", "tool_done", "done"]:
                                    logger.info(f"[{line_count}] {event_type}: {str(data.get('message', data.get('tool', '')))[:80]}")
                                
                                if data.get("type") == "done":
                                    full_content = data.get("content", "")
                                    logger.info(f"收到 done 事件，内容长度：{len(full_content)}")
                                    break
                            except json.JSONDecodeError as e:
                                logger.debug(f"JSON 解析失败：{e}")
                                continue
                    
                    result["success"] = bool(full_content)
                    result["content"] = full_content
                    result["line_count"] = line_count
                    
                    if full_content:
                        logger.info(f"✅ 分析成功！返回 {len(full_content)} 字符")
                    else:
                        logger.warning("⚠️ 返回空内容")
                        result["error"] = "Empty response"
                else:
                    error_text = await response.text()
                    logger.error(f"❌ API 调用失败：{response.status} - {error_text}")
                    result["error"] = f"HTTP {response.status}: {error_text}"
    
    except asyncio.TimeoutError as e:
        logger.error(f"❌ 请求超时：{e}")
        result["error"] = f"Timeout: {e}"
    
    except Exception as e:
        logger.error(f"❌ 分析失败：{e}")
        result["error"] = str(e)
    
    # 保存结果到 JSON
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"analysis_{stock_code}_{skill_id}_{timestamp}.json"
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"📁 结果已保存到：{output_file}")
        result["output_file"] = str(output_file)
    
    return result


async def main():
    parser = argparse.ArgumentParser(description="单技能分析测试")
    parser.add_argument("--stock", required=True, help="股票代码")
    parser.add_argument("--skill", default="bull_trend", 
                       choices=list(SKILL_NAMES.keys()),
                       help="技能 ID")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="API 地址")
    parser.add_argument("--output-dir", default=None, help="输出目录")
    
    args = parser.parse_args()
    
    # 设置输出目录
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(__file__).resolve().parent.parent / "data" / "skill_test"
    
    # 执行分析
    result = await analyze_single_skill(
        args.stock,
        args.skill,
        args.api_base,
        output_dir
    )
    
    # 打印摘要
    print("\n" + "=" * 60)
    print("分析完成!")
    print("=" * 60)
    print(f"股票：{result['stock_code']}")
    print(f"技能：{result['skill_name']} ({result['skill_id']})")
    print(f"状态：{'✅ 成功' if result['success'] else '❌ 失败'}")
    print(f"内容长度：{len(result['content']) if result['content'] else 0} 字符")
    
    if result.get('error'):
        print(f"错误：{result['error']}")
    
    if result.get('output_file'):
        print(f"输出文件：{result['output_file']}")
    
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
