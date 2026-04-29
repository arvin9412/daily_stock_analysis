# Chatbot

    ## 规则

    TA：结果从 chatbot_web/data/TSLA/tradingAgent_analysis/ 下面的最新日期的json中直接导入
    DA：结果从 chatbot_web/data/TSLA/daily_analysis/ 下面的最新日期的json中直接导入

    TA和DA融合： 暂时采取两个结果都放出来的方式，后续需要多轮迭代prompt，具体返回结构如下：

    1. 一句话
        1. TradingAgent反馈：
        2. DailyStockAnalysis反馈：
    2. 三句话
        1. TradingAgent反馈：
        2. DailyStockAnalysis反馈：
    3. 详细
        1. TradingAgent反馈：
        2. DailyStockAnalysis反馈：


## 具体问题

1. **总结：总结股票整体宏观走势分析 （TA 1 与 DA 3融合）**
    - TA 1： 总体股价宏观走势分析 (也就是 chatbot_web/data/TSLA/tradingAgent_analysis/TSLA_2026-04-26.json 里的 'macro_trend' 键对应的值)
    - DA 3： 总结股价整体宏观走势分析 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '总结股价整体宏观走势分析' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)
2. **总结：总结股票整体长期投资思路  （TA 2 与 DA 4融合）**
    - TA 2： 总体股票长期投资思路 (也就是 chatbot_web/data/TSLA/tradingAgent_analysis/TSLA_2026-04-26.json 里的 'investment_ideas' 键对应的值)
    - DA 4： 总结股票宏观长期投资思路 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '总结股票宏观长期投资思路' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)

3. 基本面与股价：公司基本面情况  （TA 3）
    - TA 3： 公司基本面情况 (也就是 chatbot_web/data/TSLA/tradingAgent_analysis/TSLA_2026-04-26.json 里的 'fundamentals' 键对应的值)
4. 基本面与股价：近期股价波动原因 （TA 4）
    - TA 4： 近期股价波动原因 (也就是 chatbot_web/data/TSLA/tradingAgent_analysis/TSLA_2026-04-26.json 里的 'market' 键对应的值)
5. 基本面与股价：近期大事件分析 （TA 5）
    - TA 5： 近期大事件分析 (也就是 chatbot_web/data/TSLA/tradingAgent_analysis/TSLA_2026-04-26.json 里的 'events' 键对应的值)
6. 基本面与股价：后续重要时间点大事件 （TA 6）
    - TA 6： 后续重要时间点大事件 (也就是 chatbot_web/data/TSLA/tradingAgent_analysis/TSLA_2026-04-26.json 里的 'upcoming' 键对应的值)
7. 技术面：当前关键支撑与阻力位  （TA 7 与 DA 5融合）
    - TA 7： 当前关键支撑与阻力位 (也就是 chatbot_web/data/TSLA/tradingAgent_analysis/TSLA_2026-04-26.json 里的 'levels' 键对应的值)
    - DA 5： 关键点位提取 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '关键点位提取' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)

8. 技术面：走势的结构侧分析 （DA 2.a）
    - DA 2.a： 走势的结构侧分析 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '总结股票走势的结构侧分析' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)

9. 技术面：走势的趋势分析 （DA 2.b）
    - DA 2.b： 走势的趋势分析 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '总结股价走势的趋势侧分析' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)

10. **技术面：近期走势出现的特殊形态 （DA 1.b）**
    - DA 1.b： 近期走势出现的特殊形态 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '单个特殊形态结果总结' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)

11. 综合评估：总结整个股票当前走势看法 （DA 2.c）
        - DA 2.c： 总结整个股票当前看法 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '总结整个股票当前看法' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)
12. 综合评估：总结整个股票过去走势看法 （DA 2.d）
        - DA 2.d： 总结整个股票过去看法 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '总结整个股票过去看法' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)
13. 综合评估：总结整个股票未来走势看法 （DA 2.e）
        - DA 2.e： 总结整个股票未来看法 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '总结整个股票未来看法' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)

14. 交易策略：对当前空仓者建议长线交易策略   (DA 7）
    - DA 7： 对当前空仓者建议长线交易策略 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '长线投资-空仓（底仓）操作指引' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)

15. 交易策略：对当前轻仓者建议长线交易策略.   (DA 7）
    - DA 7： 对当前轻仓者建议长线交易策略 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '长线投资-轻仓操作指引' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)
16. 交易策略：对当前重仓者建议长线交易策略.   (DA 7）
    - DA 7： 对当前重仓者建议长线交易策略 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '长线投资-重仓操作指引' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)

17. 交易策略：建议短线交易策略  (DA 6）
    - DA 6： 建议短线交易策略 (也就是 chatbot_web/data/TSLA/daily_analysis/TSLA_2026-04-26.json 里的 title === '总结所有短线机会' 对应的 'output_json' 的 'one'/'three'/'detailed' 字段)

   

## 主要逻辑
1. 第一步：先不读取json文件，先和用户聊天，去识别用户想了解哪只股票（或者大盘）。
2. 第二步：判断 用户的问题是预先准备问题（预先准备的问题就是上面15个的合并问题，也就是两个json 输出来的问题，这里合并了一下）中的哪一个 ，则这里返回具体预设问题。如果不是预设问题，则这里返回"NA"

## 渐进式回复机制（新增）

用户选定个股后，点击某个维度（如"基本面"），按以下渐进式递进：

| 轮次 | 输出 | 数据来源 |
|------|------|----------|
| 第1次点击维度 | **一句话分析** | 直接从 JSON 读取（`*_one` 字段） |
| 追问/再点同一维度 | **三句话分析** | 直接从 JSON 读取（`*_three` 字段） |
| 继续追问 | **详细版本** | 直接从 JSON 读取（`*_detailed` 字段） |
| 再继续追问 | **大模型扩展** | 调用 LLM，基于完整数据自由发挥 |

- 每个维度的深度独立维护，切换维度时重置
- 前3级直接从 JSON 读取，不调用 LLM（省时间省 token）
- 第4级才开始调用大模型进行扩展

- - 系统输入
    - 读取上次聊天后的生成的用户Profile
    - 读取本次聊天历史
    - 读取聊天Rules
        - 角色
            - 股票专家，也是用户的老朋友
        - 任务
            - 给用户专业但是口语化的答疑解惑，对用户关注的个股与信息给予及时的提醒，对用户炒股过程中产生的情绪给以安抚并给出理性的策略解法
        - 约束
            - 避免给确定性的涨跌预测，强调适应市场变化，根据市场变化制定两手准备的交易策略，止盈止盈，该止损止损
- - 对话逻辑
    - 语言选择
    - 文风要求  “简短专业，不要有AI味”
    - 对话逻辑细节
        - 意图识别 （每次回复，都要把意图识别结果打印出来作为debug，显示在页面的每句回复的下面）
            {
                "ticker": // 用户询问的是个股还是大盘，还是都不是，如果是大盘返回 "Market"，如果是个股返回对应的stock ticker，如果都不是返回“NA”
                "topic": // 用户的问题是预先准备问题中的哪一个，如果是预设问题，则这里返回具体预设问题。如果不是预设问题，则这里返回“NA”
                "granularity": // 用户这个问题需要回复的详细程度，根据上下文语境从【简单回复，展开回复，详细解读】中三选一
                "extra_input_goal": // 回答用户这个问题是否需要首先收集下用户的投资目标 ，根据上下文语境从从【短期快进快出，中期持有一段时间，长期价值投】中三选一。如果不需要收集或者已经有此信息则返回“NA”
                 "extra_input_holding": // 回答用户这个问题是否需要首先收集下用户的仓位信息 ，根据上下文语境从从【空仓，轻仓，重仓】中三选一。如果不需要收集或者已经有此信息则返回“NA”
            }
            - 首先判断用户想聊的个股，还是聊大盘，还是其他
            - 其次判断用户的问题是预先准备问题中的哪一个【输入问题列表】，还是都不是。
            - 再次看下回答用户的问题是否需要收集更多用户信息，比如如果用户问道投资策略相关问题，需要必须收集的信息有：
                - 对该股票的投资目标（短期快进快出，中期持有一段时间，长期价值投资）
                - 现在的持仓仓位，空仓，轻仓，还是重仓
            - 最后根据上下文，判断用户对问题解答的颗粒度需求是简单回复，还是展开回复，还是详细解读
        - - 回复内容生成
            - 如果意图是预准备问题，则根据颗粒度需求生成回复内容
            - 如果意图是某个股票（或大盘）但不是预准备问题，则根据上下文，以及个股每日总结，生成回复内容
            - 如果意图不是个股与大盘，则根据上下文自由发挥
        - 回复润色
            - 润色
                - 输入是回复内容，根据用户对话上下文，以及用户profile，进行个性化润色
            - 反问
                - 如果有机会，在合适的地方丝滑的反问用户一个问题，目标是收集用户画像（这里给下面的用户画像的核心问题）
            - 情商
                - 讲笑话：在合适的时候也可以讲一个切合主题或者个股的笑话
                - 心理按摩：如果判断出用户处于心理波动状态，可以给予一定的巧妙自然的心理安慰
            - 回复润色总体要求
                - 反问，讲笑话，心理按摩这些可以增加，但注意一定要根据上下文丝滑潜入，不要太突兀
- - 用户画像总结
    - 在对话结束后输出以下 （一小时没有互动则启动本任务，或者每N次返回总结一下？输入用户所有的历史对话记录进行总结）
        - 用户投资目标，短期，中期，价值投资，可以多选
        - 用户投资风格，快进快出，拿着不动，跟随消息
        - 用户投资水平，技术面量化知识，基本面金融知识
        - 用户资金量级
        - 用户x个股情况list，每一只个股有以下字段（大盘当作一只个股 “Makket”）
            - 兴趣程度
                - 无，有一点，很关注
            - 投资目标
                - 短期快进快出，中期持有一段时间，长期价值投资
            - 持仓情况
                - 空仓，轻仓，重仓
            - 心态情况
                - 乐观，恐惧，FOMO，谨慎等
