"""`python -m app.scoring` 的入口。

重算的选行规则(不传任何参数时只补"从未评分"的):

  --changed            内容变了(评分输入的 SHA-256 与库里不一致)
  --stale-days [N]     太久没评(默认取 SCORING_STALE_DAYS=90)
  --outdated-version   口径变了(rubric / 模型 / 权威度占比)
  --force / --all      全量重评

退出码:
  0  全部成功(或没有需要处理的工具)
  1  有工具评分失败(其余已成功写入并提交)
  2  配置不完整(缺 LLM_API_KEY / 模型名 / 参数越界)

刻意不做"出错就整体回滚":批量评分里单条失败(模型偶发输出不合法)不该让另外
两百条白跑。失败的行保持原状(ai_score_at 没更新),下次再跑会自动被捡起来。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from app.core.config import Settings, get_settings
from app.core.database import AsyncSessionLocal, engine
from app.core.logging import configure_logging
from app.models import ToolStatus
from app.scoring.llm import OpenAICompatJudge
from app.scoring.pipeline import ScoringOptions, run_scoring

logger = logging.getLogger(__name__)

# --stale-days 不带数值时用它表示"取配置里的默认天数"
_USE_CONFIG_STALE_DAYS = -1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scoring",
        description="用 LLM 对工具做主题分类、0~1000 评分与 0~9 权威度判断,并写回 xg_tool.ai_* 列",
    )
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少个工具(按 id 升序)")
    parser.add_argument("--force", action="store_true", help="全量重评(忽略已评分/未变化)")
    parser.add_argument("--all", action="store_true", help="同 --force(口语化别名)")
    parser.add_argument("--changed", action="store_true", help="只重评输入内容变了的工具")
    parser.add_argument(
        "--stale-days",
        type=int,
        nargs="?",
        const=_USE_CONFIG_STALE_DAYS,
        default=None,
        help="只重评超过 N 天没评分的工具;省略数值时取 SCORING_STALE_DAYS",
    )
    parser.add_argument("--outdated-version", action="store_true", help="只重评口径(rubric/模型/权威度占比)已过期的")
    parser.add_argument("--dry-run", action="store_true", help="只调用模型并打印结果,不写库")
    parser.add_argument("--apply-topics", action="store_true", help="把 AI 主题建议写进 xg_tool_topic")
    parser.add_argument("--status", action="append", choices=[s.value for s in ToolStatus], help="要评分的状态,可重复")
    parser.add_argument("--samples", type=int, default=None, help="每个工具采样几次(默认取 SCORING_SAMPLES)")
    parser.add_argument("--concurrency", type=int, default=None, help="并发请求数(默认取 SCORING_CONCURRENCY)")
    parser.add_argument(
        "--authority-weight",
        type=float,
        default=None,
        help="权威度占比 0~1(默认取 SCORING_AUTHORITY_WEIGHT);改它会让 ai_score_version 变化",
    )
    parser.add_argument("--model", default=None, help="覆盖 LLM_MODEL")
    return parser


def _validate(settings: Settings, args: argparse.Namespace) -> str | None:
    """返回错误信息;None 表示配置可用。"""
    if not settings.llm_api_key.strip():
        return "LLM_API_KEY 未配置:请在 .env.<APP_ENV> 里填写,或设置同名环境变量"
    if not settings.llm_model.strip():
        return "LLM_MODEL 为空"
    if args.authority_weight is not None and not 0.0 <= args.authority_weight <= 1.0:
        return f"--authority-weight 必须在 0~1: {args.authority_weight}"
    if args.stale_days is not None and args.stale_days not in (_USE_CONFIG_STALE_DAYS,) and args.stale_days < 1:
        return f"--stale-days 必须为正整数: {args.stale_days}"
    if args.samples is not None and args.samples < 1:
        return f"--samples 必须 ≥1: {args.samples}"
    if args.concurrency is not None and args.concurrency < 1:
        return f"--concurrency 必须 ≥1: {args.concurrency}"
    return None


def _resolve_stale_days(settings: Settings, value: int | None) -> int | None:
    if value is None:
        return None
    if value == _USE_CONFIG_STALE_DAYS:
        return settings.scoring_stale_days
    return value


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)

    if error := _validate(settings, args):
        logger.error(error)
        return 2

    model = args.model or settings.llm_model
    statuses = tuple(ToolStatus(value) for value in args.status) if args.status else (ToolStatus.PUBLISHED,)

    options = ScoringOptions(
        limit=args.limit,
        force=args.force or args.all,
        changed=args.changed,
        stale_days=_resolve_stale_days(settings, args.stale_days),
        outdated_version=args.outdated_version,
        dry_run=args.dry_run,
        apply_topics=args.apply_topics,
        samples=args.samples or settings.scoring_samples,
        concurrency=args.concurrency or settings.scoring_concurrency,
        authority_weight=(
            args.authority_weight if args.authority_weight is not None else settings.scoring_authority_weight
        ),
        statuses=statuses,
    )

    judge = OpenAICompatJudge(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        max_output_tokens=settings.llm_max_output_tokens,
        reasoning_effort=settings.llm_reasoning_effort,
        structured_output=settings.llm_structured_output,
    )

    try:
        async with AsyncSessionLocal() as session:
            report = await run_scoring(session, judge, options, model_name=model)
            if args.dry_run:
                await session.rollback()
                logger.info("dry-run:已回滚,没有写入任何数据")
            else:
                await session.commit()
    except Exception as exc:
        # 不向上抛:批处理要的是一个可读的退出码,而不是一整页 traceback。
        # 已经提交的分批结果保持原状(见文件头的退出码说明)。
        logger.exception("评分中断: %s", exc)
        return 1
    finally:
        await judge.aclose()
        # 关掉连接池里最后一条连接:否则解释器退出时 aiomysql 的 __del__ 会对着
        # 已经关闭的事件循环调 close(), 在 stderr 打一段与结果无关的 traceback。
        await engine.dispose()

    sys.stdout.write(json.dumps(report.summary(), ensure_ascii=False, indent=2) + "\n")
    return 1 if report.failed else 0


def main() -> int:
    return asyncio.run(_run(_build_parser().parse_args()))


if __name__ == "__main__":
    sys.exit(main())
