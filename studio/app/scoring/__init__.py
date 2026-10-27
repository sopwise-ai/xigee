"""AI 分类 + 评分(离线管线)。

用法::

    uv run python -m app.scoring --limit 10 --dry-run     # 先看效果,不写库
    uv run python -m app.scoring --force --apply-topics   # 全量重评 + 应用主题
    uv run python -m app.scoring                          # 只补没评过的

模块分工:

    rubric.py     评分口径(维度/权重/锚点/版本)—— 改它必须递增 RUBRIC_VERSION
    prompt.py     闭集分类 + 锚定打分的 prompt
    llm.py        OpenAI 兼容客户端与严格解析
    aggregate.py  归一化 → 加权 → 贝叶斯收缩 → 0~1000
    pipeline.py   取数 → 采样 → 聚合 → 写回(只写 ai_* 列)

评分结果会写进 xg_tool 的 ai_* 列,并成为导出/列表的唯一排序依据;
人工复核(review_*)不在这里写,它只用来做 few-shot 校准。
"""
