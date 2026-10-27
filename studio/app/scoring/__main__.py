"""`python -m app.scoring` 的入口。

退出码:
  0  全部成功(或没有需要处理的工具)
  1  有工具评分失败(其余已成功写入并提交)
  2  配置不完整(缺 LLM_API_KEY / 模型名)

刻意不做"出错就整体回滚":批量评分里单条失败(模型偶发输出不合法)不该让另外
两百条白跑。失败的行保持原状(ai_score_at 仍为空),下次再跑会自动被捡起来。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from app.core.config import Settings, get_settings
from app.core.database import AsyncSessionLocal
from app.core.logging import configure_logging
from app.models import ToolStatus
from app.scoring.llm import OpenAICompatJudge
from app.scoring.pipeline import ScoringOptions, run_scoring

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scoring",
        description="用 LLM 对工具做主题分类 + 0~1000 评分,并写回 xg_tool.ai_* 列",
    )
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少个工具(按 id 升序)")
    parser.add_argument("--force", action="store_true", help="重评已有分数的工具(默认只补 ai_score_at 为空的)")
    parser.add_argument("--all", action="store_true", help="同 --force(口语化别名)")
    parser.add_argument("--dry-run", action="store_true", help="只调用模型并打印结果,不写库")
    parser.add_argument("--apply-topics", action="store_true", help="把 AI 主题建议写进 xg_tool_topic")
    parser.add_argument("--status", action="append", choices=[s.value for s in ToolStatus], help="要评分的状态,可重复")
    parser.add_argument("--samples", type=int, default=None, help="每个工具采样几次(默认取配置 scoring_samples)")
    parser.add_argument("--concurrency", type=int, default=None, help="并发请求数(默认取配置 scoring_concurrency)")
    parser.add_argument("--model", default=None, help="覆盖 LLM_MODEL")
    return parser


def _validate(settings: Settings) -> str | None:
    """返回错误信息;None 表示配置可用。"""
    if not settings.llm_api_key.strip():
        return "LLM_API_KEY 未配置:请在 .env.<APP_ENV> 里填写,或设置同名环境变量"
    if not settings.llm_model.strip():
        return "LLM_MODEL 为空"
    return None


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)

    if error := _validate(settings):
        logger.error(error)
        return 2

    model = args.model or settings.llm_model
    statuses = tuple(ToolStatus(value) for value in args.status) if args.status else (ToolStatus.PUBLISHED,)

    options = ScoringOptions(
        limit=args.limit,
        force=args.force or args.all,
        dry_run=args.dry_run,
        apply_topics=args.apply_topics,
        samples=args.samples or settings.scoring_samples,
        concurrency=args.concurrency or settings.scoring_concurrency,
        statuses=statuses,
    )

    judge = OpenAICompatJudge(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=model,
        timeout=settings.llm_timeout,
        temperature=settings.llm_temperature,
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

    sys.stdout.write(json.dumps(report.summary(), ensure_ascii=False, indent=2) + "\n")
    return 1 if report.failed else 0


def main() -> int:
    return asyncio.run(_run(_build_parser().parse_args()))


if __name__ == "__main__":
    sys.exit(main())
