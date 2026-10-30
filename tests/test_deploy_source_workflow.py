"""deploy-source.yml 里远端部署脚本的回归测试。

用假的 docker / curl 跑通四个分支，确保回滚逻辑不会被改坏。
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
WF = ROOT / ".github/workflows/deploy-source.yml"
WORK = pathlib.Path("/tmp/vf_dstest")

DOCKER_OK = """#!/usr/bin/env bash
case "$1" in
  build) echo "[fake] build ok"; exit 0 ;;
  rm) exit 0 ;;
  run) echo "[fake] run ok"; exit 0 ;;
  ps) echo "   Up 3 seconds (healthy)"; exit 0 ;;
  images) printf "latest\\n" ; exit 0 ;;
  logs) echo "[fake] logs"; exit 0 ;;
esac
exit 0
"""

DOCKER_BUILD_FAIL = """#!/usr/bin/env bash
if [ "$1" = "build" ]; then echo "[fake] build FAILED"; exit 1; fi
exit 0
"""


def _remote_blocks() -> list[str]:
    text = WF.read_text(encoding="utf-8")
    return re.findall(r"<<'REMOTE'\n(.*?)\n\s*REMOTE\n", text, re.S)


def _run_case(name, docker_stub, curl_exit, prev_tag, expect_code, keyword) -> bool:
    shutil.rmtree(WORK, ignore_errors=True)
    (WORK / "bin").mkdir(parents=True)
    (WORK / "app").mkdir()

    for cmd, body in (
        ("docker", docker_stub),
        ("curl", f"#!/usr/bin/env bash\nexit {curl_exit}\n"),
    ):
        f = WORK / "bin" / cmd
        f.write_text(body, encoding="utf-8")
        f.chmod(0o755)

    (WORK / "app" / "x.txt").write_text("hi", encoding="utf-8")
    subprocess.run(
        ["tar", "czf", str(WORK / "src.tar.gz"), "-C", str(WORK / "app"), "x.txt"],
        check=True,
    )
    if prev_tag:
        (WORK / ".last-image").write_text(prev_tag + "\n", encoding="utf-8")

    block = _remote_blocks()[-1]
    block = block.replace("/verifly/activity-export", str(WORK))
    block = block.replace("seq 1 30", "seq 1 2").replace("sleep 2", "sleep 0.1")

    script = WORK / "remote.sh"
    script.write_text("SHA_SHORT=abc1234\n" + block, encoding="utf-8")

    env = {**os.environ, "PATH": f"{WORK / 'bin'}:{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
    )
    out = r.stdout + r.stderr
    ok = r.returncode == expect_code and keyword in out
    print(f"{'✅' if ok else '❌'} {name}  code={r.returncode} 有「{keyword}」={keyword in out}")
    return ok


def test_remote_blocks_syntax():
    """远端 heredoc 里的 shell 必须语法正确。"""
    blocks = _remote_blocks()
    assert blocks, "没找到 REMOTE 块"
    for i, b in enumerate(blocks, 1):
        f = pathlib.Path(f"/tmp/vf_block_inline_{i}.sh")
        f.write_text("SHA_SHORT=abc1234\n" + b, encoding="utf-8")
        r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"块{i} 语法错误: {r.stderr[:300]}"


def test_deploy_scenarios():
    """正常部署 / 构建失败 / 健康检查失败回滚 / 无上一版。"""
    results = [
        _run_case("正常部署（无上一版）", DOCKER_OK, 0, "", 0, "部署成功"),
        _run_case("构建失败 → 线上不动", DOCKER_BUILD_FAIL, 0, "20260101-1", 1, "构建失败"),
        _run_case("健康检查失败 → 回滚", DOCKER_OK, 7, "20260101-1", 1, "回滚"),
        _run_case("健康检查失败且无上一版", DOCKER_OK, 7, "", 1, "人工处理"),
    ]
    shutil.rmtree(WORK, ignore_errors=True)
    assert all(results), f"通过 {sum(results)}/{len(results)}"
