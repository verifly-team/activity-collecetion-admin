#!/usr/bin/env python3
"""GitHub Actions workflow 静态检查 —— 抓那些 push 后才会暴露的引用错误。

检查项：
  1. job 内引用 needs.<自己>       → 永远取到空值（本次踩的坑）
  2. 引用 needs.X 但 X 不在 needs 里 → 取到空值
  3. 引用 steps.X.outputs 但同 job 没有 id: X
  4. 引用了未声明的 secrets（仅提示，因为 secrets 不在仓库里）

用法：python3 deploy/ci-lint.py [.github/workflows/ci-cd.yml]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("需要 pyyaml：pip install pyyaml")
    sys.exit(2)

NEEDS_SELF = re.compile(r"needs\.([A-Za-z0-9_-]+)\.outputs")
STEPS_OUT = re.compile(r"steps\.([A-Za-z0-9_-]+)\.outputs")
SECRET = re.compile(r"secrets\.([A-Za-z0-9_]+)")


def walk_strings(node):
    """递归取出所有字符串（含 dict key/value、list 项）。"""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from walk_strings(k)
            yield from walk_strings(v)
    elif isinstance(node, list):
        for item in node:
            yield from walk_strings(item)


def main(path: str) -> int:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    jobs = doc.get("jobs") or {}
    errors: list[str] = []
    warnings: list[str] = []

    all_secrets: set[str] = set()

    for job_name, job in jobs.items():
        needs = job.get("needs") or []
        needs = [needs] if isinstance(needs, str) else list(needs)
        steps = job.get("steps") or []
        step_ids = {s.get("id") for s in steps if isinstance(s, dict) and s.get("id")}

        for text in walk_strings(job):
            # ① 引用自己的 outputs
            for ref in NEEDS_SELF.findall(text):
                if ref == job_name:
                    errors.append(
                        f"[{job_name}] 引用了 needs.{ref}.outputs —— "
                        f"job 不能引用自己的 needs，取到的是空值；"
                        f"应改用 steps.<id>.outputs"
                    )
                elif ref not in needs:
                    errors.append(
                        f"[{job_name}] 引用 needs.{ref}.outputs，"
                        f"但 needs 里只有 {needs or '（空）'}"
                    )

            # ② 引用同 job 里不存在的 step id
            for ref in STEPS_OUT.findall(text):
                if ref not in step_ids:
                    errors.append(
                        f"[{job_name}] 引用 steps.{ref}.outputs，"
                        f"但该 job 没有 id: {ref}（现有：{sorted(step_ids) or '无'}）"
                    )

            all_secrets.update(SECRET.findall(text))

    for s in sorted(all_secrets):
        warnings.append(f"依赖 Secret：{s}（需在仓库 Settings → Secrets 里配好）")

    for w in warnings:
        print(f"  · {w}")

    if errors:
        print()
        for e in errors:
            print(f"  ❌ {e}")
        print(f"\n共 {len(errors)} 个错误")
        return 1

    print("  ✅ workflow 引用检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ".github/workflows/ci-cd.yml"))
