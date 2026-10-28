"""AI 分类 + 评分的唯一口径(rubric)。

改这里的【任何一项】(维度、权重、锚点文案)都必须同时递增 RUBRIC_VERSION ——
版本号会写进 xg_tool.ai_score_version,是事后判断"这个分数是哪套口径算出来的"
唯一依据。没有递增就等于让两套口径的分数混在一张表里排序。

权重之和必须等于 1.0,模块导入时就校验:写错一位小数会让最终分整体缩水或溢出,
而这种错误在几十个工具的小样本上肉眼看不出来。
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Dimension:
    """一个评分维度。

    low / mid / high 是 1 / 3 / 5 分的锚点描述。只写锚点、不写"1~5 分代表什么"是
    刻意的:LLM 对具体行为描述("需要看文档才能用起来")比抽象程度词("较好")稳定
    得多,后者会让所有工具挤在 3~4 分(尺度压缩)。
    """

    key: str
    name: str
    weight: float
    low: str
    mid: str
    high: str


# 维度裁剪自 ISO/IEC 25010 的软件质量特性,并按"AI 工具目录"的消费场景做了取舍:
#   - 去掉可维护性 / 可移植性(目录用户不关心,也拿不到证据)
#   - 补上创新度(同质化是这个品类最真实的差异)
# 权重是产品判断,不是统计结论:能力权重最高,因为用户来目录是为了"能不能解决问题"。
DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        key="capability",
        name="能力匹配度",
        weight=0.28,
        low="核心功能缺失,或只能覆盖需求的一小部分",
        mid="核心场景可用,但复杂任务需要人工补位",
        high="核心场景开箱即用,能独立完成端到端任务",
    ),
    Dimension(
        key="maturity",
        name="体验成熟度",
        weight=0.22,
        low="文档/引导缺失,或明显是早期原型",
        mid="上手需要看文档,常见流程没有明显卡点",
        high="零学习成本,交互与文档都达到商业产品水准",
    ),
    Dimension(
        key="ecosystem",
        name="生态与影响",
        weight=0.18,
        low="没有可见的社区、插件或第三方集成",
        mid="有一定社区讨论或少量集成",
        high="事实标准级别的生态:大量集成、教程与开发者讨论",
    ),
    Dimension(
        key="accessibility",
        name="可及性",
        weight=0.17,
        low="必须代理/邀请码,且只有高价付费档",
        mid="可注册,免费额度有限或需要代理",
        high="可直连、有免费档、注册即用",
    ),
    Dimension(
        key="innovation",
        name="创新度",
        weight=0.15,
        low="与现有产品高度同质,没有新增能力",
        mid="在既有品类上做了明显改进",
        high="开创了新品类或新的交互范式",
    ),
)

DIMENSION_KEYS: tuple[str, ...] = tuple(d.key for d in DIMENSIONS)
WEIGHTS: dict[str, float] = {d.key: d.weight for d in DIMENSIONS}

# 口径版本:维度/权重/锚点/公式变一次就 +1
RUBRIC_VERSION = "r2"
RUBRIC_REVISION = "2026-10-28"

# 权威度(authority)的值域。它不是质量分,是"这东西在行业里有多重要"的先验,
# 与 rubric 的维度权重是两回事,所以刻意不叫 weight。
MIN_AUTHORITY = 0
MAX_AUTHORITY = 9
DEFAULT_AUTHORITY = 5

# 1~5 分的端点:归一化用 (score - MIN) / (MAX - MIN),与 aggregate 共用一份
MIN_DIMENSION_SCORE = 1
MAX_DIMENSION_SCORE = 5


def _validate() -> None:
    if abs(sum(WEIGHTS.values()) - 1.0) > 1e-9:
        raise RuntimeError(f"rubric 权重之和必须为 1.0,当前 {sum(WEIGHTS.values()):.4f}")
    if len(set(DIMENSION_KEYS)) != len(DIMENSIONS):
        raise RuntimeError("rubric 维度 key 重复")
    for dimension in DIMENSIONS:
        if not 0 < dimension.weight < 1:
            raise RuntimeError(f"维度 {dimension.key} 的权重必须在 (0, 1) 内")


_validate()


def version_tag(model: str, authority_weight: float) -> str:
    """把"口径 + 权威度占比 + 模型"压成 ≤32 字符的签名,写进 ai_score_version。

    为什么要把 authority_weight 也编进去:它直接改最终分(0.35 → 0.50 会让每个工具
    都变分)。不编进版本号,两套公式的分数就会混在一张表里排序,而且没有任何痕迹。

    xg_tool.ai_score_version 是 VARCHAR(32):超长时只保留口径 + 模型名的短哈希 ——
    仍能回答"是不是同一套口径/同一个模型",完整模型名在 ai_score_breakdown 里。
    """
    from hashlib import sha256

    weight_tag = round(authority_weight * 100)
    prefix = f"{RUBRIC_VERSION}|w{weight_tag}"
    raw = f"{prefix}|{model}"
    if len(raw) <= 32:
        return raw
    return f"{prefix}|{sha256(model.encode('utf-8')).hexdigest()[:8]}"
