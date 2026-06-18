"""
audit_ml_data_integrity.py

ML V1.16 Data Integrity Audit Layer.

Read-only script. Does not modify any data.

Usage:
    python -m app.scripts.audit_ml_data_integrity

Exit codes:
    0  = All hard checks passed
    1  = One or more hard checks failed
"""

import json
import os
import sys
import textwrap
from datetime import datetime, timezone

from app.ml_data_integrity import (
    DEFAULT_EXPORTS_DIR,
    DEFAULT_MAIN_DB,
    DEFAULT_SHADOW_DB,
    run_all_checks,
)


REPORT_JSON_PATH = os.path.join(DEFAULT_EXPORTS_DIR, "ml_data_integrity_report.json")
REPORT_TXT_PATH = os.path.join(DEFAULT_EXPORTS_DIR, "ml_data_integrity_report.txt")


def build_report(overall: str, checks, generated_at: str) -> dict:
    return {
        "generated_at": generated_at,
        "overall_status": overall,
        "checks": [c.as_dict() for c in checks],
    }


def format_txt_report(report: dict) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("ML V1.16 DATA INTEGRITY AUDIT REPORT")
    lines.append("=" * 70)
    lines.append(f"Generated at : {report['generated_at']}")
    lines.append(f"Overall      : {report['overall_status']}")
    lines.append("")

    for chk in report["checks"]:
        status_tag = "[PASS]" if chk["status"] == "PASS" else "[FAIL]"
        lines.append(f"  {status_tag}  {chk['name']}")
        if chk.get("detail"):
            lines.append(f"         {chk['detail']}")
        for err in chk.get("errors", []):
            lines.append(f"         ERROR: {err}")

    lines.append("")
    lines.append("=" * 70)
    if report["overall_status"] == "PASS":
        lines.append("RESULT: ALL CHECKS PASSED")
    else:
        fail_names = [c["name"] for c in report["checks"] if c["status"] == "FAIL"]
        lines.append(f"RESULT: FAILED CHECKS: {', '.join(fail_names)}")
    lines.append("=" * 70)
    return "\n".join(lines)


def run_audit(
    main_db: str = DEFAULT_MAIN_DB,
    shadow_db: str = DEFAULT_SHADOW_DB,
    exports_dir: str = DEFAULT_EXPORTS_DIR,
    report_json_path: str = REPORT_JSON_PATH,
    report_txt_path: str = REPORT_TXT_PATH,
    feature_sample_limit: int = 5000,
) -> int:
    """
    Run all integrity checks, write reports, and return exit code (0=PASS, 1=FAIL).
    """
    generated_at = datetime.now(timezone.utc).isoformat()

    print("ML V1.16 DATA INTEGRITY AUDIT")
    print(f"Main DB     : {main_db}")
    print(f"Shadow DB   : {shadow_db}")
    print(f"Exports dir : {exports_dir}")
    print("")

    overall, checks = run_all_checks(
        main_db=main_db,
        shadow_db=shadow_db,
        exports_dir=exports_dir,
        feature_sample_limit=feature_sample_limit,
    )

    for chk in checks:
        tag = "PASS" if chk.status == "PASS" else "FAIL"
        print(f"  [{tag}] {chk.name}")
        if chk.detail:
            print(f"        {chk.detail}")
        for err in chk.errors:
            print(f"        ERROR: {err}")

    report = build_report(overall, checks, generated_at)

    os.makedirs(os.path.dirname(report_json_path), exist_ok=True)
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    txt = format_txt_report(report)
    with open(report_txt_path, "w", encoding="utf-8") as f:
        f.write(txt)

    print("")
    print(txt)
    print(f"JSON report : {report_json_path}")
    print(f"Text report : {report_txt_path}")

    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(run_audit())
