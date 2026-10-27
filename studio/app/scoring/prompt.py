"""Prompt 构造:闭集分类 + 锚定打分 + 结构化 JSON 输出。

分类准确率几乎全部来自这里的三件事,改动前请先想清楚会不会破坏它们:

1. **闭集**:把 xg_topic 的真实清单(slug / 名称 / 简介)整份塞进 system prompt,
   并明确"禁止发明 slug"。模型输出之后再按白名单过滤一次 —— prompt 是软约束,
   白名单才是硬约束。开放式分类(让模型自由命名)在目录场景里必然漂移成几百个
   同义主题,那是产品灾难,不是分类。
2. **锚点**:每个维度的 1/3/5 分都写成可观察的行为描述,而不是"较差/一般/优秀"。
   抽象程度词会让模型把所有东西打到 3~4 分,后续无论怎么加权都分不开。
3. **少样本校准**:把人工复核过的样本(review_score 非空)作为 few-shot anchor 塞进去,
   让模型的尺度对齐人。这是 LLM-as-Judge 里唯一能真正对抗"模型自有一套标准"的手段,
   也是 review_score 存在的意义。

输出强制为单个 JSON 对象(response_format=json_object),解析失败由 llm.py 重试。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.scoring.rubric import DIMENSIONS


@dataclass(frozen=True, slots=True)
class TopicBrief:
    """主题清单里的一项(来自 xg_topic,只含有助于判断的字段)。"""

    slug: str
    name: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class AnchorExample:
    """一个人工校准样本:输入摘要 + 期望输出。

    期望输出的维度分来自 review_score 的【分档】而不是原值 —— review_score 是 0~1000
    的总分,没法反推六个维度。这里只把总分映射成一个大致的档位(低/中/高),用来
    校准尺度,不假装它是逐维度的真值。
    """

    tool: dict[str, Any]
    topics: list[str]
    tier: int


_TIER_LABEL = {1: "低档", 3: "中档", 5: "高档"}


def _topic_catalog(topics: list[TopicBrief]) -> str:
    if not topics:
        # 没有主题时不能给出"空清单 + 只能从这里选"的矛盾指令
        return "- misc | 未分类 | 尚未归类的工具"
    lines = []
    for topic in topics:
        description = (topic.description or "").strip() or "(无简介,按名称判断)"
        lines.append(f"- {topic.slug} | {topic.name} | {description}")
    return "\n".join(lines)


def _rubric_table() -> str:
    lines = ["| key | 维度 | 权重 | 1 分 | 3 分 | 5 分 |", "| --- | --- | --- | --- | --- | --- |"]
    for dimension in DIMENSIONS:
        lines.append(
            f"| {dimension.key} | {dimension.name} | {dimension.weight:.2f} "
            f"| {dimension.low} | {dimension.mid} | {dimension.high} |"
        )
    return "\n".join(lines)


def _output_example() -> str:
    dimensions = {dimension.key: {"score": 3, "reason": "≤40 字,说明判断依据"} for dimension in DIMENSIONS}
    return json.dumps(
        {
            "topics": [{"slug": "misc", "confidence": 0.9}],
            "dimensions": dimensions,
            "summary": "≤60 字,说明这个工具为什么排在这个位置",
        },
        ensure_ascii=False,
        indent=2,
    )


def _anchor_section(examples: list[AnchorExample]) -> str:
    if not examples:
        return ""
    blocks = []
    for example in examples:
        tier = _TIER_LABEL.get(example.tier, "中档")
        dimensions = {
            dimension.key: {"score": example.tier, "reason": f"人工复核为{tier},作为尺度锚点"}
            for dimension in DIMENSIONS
        }
        blocks.append(
            json.dumps(
                {
                    "input": example.tool,
                    "output": {
                        "topics": [{"slug": slug, "confidence": 0.9} for slug in example.topics],
                        "dimensions": dimensions,
                        "summary": f"人工复核为{tier}",
                    },
                },
                ensure_ascii=False,
            )
        )
    return (
        "\n## 四、人工校准样例\n"
        "下面是运营人工复核过的样本(输入 → 期望输出)。请让评分尺度向它们看齐:"
        "同类工具在同一档,不要自己另起一套标准。\n" + "\n".join(blocks) + "\n"
    )


def build_system_prompt(topics: list[TopicBrief], examples: list[AnchorExample] | None = None) -> str:
    """拼 system prompt。topic 清单来自库,不是硬编码。"""
    return f"""你是 XiGee(AI 工具目录)的资深编辑。你的输出会直接写进数据库,并决定首页排序,
所以必须严格按给定清单与 rubric 工作,不允许自由发挥。

## 一、主题分类(闭集,只能从清单里选)

可用主题(格式:slug | 名称 | 简介):
{_topic_catalog(topics)}

规则:
1. 只能输出上面出现过的 slug。发明新 slug、翻译 slug、改大小写都视为错误。
2. 选 1~3 个主题,按相关度降序排列,第一个是主主题。
3. 工具只要实质涉及某个主题就选它,不要因为"不是完美匹配"就退回 misc。
4. 只有当清单里确实没有任何主题能覆盖它的核心用途时,才选 misc。
5. confidence 是你对某个 slug 的把握(0~1):主主题通常 ≥0.8,边缘主题可以低一些。

## 二、评分(5 个维度,整数 1~5,禁止小数)

{_rubric_table()}

评分纪律:
- 只依据给出的字段(名称、简介、描述、标签、主题、链接、收费、来源、可及性)判断。
- 不要臆造用户量、融资、榜单排名、真实流行度等你无法从输入核实的事实。
- 信息不足时给 3 分(中性),不要因为"没查到"就给 1 分,也不要因为"听起来很火"给 5 分。
- 每个维度写一句 ≤40 字的理由,理由必须指向输入里的具体证据。

## 三、输出格式(只输出一个 JSON 对象,不要 markdown 代码块,不要额外文字)

{_output_example()}

字段约束:
- topics:1~3 项;slug 必须在清单内;confidence 在 0~1。
- dimensions:必须且只能包含上面 {len(DIMENSIONS)} 个 key,每项是 {{"score": 1-5, "reason": "..."}}。
- summary:≤60 字。
{_anchor_section(examples or [])}"""


def build_user_prompt(tool: dict[str, Any]) -> str:
    """把工具的可判断字段序列化给模型。

    刻意不传 id / status / published_at:那些是运营状态,和"这个产品好不好"无关,
    传进去只会让模型把"收录早"误读成"质量高"。链接只给 label + url(域名),
    不给待抓取内容 —— 评分发生在离线批处理里,不做页面抓取。
    """
    return "请按 system 指令完成分类与评分。工具数据:\n" + json.dumps(tool, ensure_ascii=False, indent=2)
