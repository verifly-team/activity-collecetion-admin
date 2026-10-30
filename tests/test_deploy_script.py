"""用假的 docker / curl 验证 remote-deploy.sh 的各个分支。"""

import os
import pathlib
import shutil
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "deploy" / "remote-deploy.sh"
WORK = pathlib.Path("/tmp/vf_deploy_script_test")

DOCKER_STUB = """#!/usr/bin/env bash
case "$1" in
  pull) exit 0 ;;
  rm)   exit 0 ;;
  run)  if [ "{mode}" = "fail_start" ]; then exit 1; fi; exit 0 ;;
  logs) echo "fake container logs"; exit 0 ;;
  ps)   echo "fake ps"; exit 0 ;;
  *)    exit 0 ;;
esac
"""

CURL_STUB = """#!/usr/bin/env bash
if [ "{mode}" = "fail_health" ]; then exit 7; fi
exit 0
"""


def run_case(name, mode, prev, expect_code, expect_rollback):
    shutil.rmtree(WORK, ignore_errors=True)
    bin_dir = WORK / "bin"
    audit = WORK / "audit"
    uploads = WORK / "uploads"
    for d in (bin_dir, audit, uploads):
        d.mkdir(parents=True)

    for cmd, tpl in (("docker", DOCKER_STUB), ("curl", CURL_STUB)):
        f = bin_dir / cmd
        f.write_text(tpl.format(mode=mode), encoding="utf-8")
        f.chmod(0o755)

    (WORK / "export.env").write_text("EXPORT_TOKEN=x\n", encoding="utf-8")
    state = WORK / ".last-image"
    if prev:
        state.write_text(prev + "\n", encoding="utf-8")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ENV_FILE": str(WORK / "export.env"),
        "UPLOAD_DIR_HOST": str(uploads),
        "AUDIT_DIR_HOST": str(audit),
        "STATE_FILE": str(state),
        "LOG_FILE": str(WORK / "deploy.log"),
        "PORT": "9999",
        "HEALTH_TRIES": "2",
        "HEALTH_INTERVAL": "0.1",
    }
    r = subprocess.run(
        ["bash", str(SCRIPT), "registry.example/img:new"],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        errors="replace",
    )
    out = r.stdout + r.stderr
    rolled = "回滚到：" in out
    ok = (r.returncode == expect_code) and (rolled == expect_rollback)
    print(f"{'✅' if ok else '❌'} {name}")
    print(f"   退出码={r.returncode}（期望 {expect_code}）  回滚={rolled}（期望 {expect_rollback}）")
    for line in out.strip().splitlines()[-3:]:
        print("   |", line)
    print()
    return ok


def test_deploy_script_cases():
    results = [
        run_case("正常部署（无上一版）", "ok", "", 0, False),
        run_case("正常部署（有上一版）", "ok", "registry.example/img:old", 0, False),
        run_case("新容器启动失败 → 必须回滚", "fail_start", "registry.example/img:old", 1, True),
        run_case("健康检查失败 → 必须回滚", "fail_health", "registry.example/img:old", 1, True),
        run_case("健康检查失败且无上一版 → 报错不崩", "fail_health", "", 1, False),
    ]
    shutil.rmtree(WORK, ignore_errors=True)
    assert all(results), f"通过 {sum(results)}/{len(results)}"
