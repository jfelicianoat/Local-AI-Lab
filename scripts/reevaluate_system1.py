"""Use the same evaluator over an existing report and immutable inputs."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from local_ai_lab.broker.client import BrokerTaskClient
from local_ai_lab.domain.common import canonical_json
from local_ai_lab.evaluation.cascade import SemanticEvaluationConfig
from local_ai_lab.evaluation.recalculate import recalculate_strategy_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "suite", "snapshot", "config", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--broker-endpoint", required=True)
    parser.add_argument("--gold-labels", type=Path)
    parser.add_argument("--compare", type=Path, help="Previous reevaluation of the same responses and configuration")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a new file")
    config = SemanticEvaluationConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
    result = recalculate_strategy_report(
        report_path=args.report, suite_root=args.suite, snapshot=args.snapshot,
        config=config, limit=args.limit,
        client=BrokerTaskClient(endpoint=args.broker_endpoint, token=os.environ.get("LOCAL_AI_LAB_BROKER_TOKEN"),
                                max_wait=config.strong_judge_timeout),
        gold_labels=json.loads(args.gold_labels.read_text(encoding="utf-8")) if args.gold_labels else None,
    )
    if args.compare:
        previous = json.loads(args.compare.read_text(encoding="utf-8"))
        for key in ("source_report_sha256", "evaluation_configuration_fingerprint", "case_ids"):
            if previous.get(key) != result[key]:
                parser.error("stability comparison requires identical responses, cases and configuration")
        pairs = [(a["evaluation"]["label"], b["evaluation"]["label"])
                 for a, b in zip(previous["results"], result["results"], strict=True)
                 if a["evaluation"]["label"] is not None and b["evaluation"]["label"] is not None]
        result["stability"] = {"compared": len(pairs), "agreement": sum(a == b for a, b in pairs) / len(pairs) if pairs else None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as target:
        target.write(canonical_json(result) + "\n")
    print(canonical_json(result["evaluation_metrics"]))


if __name__ == "__main__":
    main()
