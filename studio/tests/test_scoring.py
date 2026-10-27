"""AI 评分管线的纯函数测试(不连库、不连网)。

覆盖三块最容易悄悄坏掉的地方:
  1. rubric 权重与归一化 —— 写错一位小数,分数整体缩水但没有任何报错
  2. 贝叶斯收缩 —— 证据少时应该被拉向先验,证据多时才允许接近原始分
  3. 分类投票 + 白名单 —— 模型幻觉出的 slug 绝不能进 ai_topics
"""

from __future__ import annotations

import json

import pytest

from app.scoring.aggregate import (
    DEFAULT_PRIOR,
    MAX_AI_SCORE,
    evidence_count,
    median_scores,
    normalize_dimension,
    prior_from_scores,
    score_confidence,
    shrink,
    to_score,
    weighted_raw,
)
from app.scoring.llm import Judgement, parse_judgement
from app.scoring.pipeline import aggregate_topics
from app.scoring.prompt import AnchorExample, TopicBrief, build_system_prompt, build_user_prompt
from app.scoring.rubric import DIMENSION_KEYS, DIMENSIONS, RUBRIC_VERSION, WEIGHTS, version_tag


def _judgement(topics: list[tuple[str, float]] | None = None, scores: dict[str, int] | None = None) -> Judgement:
    dimensions = {key: {"score": 4, "reason": "ok"} for key in DIMENSION_KEYS}
    for key, value in (scores or {}).items():
        dimensions[key] = {"score": value, "reason": "ok"}
    return Judgement.model_validate(
        {
            "topics": [{"slug": slug, "confidence": confidence} for slug, confidence in (topics or [("misc", 0.9)])],
            "dimensions": dimensions,
            "summary": "",
        }
    )


# ── rubric ────────────────────────────────────────────────────────────────────


def test_rubric_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_rubric_dimension_keys_are_unique():
    assert len(DIMENSION_KEYS) == len(set(DIMENSION_KEYS)) == len(DIMENSIONS)


def test_version_tag_fits_varchar_32():
    """ai_score_version 是 VARCHAR(32),超长会 1406(500)。"""
    short = version_tag("deepseek-chat")
    long = version_tag("some-very-long-model-name-that-does-not-fit-at-all")

    assert len(short) <= 32
    assert len(long) <= 32
    assert RUBRIC_VERSION in long
    # 同名模型必须得到同一个签名,否则无法判断"是不是同一套口径"
    assert version_tag("deepseek-chat") == short


# ── 归一化与加权 ──────────────────────────────────────────────────────────────


def test_normalize_dimension_endpoints():
    assert normalize_dimension(1) == 0.0
    assert normalize_dimension(3) == 0.5
    assert normalize_dimension(5) == 1.0


@pytest.mark.parametrize("score", [0, 6, -1])
def test_normalize_dimension_rejects_out_of_range(score):
    with pytest.raises(ValueError, match="维度分必须在"):
        normalize_dimension(score)


def test_weighted_raw_is_zero_at_min_and_one_at_max():
    assert weighted_raw(dict.fromkeys(DIMENSION_KEYS, 1)) == 0.0
    assert weighted_raw(dict.fromkeys(DIMENSION_KEYS, 5)) == 1.0


def test_weighted_raw_requires_every_dimension():
    partial = dict.fromkeys(DIMENSION_KEYS[:-1], 3)
    with pytest.raises(ValueError, match="缺少维度分"):
        weighted_raw(partial)


def test_weighted_raw_weights_are_respected():
    """只有权重最高的维度是 5 分时,结果必须小于"所有维度都 5 分"。"""
    top = max(DIMENSIONS, key=lambda d: d.weight)
    scores = dict.fromkeys(DIMENSION_KEYS, 3)
    scores[top.key] = 5
    assert weighted_raw(scores) > weighted_raw(dict.fromkeys(DIMENSION_KEYS, 3))
    assert weighted_raw(scores) < 1.0


def test_median_scores_ignores_single_outlier():
    """3 次采样里一次离群不该拽偏结果(均值会被拽低,中位数不会)。"""
    samples = [
        dict.fromkeys(DIMENSION_KEYS, 4),
        dict.fromkeys(DIMENSION_KEYS, 4),
        {**dict.fromkeys(DIMENSION_KEYS, 4), "capability": 1},
    ]
    assert median_scores(samples)["capability"] == 4


def test_score_confidence_is_one_when_samples_agree():
    samples = [dict.fromkeys(DIMENSION_KEYS, 4)] * 3
    assert score_confidence(samples) == 1.0


def test_score_confidence_is_zero_at_max_spread():
    samples = [
        dict.fromkeys(DIMENSION_KEYS, 1),
        dict.fromkeys(DIMENSION_KEYS, 3),
        dict.fromkeys(DIMENSION_KEYS, 5),
    ]
    assert score_confidence(samples) == 0.0


# ── 证据与收缩 ────────────────────────────────────────────────────────────────


def test_evidence_count_counts_only_verifiable_signals():
    assert evidence_count(has_description=False, tag_count=0, topic_count=0, link_count=1) == 0
    assert evidence_count(has_description=True, tag_count=3, topic_count=2, link_count=2) == 5


def test_shrink_returns_prior_without_evidence():
    assert shrink(0.9, 0, DEFAULT_PRIOR) == DEFAULT_PRIOR


def test_shrink_approaches_raw_with_many_evidence():
    """n 远大于 m 时才能接近原始分 —— 这是 IMDb 那条公式的核心行为。"""
    near = shrink(0.9, 100, 0.5)
    assert near > 0.89
    assert near < 0.9


def test_shrink_with_few_evidence_sits_between_prior_and_raw():
    value = shrink(1.0, 1, 0.5)
    assert 0.5 < value < 1.0
    assert value == pytest.approx((1 * 1.0 + DEFAULT_PRIOR * 2.0) / 3.0)


def test_shrink_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="0~1"):
        shrink(1.5, 1, 0.5)
    with pytest.raises(ValueError, match="证据条数"):
        shrink(0.5, -1, 0.5)


def test_to_score_clamps_and_rounds():
    assert to_score(0.0) == 0
    assert to_score(1.0) == MAX_AI_SCORE
    assert to_score(-0.5) == 0
    assert to_score(1.5) == MAX_AI_SCORE
    # .5 边界向上取整,避免浮点抖动把 501 吞成 500
    assert to_score(0.5005) == 501


def test_prior_from_scores_uses_median():
    assert prior_from_scores([]) == DEFAULT_PRIOR
    assert prior_from_scores([200, 400, 900]) == pytest.approx(0.4)


# ── 输出解析 ──────────────────────────────────────────────────────────────────


def _valid_payload() -> dict[str, object]:
    return {
        "topics": [{"slug": "chat", "confidence": 0.9}],
        "dimensions": {key: {"score": 4, "reason": "有明确证据"} for key in DIMENSION_KEYS},
        "summary": "一句话总结",
    }


def test_parse_judgement_accepts_plain_json():
    judgement = parse_judgement(json.dumps(_valid_payload(), ensure_ascii=False))
    assert judgement.topics[0].slug == "chat"
    assert judgement.scores()["capability"] == 4


def test_parse_judgement_strips_markdown_fence_and_chatter():
    """模型很爱把 JSON 包进 ```json 并且前后各说一句客套话。"""
    content = "好的,结果如下:\n```json\n" + json.dumps(_valid_payload(), ensure_ascii=False) + "\n```\n希望有帮助。"
    judgement = parse_judgement(content)
    assert set(judgement.scores()) == set(DIMENSION_KEYS)


def test_parse_judgement_rejects_missing_dimension():
    payload = _valid_payload()
    dimensions = payload["dimensions"]
    assert isinstance(dimensions, dict)
    dimensions.pop("innovation")
    with pytest.raises(ValueError, match="输出结构不合法"):
        parse_judgement(json.dumps(payload, ensure_ascii=False))


def test_parse_judgement_rejects_unknown_dimension():
    payload = _valid_payload()
    dimensions = payload["dimensions"]
    assert isinstance(dimensions, dict)
    dimensions["made_up"] = {"score": 5, "reason": ""}
    with pytest.raises(ValueError, match="输出结构不合法"):
        parse_judgement(json.dumps(payload, ensure_ascii=False))


def test_parse_judgement_rejects_out_of_range_score():
    payload = _valid_payload()
    dimensions = payload["dimensions"]
    assert isinstance(dimensions, dict)
    dimensions["capability"] = {"score": 9, "reason": ""}
    with pytest.raises(ValueError, match="输出结构不合法"):
        parse_judgement(json.dumps(payload, ensure_ascii=False))


def test_parse_judgement_rejects_non_json():
    with pytest.raises(ValueError, match="合法 JSON"):
        parse_judgement("我觉得这个工具非常好")


# ── 主题投票(闭集) ──────────────────────────────────────────────────────────


def test_aggregate_topics_requires_majority():
    """3 次采样里只有 1 次提到,不采纳;2 次提到才采纳。"""
    judgements = [
        _judgement(topics=[("chat", 0.9), ("code", 0.6)]),
        _judgement(topics=[("chat", 0.8)]),
        _judgement(topics=[("misc", 0.5)]),
    ]
    winners = aggregate_topics(judgements, {"chat", "code", "misc"})
    assert [item["slug"] for item in winners] == ["chat"]
    # 得票率 2/3 × 平均自评 0.85
    assert winners[0]["confidence"] == pytest.approx(0.85 * 2 / 3, abs=1e-4)


def test_aggregate_topics_drops_slugs_outside_the_closed_set():
    """白名单是硬约束:prompt 说了"只能选清单里的",但模型仍可能发明 slug。"""
    judgements = [_judgement(topics=[("invented-topic", 0.99)])] * 3
    assert aggregate_topics(judgements, {"chat", "misc"}) == []


def test_aggregate_topics_caps_three_and_sorts_by_confidence():
    """每个工具最多保留 3 个主题;同分时按 slug 稳定排序。"""
    judgements = [
        _judgement(topics=[("a", 0.9), ("b", 0.8), ("c", 0.8)]),
        _judgement(topics=[("a", 0.9), ("b", 0.8), ("d", 0.8)]),
        _judgement(topics=[("a", 0.9), ("c", 0.8), ("d", 0.8)]),
    ]
    winners = aggregate_topics(judgements, set("abcd"))
    assert [item["slug"] for item in winners] == ["a", "b", "c"]


# ── prompt ────────────────────────────────────────────────────────────────────


def test_system_prompt_contains_closed_set_and_every_dimension():
    topics = [TopicBrief(slug="chat", name="对话", description="通用对话"), TopicBrief(slug="misc", name="未分类")]
    prompt = build_system_prompt(topics)

    assert "chat | 对话 | 通用对话" in prompt
    assert "misc | 未分类" in prompt
    for key in DIMENSION_KEYS:
        assert key in prompt
    assert "只能输出上面出现过的 slug" in prompt


def test_system_prompt_includes_human_anchors():
    example = AnchorExample(tool={"name": "示例"}, topics=["chat"], tier=5)
    prompt = build_system_prompt([TopicBrief(slug="chat", name="对话")], [example])

    assert "人工校准样例" in prompt
    assert "高档" in prompt
    assert "示例" in prompt


def test_user_prompt_never_leaks_operational_state():
    """id/status/published_at 会让模型把"收录早"误读成"质量高"。"""
    prompt = build_user_prompt({"slug": "x", "name": "X", "tagline": "一句话。"})
    assert "published_at" not in prompt
    assert "status" not in prompt
    assert '"id"' not in prompt
