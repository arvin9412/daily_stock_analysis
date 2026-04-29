# End-to-End Commands

## 0. 进入项目目录

```bash
cd /Users/arvin/Desktop/liulu/workspace/AI_Platforms/daily_stock_analysis
```

## 1. 启动本地 API（另开一个终端）

```bash
python webui.py
```

## 2. 先跑原始技能分析（生成原始 JSON）

先设置日期变量（示例日期：2026-04-23）：

```bash
DATE=$(date +%Y%m%d)
```

```bash
python scripts/run_all_analysis_api.py --stock AMZN
```

生成文件示例（日期已带上）：

`data/analysis_results/analysis_AMZN_${DATE}_HHMMSS.json`

## 3. 基于原始 JSON 跑分步大模型总结（生成 structured JSON + MD + HTML）

把下面命令中的输入文件替换成你第 2 步生成的 JSON（日期已带上）：

```bash
python scripts/summarize_analysis_json.py \
  --input data/analysis_results/analysis_AMZN_${DATE}_HHMMSS.json
```

固定文件名示例（2026-04-23）：

```bash
python scripts/summarize_analysis_json.py \
  --input data/analysis_results/analysis_AMZN_20260429_162454.json
```

python scripts/summarize_analysis_json.py \
  --input data/analysis_results/analysis_TSLA_20260425_141753.json

  
输出文件示例：

- `data/analysis_results/analysis_AMZN_YYYYMMDD_HHMMSS.structured.json`
- `data/analysis_results/analysis_AMZN_YYYYMMDD_HHMMSS.structured.md`
- `data/analysis_results/analysis_AMZN_YYYYMMDD_HHMMSS.structured.html`

## 4. 仅重建 md/html（不再调用大模型）

```bash
python scripts/summarize_analysis_json.py \
  --input data/analysis_results/analysis_AMZN_20260423_113924.structured.json \
  --render-only
```
