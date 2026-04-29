# 💬 Stock Chatbot — 股票对话助手

一个基于已生成分析结果的 **轻量对话式股票助手**，直接读取每日分析产出的结构化 JSON 文件作为知识库，无需额外调用分析引擎。

## 与 Agent 问股的区别

| 特性 | Agent 策略问股 | Chatbot 对话助手 |
|------|---------------|-----------------|
| **数据源** | 实时调用工具链（行情+K线+新闻+11 种策略） | 已生成的分析 JSON 文件（预计算结果） |
| **响应速度** | 较慢（需调用多个工具） | 快（直接读取知识库） |
| **Token 消耗** | 高（多轮工具调用） | 低（单次 LLM 调用） |
| **适用场景** | 深度技术分析、实时行情问答 | 快速答疑、已有分析结果的口语化解读 |
| **用户画像** | ❌ 无 | ✅ 自动收集并更新 |

## 功能特性

- **角色定位**：股票专家 + 老朋友，专业但口语化，拒绝 AI 味
- **意图识别**：自动判断用户想聊个股、大盘还是闲聊，匹配预置问题列表
- **多维数据融合**：合并两份 JSON（简洁版 + 11 技能结构版）构建统一知识库
- **用户画像收集**：每 5 轮对话后台自动更新画像（投资目标/风格/水平/资金量/个股持仓心态）
- **渐进式回复**：首次询问 → 一句话回复，追问 → 三句话，继续深入 → 详细版
- **意图识别**：每次回复自动输出意图 debug 信息（ticker / topic / granularity / 信息收集需求），默认折叠显示
- **自动识别股票**：无需手动选择，AI 自动从消息中提取股票代码并加载对应分析数据
- **两阶段对话**：第一阶段纯聊天（不加载 JSON），当识别到具体股票 + 具体问题后才加载分析数据
- **实时股价**：当用户问到价格相关问题时，自动通过 Yahoo Finance 获取最新实时股价并注入对话
- **约束设计**：不做确定性涨跌预测，强调两手准备、止盈止损

## 快速使用

### 1. 启动服务

```bash
cd scripts/新需求
bash start_chatbot.sh
```

启动后看到以下输出即成功：

```
Starting Chatbot API server...
  Model: qwen3.6-plus
  Base URL: https://coding.dashscope.aliyuncs.com/v1
  Web UI: http://localhost:8899
  API Docs: http://localhost:8899/docs
```

### 2. 访问聊天界面

浏览器打开 `http://localhost:8899` 即可开始对话。

![Chatbot UI](chatbot_ui_preview.png)

## 数据源

Chatbot 从 **当前目录**（`scripts/新需求/`）读取已生成的分析 JSON 文件：

| 文件类型 | 示例文件名 | 内容 |
|----------|-----------|------|
| 简洁版 | `AMZN_2026-04-22.json` | 基本面/策略/关键点位摘要（one/three/detailed 三级） |
| 结构版 | `analysis_AMZN_20260423_113924.structured.json` | 11 种技能详细分析报告 + LLM 结构化总结 |

**合并逻辑**：
1. 简洁版提取：基本面、市场宏观、大事件、未来展望、关键点位、长短线策略、多空辩论
2. 结构版提取：LLM pipeline 的 8 个步骤输出（宏观总结/形态总结/结构分析/趋势/当前看法/过去看法/未来看法/关键点位）
3. 统一注入到 System Prompt，AI 根据问题类型自动选择合适的数据维度作答

**添加新股票**：把对应 JSON 文件放到同一目录，在 Web UI 的 ticker 下拉框切换即可。

## API 接口

### POST /api/chat

普通聊天，返回完整回复。

```bash
curl -X POST http://localhost:8899/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "AMZN 走势如何？",
    "ticker": "AMZN",
    "session_id": "可选，用于多轮对话"
  }'
```

**响应**：

```json
{
  "session_id": "uuid-string",
  "reply": "AMZN 这波走势挺有意思...",
  "ticker": "AMZN",
  "prepared_questions": ["公司基本面情况", "近期股价波动原因", ...],
  "user_profile": {...},
  "intent": {
    "ticker": "AMZN",
    "topic": "公司基本面情况",
    "granularity": "详细解读",
    "extra_input_goal": "NA",
    "extra_input_holding": "需要"
  }
}
```

### POST /api/chat/stream

SSE 流式聊天，打字机效果。

```bash
curl -N -X POST http://localhost:8899/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "AMZN 风险在哪？", "ticker": "AMZN"}'
```

**SSE 事件类型**：

| type | 说明 |
|------|------|
| `token` | 单个 token，含 `content` 字段 |
| `done` | 流结束，含 `session_id`、`prepared_questions` |
| `error` | 错误信息，含 `message` 字段 |

### GET /api/sessions/{session_id}/profile

获取当前会话的用户画像。

### GET /api/sessions/{session_id}/history

获取当前会话的聊天历史。

### POST /api/profile

手动触发用户画像更新。

## 环境变量

Chatbot 自动读取项目根目录的 `.env` 文件，支持以下变量：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | DashScope API Key | 必填 |
| `OPENAI_BASE_URL` | API 端点 | `https://coding.dashscope.aliyuncs.com/v1` |
| `OPENAI_MODEL` | 模型名称 | `qwen3.6-plus` |

也可使用专用变量覆盖：

| 变量 | 说明 |
|------|------|
| `DASHSCOPE_API_KEY` | 覆盖 OPENAI_API_KEY |
| `DASHSCOPE_BASE_URL` | 覆盖 OPENAI_BASE_URL |
| `DASHSCOPE_MODEL` | 覆盖 OPENAI_MODEL |

## 文件结构

```
scripts/新需求/
├── chatbot_server.py      # FastAPI 后端主程序
├── chatbot_web/
│   └── index.html         # Web 聊天界面（深色主题）
├── start_chatbot.sh       # 启动脚本（自动加载 .env）
├── test_api.py            # API 自测脚本
├── Chatbot.md             # 需求文档
├── AMZN_2026-04-22.json   # AMZN 简洁版分析数据
├── analysis_AMZN_20260423_113924.structured.json  # AMZN 结构版分析数据
├── TSLA_2026-04-25.json   # TSLA 简洁版分析数据
└── analysis_TSLA_20260425_141753.structured.json  # TSLA 结构版分析数据
```

## 常见问题

### Q: 为什么返回 401 错误？
A: 检查 `.env` 中的 `OPENAI_API_KEY` 是否有效，以及 `OPENAI_BASE_URL` 是否正确。

### Q: 如何切换到其他股票？
A: 把对应股票的 JSON 文件放到当前目录，然后在 Web UI 顶部的 ticker 下拉框选择即可。代码会自动匹配 `analysis_{TICKER}_*.structured.json` 和 `{TICKER}_*.json`。

### Q: 用户画像什么时候更新？
A: 默认每 5 轮对话自动触发一次后台画像更新。也可以通过 `POST /api/profile` 手动触发。

### Q: 如何自定义预置问题？
A: 修改 `chatbot_server.py` 中 `ChatbotKnowledge.get_prepared_questions()` 方法返回列表内容即可。

## 开发说明

- **Python 版本**：3.9+
- **依赖**：`fastapi`, `uvicorn`, `openai`, `pydantic`
- **端口**：8899（可在 `chatbot_server.py` 末尾修改）
- **关闭深度思考**：已配置 `enable_thinking=false` + `thinking_enabled=false` 确保快速响应（2-5 秒）
