"""把"多次采样的维度分"聚合成一个可排序的 0~1000 分。

这不是拍脑袋的加权平均,而是三层各自有出处的标准做法:

1. **归一化**:维度分是 1~5 的次序值,量纲一致但幅度被压缩,先线性映射到 0~1。
2. **加权**:权重来自 rubric(AHP 式的产品判断,不是等权 —— 等权会让"创新度"和
   "能力"一样重要,明显不符合目录用户的决策方式)。
3. **经验贝叶斯收缩**:这是 IMDb Top 250 的加权评分公式
   `WR = v/(v+m)·R + m/(v+m)·C` 的推广。R 是工具自己的原始分,C 是全站先验,
   v 是"证据条数",m 是先验强度。作用只有一个:**证据少的工具不要靠运气冲到前排**。
   没有它,一个只有 tagline、没有描述/标签/主题/第二个链接的工具,会完全由 LLM
   对"信息缺失"的随机反应决定名次。

最终 0~1000 只是展示尺度,单调映射,不改变任何排序关系。真正决定名次的是
`shrunk`;想换尺度不需要重算,改 to_score 的乘数即可。
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median

from app.scoring.rubric import (
    DIMENSION_KEYS,
    MAX_DIMENSION_SCORE,
    MIN_DIMENSION_SCORE,
    WEIGHTS,
)

# 先验强度:等价于"凭空多出 m 条证据,都指向全站中位数"。
# 取 2.0 是权衡的结果 —— 证据条数上限是 5,m 太大会让充分信息的工具也被拉回中位数,
# 太小则起不到抑制小样本的作用。调它之前先看 ai_score_breakdown 里的 n 分布。
SHRINKAGE_M = 2.0

# 没有任何历史分数时的先验(0.5 即"中位",不奖励也不惩罚)
DEFAULT_PRIOR = 0.5

MAX_AI_SCORE = 1000


def normalize_dimension(score: int) -> float:
    """1~5 → 0~1。超界直接报错:静默 clamp 会把模型输出错误藏起来。"""
    if not MIN_DIMENSION_SCORE <= score <= MAX_DIMENSION_SCORE:
        raise ValueError(f"维度分必须在 {MIN_DIMENSION_SCORE}~{MAX_DIMENSION_SCORE}: {score!r}")
    span = MAX_DIMENSION_SCORE - MIN_DIMENSION_SCORE
    return (score - MIN_DIMENSION_SCORE) / span


def weighted_raw(scores: dict[str, int]) -> float:
    """按 rubric 权重合成原始分(0~1)。缺维度视为上游 bug,直接抛。"""
    missing = set(DIMENSION_KEYS) - set(scores)
    if missing:
        raise ValueError(f"缺少维度分: {sorted(missing)}")
    return sum(WEIGHTS[key] * normalize_dimension(scores[key]) for key in DIMENSION_KEYS)


def median_scores(samples: Sequence[dict[str, int]]) -> dict[str, int]:
    """逐维度取中位数。

    中位数而不是均值:3 次采样里出现一次离群(比如把 4 打成 1)时,均值会被拽低,
    中位数不会。维度分是整数,中位数在 N 为奇数时仍然是整数;N 为偶数时取中间两数
    的均值再四舍五入 —— 结果可能落到 x.5,所以这里用 round 回到整数。
    """
    if not samples:
        raise ValueError("至少需要一次采样")
    return {key: round(median([sample[key] for sample in samples])) for key in DIMENSION_KEYS}


def agreement(values: Sequence[int]) -> float:
    """采样一致率(0~1),用作 ai_score_confidence。

    定义:`1 - mean(|v - median(v)|) / max_mean_deviation(N)`。
    分母是"同样本数下可能出现的最大平均离差"(一半打 1 分、一半打 5 分),所以:

      - 全部相同        → 1.0
      - N=3 时 1/3/5    → 0.0
      - N=3 时 4/4/1    → 0.25

    直接除以满分跨度 (MAX-MIN) 是不对的:那样 N=3 的最低值只能到 0.67,置信度会全部
    挤在 0.67~1 之间,失去区分力。它衡量的是"模型自己稳不稳定",不是"分数对不对" ——
    后者只能靠人工复核集来校准。
    """
    if not values:
        return 0.0
    if len(values) == 1:
        # 单次采样没有"一致"可言;返回 1.0 只是不让它污染乘积,不代表可信
        return 1.0
    center = median(values)
    spread = sum(abs(value - center) for value in values) / len(values)
    max_spread = (MAX_DIMENSION_SCORE - MIN_DIMENSION_SCORE) * (len(values) - 1) / (2 * len(values))
    if max_spread == 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - spread / max_spread))


def score_confidence(samples: Sequence[dict[str, int]]) -> float:
    """跨维度、跨采样的整体置信度。"""
    if not samples:
        return 0.0
    per_dimension = [agreement([sample[key] for sample in samples]) for key in DIMENSION_KEYS]
    return sum(per_dimension) / len(per_dimension)


def evidence_count(
    *,
    has_description: bool,
    tag_count: int,
    topic_count: int,
    link_count: int,
) -> int:
    """证据条数 v(0~5),喂给收缩公式。

    刻意只用"可核对的完整度"信号,不用 LLM 的自我评分:模型说自己有把握,恰恰是
    最不可信的那种证据。这五项都能从库里直接数出来,可复现、可审计。
    """
    signals = (
        has_description,
        tag_count >= 3,
        topic_count >= 1,
        topic_count >= 2,
        link_count >= 2,
    )
    return sum(1 for signal in signals if signal)


def shrink(raw: float, n: int, prior: float, m: float = SHRINKAGE_M) -> float:
    """经验贝叶斯收缩:`(n*raw + m*prior) / (n+m)`。

    n=0 时完全等于先验;n 远大于 m 时接近原始分。这正是 IMDb 用 m=25000 干的事 ——
    让"1 个人打 10 分"永远排不到"10 万人打 8.9 分"前面。
    """
    if n < 0:
        raise ValueError(f"证据条数不能为负: {n}")
    if not 0.0 <= raw <= 1.0 or not 0.0 <= prior <= 1.0:
        raise ValueError(f"raw/prior 必须在 0~1: raw={raw}, prior={prior}")
    if m < 0:
        raise ValueError(f"先验强度不能为负: {m}")
    total = n + m
    if total == 0:
        return prior
    return (n * raw + m * prior) / total


def to_score(value: float) -> int:
    """0~1 → 0~1000 整数(单调映射,仅展示尺度)。"""
    clamped = min(1.0, max(0.0, value))
    # 加 1e-9 抵消二进制浮点在 .5 边界上的抖动(0.5005*1000 = 500.49999…)
    return round(clamped * MAX_AI_SCORE + 1e-9)


def prior_from_scores(existing: Sequence[int]) -> float:
    """全站先验 = 已有分数的中位数(0~1000 → 0~1)。

    用中位数而不是均值:均值会被少数满分/零分拉偏,而先验的作用是"代表典型工具"。
    没有任何历史分数时退回 0.5。
    """
    if not existing:
        return DEFAULT_PRIOR
    return median(existing) / MAX_AI_SCORE
