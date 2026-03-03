"""精度評価スクリプト（TASK-F04）

人間の判定結果（正解データ）とシステム出力を比較し、
判定一致率・確信度別精度・Confusion Matrixを算出する。

Usage:
    python scripts/evaluate_accuracy.py \
        --case-id <UUID> \
        --ground-truth <path.xlsx> \
        [--output <output.json>]
"""

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import create_session_factory
from app.models.mapping_result import MappingResult
from app.models.requirement import FunctionalRequirement


# ─── Dataclasses ───


@dataclass
class GroundTruthRow:
    """正解データの1行。"""

    function_name: str
    expected_judgment_level: str
    business_category: str | None = None
    notes: str | None = None


@dataclass
class MismatchDetail:
    """不一致件の詳細。"""

    requirement_id: str
    function_name: str
    expected: str
    actual: str
    confidence: str
    confidence_score: float
    scope_item_analysis: str
    gap_analysis: str
    judgment_reason: str


@dataclass
class AccuracyMetrics:
    """精度メトリクス。"""

    total_pairs: int
    matched_count: int
    overall_accuracy: float
    accuracy_by_confidence: dict[str, float]
    accuracy_by_judgment: dict[str, dict[str, int]]  # Confusion Matrix
    mismatch_details: list[MismatchDetail]


@dataclass
class AccuracyReport:
    """精度評価レポート。"""

    case_id: str
    evaluated_at: str
    metrics: AccuracyMetrics
    pass_threshold: float = 0.70
    is_passed: bool = False


# ─── Core ───


def load_ground_truth(path: Path) -> list[GroundTruthRow]:
    """正解データ Excel を読み込む。

    想定列: 機能名 | 判定レベル（正解）| 業務分類 | 備考
    """
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if len(rows) < 2:
        raise ValueError("正解データに有効な行がありません")

    headers = [str(h).strip() if h else "" for h in rows[0]]

    # 列マッピング（柔軟に対応）
    fn_idx = None
    jl_idx = None
    bc_idx = None
    note_idx = None

    for i, h in enumerate(headers):
        hl = h.lower()
        if "機能名" in h or "function" in hl:
            fn_idx = i
        elif "判定" in h or "judgment" in hl:
            jl_idx = i
        elif "業務" in h or "category" in hl:
            bc_idx = i
        elif "備考" in h or "note" in hl:
            note_idx = i

    if fn_idx is None or jl_idx is None:
        raise ValueError(
            f"必須列（機能名/判定レベル）が見つかりません。ヘッダー: {headers}"
        )

    result = []
    for row in rows[1:]:
        fn = row[fn_idx] if fn_idx < len(row) else None
        jl = row[jl_idx] if jl_idx < len(row) else None
        if not fn or not jl:
            continue
        result.append(
            GroundTruthRow(
                function_name=str(fn).strip(),
                expected_judgment_level=str(jl).strip(),
                business_category=str(row[bc_idx]).strip() if bc_idx and bc_idx < len(row) and row[bc_idx] else None,
                notes=str(row[note_idx]).strip() if note_idx and note_idx < len(row) and row[note_idx] else None,
            )
        )

    return result


def match_results(
    ground_truth: list[GroundTruthRow],
    results: list[tuple[FunctionalRequirement, MappingResult]],
) -> list[tuple[GroundTruthRow, FunctionalRequirement, MappingResult]]:
    """function_name で突合。"""
    result_map: dict[str, tuple[FunctionalRequirement, MappingResult]] = {}
    for fr, mr in results:
        result_map[fr.function_name.strip()] = (fr, mr)

    pairs = []
    for gt in ground_truth:
        key = gt.function_name
        if key in result_map:
            fr, mr = result_map[key]
            pairs.append((gt, fr, mr))

    return pairs


def calculate_metrics(
    pairs: list[tuple[GroundTruthRow, FunctionalRequirement, MappingResult]],
) -> AccuracyMetrics:
    """精度メトリクスを算出。"""
    total = len(pairs)
    matched = 0
    by_confidence: dict[str, list[bool]] = defaultdict(list)
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    mismatches: list[MismatchDetail] = []

    for gt, fr, mr in pairs:
        expected = gt.expected_judgment_level
        actual = mr.judgment_level or ""
        confidence = mr.confidence or "Unknown"
        is_match = expected == actual

        if is_match:
            matched += 1
        else:
            mismatches.append(
                MismatchDetail(
                    requirement_id=str(fr.id),
                    function_name=fr.function_name,
                    expected=expected,
                    actual=actual,
                    confidence=confidence,
                    confidence_score=mr.confidence_score or 0.0,
                    scope_item_analysis=mr.scope_item_analysis or mr.rationale or "",
                    gap_analysis=mr.gap_analysis or "",
                    judgment_reason=mr.judgment_reason or "",
                )
            )

        by_confidence[confidence].append(is_match)
        confusion[expected][actual] += 1

    # 確信度別精度
    acc_by_conf = {}
    for conf, matches in by_confidence.items():
        acc_by_conf[conf] = sum(matches) / len(matches) if matches else 0.0

    return AccuracyMetrics(
        total_pairs=total,
        matched_count=matched,
        overall_accuracy=matched / total if total > 0 else 0.0,
        accuracy_by_confidence=acc_by_conf,
        accuracy_by_judgment={k: dict(v) for k, v in confusion.items()},
        mismatch_details=mismatches,
    )


async def run_evaluation(case_id: str, gt_path: Path) -> AccuracyReport:
    """評価を実行。"""
    ground_truth = load_ground_truth(gt_path)
    print(f"正解データ: {len(ground_truth)} 件")

    settings = get_settings()
    session_factory = create_session_factory(settings)

    async with session_factory() as session:
        stmt = (
            select(FunctionalRequirement, MappingResult)
            .join(
                MappingResult,
                MappingResult.functional_requirement_id == FunctionalRequirement.id,
            )
            .where(FunctionalRequirement.case_id == case_id)
            .where(MappingResult.status == "completed")
        )
        result = await session.execute(stmt)
        db_results = list(result.all())

    print(f"システム結果: {len(db_results)} 件 (completed)")

    pairs = match_results(ground_truth, db_results)
    print(f"突合成功: {len(pairs)} 件")

    metrics = calculate_metrics(pairs)

    report = AccuracyReport(
        case_id=case_id,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        metrics=metrics,
        is_passed=metrics.overall_accuracy >= 0.70,
    )

    return report


def print_report(report: AccuracyReport) -> None:
    """レポートをコンソール出力。"""
    m = report.metrics
    print("\n" + "=" * 60)
    print(f"精度評価レポート — Case: {report.case_id}")
    print(f"評価日時: {report.evaluated_at}")
    print("=" * 60)
    print(f"突合件数: {m.total_pairs}")
    print(f"一致件数: {m.matched_count}")
    print(f"全体精度: {m.overall_accuracy:.1%}")
    print(f"合否判定: {'PASS' if report.is_passed else 'FAIL'} (閾値: {report.pass_threshold:.0%})")

    print("\n確信度別精度:")
    for conf, acc in sorted(m.accuracy_by_confidence.items()):
        print(f"  {conf}: {acc:.1%}")

    print("\nConfusion Matrix (expected → actual):")
    for expected, actuals in sorted(m.accuracy_by_judgment.items()):
        for actual, count in sorted(actuals.items()):
            print(f"  {expected} → {actual}: {count}")

    if m.mismatch_details:
        print(f"\n不一致件 ({len(m.mismatch_details)} 件):")
        for mm in m.mismatch_details[:10]:
            reason = mm.judgment_reason or mm.scope_item_analysis or ""
            print(f"  [{mm.confidence}] {mm.function_name}: {mm.expected} → {mm.actual} | {reason[:60]}")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="精度評価スクリプト")
    parser.add_argument("--case-id", required=True, help="案件UUID")
    parser.add_argument("--ground-truth", required=True, help="正解データ Excel パス")
    parser.add_argument("--output", help="JSON 出力パス")
    args = parser.parse_args()

    report = asyncio.run(run_evaluation(args.case_id, Path(args.ground_truth)))
    print_report(report)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON出力: {output_path}")


if __name__ == "__main__":
    main()
