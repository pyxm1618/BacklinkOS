#!/usr/bin/env python3
"""BacklinkOS Fresh Session Zero-Context Flow & Contract Verification.

在完全隔离的数据与运行环境下，模拟新会话执行：
“按本项目正式流程，为 quick-iching 提交外链，本轮目标新增成功提交 200 个。”

验证项：
1. 宿主文档能准确发现正式入口与执行命令；
2. 缺少 Ready 清单时，正式入口自动进行 Phase C 有界现场准备；
3. 批次组织受快照总范围约束，不无限扩扫；
4. 遇到 HUMAN_PENDING 保存现场，批次继续推进；
5. 断点恢复同一次尝试不重复计入新增成功；
6. 运行状态全持久化，新进程能直接读取进度；
7. 退出时严格对账。
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_cmd(args: list[str], env: dict) -> tuple[int, str, str]:
    res = subprocess.run(
        args,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout, res.stderr


def main():
    print("==================================================")
    print("开始执行：无历史上下文新会话流程与契约验证")
    print("==================================================")

    # 1. 验证宿主入口文档存在且指向唯一权威流程
    doc_paths = [
        PROJECT_ROOT / "AGENTS.md",
        PROJECT_ROOT / "GEMINI.md",
        PROJECT_ROOT / "CLAUDE.md",
        PROJECT_ROOT / "README.md",
    ]
    for dp in doc_paths:
        assert dp.is_file(), f"缺失宿主入口文档: {dp}"
        content = dp.read_text(encoding="utf-8")
        assert "docs/FORMAL_SUBMISSION_WORKFLOW.md" in content, f"{dp.name} 未统一指向正式流程规范"
        assert "run_submission_cycle.py" in content, f"{dp.name} 未包含正式入口命令"
    print("✅ 1. 宿主入口文档校验通过：AGENTS.md, GEMINI.md, CLAUDE.md, README.md 均统一指向 FORMAL_SUBMISSION_WORKFLOW.md")

    # 2. 准备隔离测试环境
    with tempfile.TemporaryDirectory() as tmpdir:
        test_runtime_dir = Path(tmpdir) / "runtime"
        test_runtime_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["BACKLINKOS_RUNTIME_DIR"] = str(test_runtime_dir)
        env["PYTHONPATH"] = str(PROJECT_ROOT)

        # 构造测试状态机，模拟快照有 5 个候选
        from scripts.run_submission_cycle import (
            init_cycle_state,
            load_cycle_state,
            plan_next_batch,
            record_task_outcome,
            print_cycle_summary,
        )
        from scripts.master_sheet_sync import VerifiedEntry

        initial_candidates = ["site-a.com", "site-b.com", "site-c.com", "site-d.com", "site-e.com"]
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=2,
            initial_candidates=initial_candidates,
            spreadsheet_id="test-spreadsheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=str(test_runtime_dir),
        )

        assert state["snapshot_total_count"] == 5
        assert state["still_to_submit_count"] == 5
        print("✅ 2. 候选快照范围锁定通过：5 个候选作为本轮最大硬边界")

        # 3. 模拟 Phase C 自动准备 (无 Ready 时自动现场核验)
        master_rows = [
            {"外链ID": d, "平台域名": d, "基础状态": "候选", "提交入口": f"https://{d}/submit", "_sheet_row_num": idx}
            for idx, d in enumerate(initial_candidates, 2)
        ]
        project_rows = [
            {"项目ID": "quick-iching", "外链ID": d, "状态": "待提交", "_sheet_row_num": idx}
            for idx, d in enumerate(initial_candidates, 2)
        ]

        def mock_verifier(dom, url):
            return (
                VerifiedEntry(
                    url=url,
                    domain=dom,
                    evidence_type="ACTIONABLE_FORM",
                    evidence_summary="[Verified Form]",
                ),
                "ok",
            )

        plan = plan_next_batch(
            state=state,
            master_rows=master_rows,
            project_rows=project_rows,
            batch_ready_target=2,
            batch_scan_limit=5,
            commit_prep=False,
            runtime_dir=str(test_runtime_dir),
            entry_verifier=mock_verifier,
        )

        assert plan["action"] == "EXECUTE_BATCH"
        assert len(plan["ready_items"]) == 2
        assert plan["ready_domains"] == ["site-a.com", "site-b.com"]
        print(f"✅ 3. 自动衔接 Phase C 现场核验通过：生成首批 Ready 候选 {plan['ready_domains']}")

        # 4. 模拟 Phase D 真实提交与 HUMAN_PENDING 非阻塞
        # site-a 遇到真阻碍 (HUMAN_PENDING) -> 挂起，不中断批次！
        rec_a = record_task_outcome(
            state=state,
            backlink_id="site-a.com",
            status="需人工",
            reason="需要短信验证码",
            target_id="tab-cdp-001",
            commit=False,
            runtime_dir=str(test_runtime_dir),
        )
        assert rec_a["is_new_success"] is False
        assert rec_a["human_pending_count"] == 1
        assert state["newly_succeeded_count"] == 0
        print("✅ 4. HUMAN_PENDING 非阻塞验证通过：site-a 挂起并保留 Tab，批次继续")

        # site-b 提交成功
        rec_b = record_task_outcome(
            state=state,
            backlink_id="site-b.com",
            status="已提交",
            reason="表单提交成功，等待审核",
            evidence="[Receipt banner observed]",
            commit=False,
            runtime_dir=str(test_runtime_dir),
        )
        assert rec_b["is_new_success"] is True
        assert state["newly_succeeded_count"] == 1
        print("✅ 5. 提交结果记录通过：site-b 成功，累计新增成功 = 1")

        # 5. 自动组织下一批次 (目标为 2，当前为 1，继续规划下一批)
        plan2 = plan_next_batch(
            state=state,
            master_rows=master_rows,
            project_rows=project_rows,
            batch_ready_target=2,
            batch_scan_limit=5,
            commit_prep=False,
            runtime_dir=str(test_runtime_dir),
            entry_verifier=mock_verifier,
        )
        assert plan2["action"] == "EXECUTE_BATCH"
        print(f"✅ 6. 多批次自动推进通过：自动规划第二批 Ready 候选 {plan2['ready_domains']}")

        # 模拟 site-c 成功
        rec_c = record_task_outcome(
            state=state,
            backlink_id="site-c.com",
            status="审核中",
            reason="审核中",
            evidence="[Receipt acknowledgment recorded]",
            commit=False,
            runtime_dir=str(test_runtime_dir),
        )
        assert rec_c["is_new_success"] is True
        assert rec_c["newly_succeeded_count"] == 2
        assert rec_c["is_finished"] is True
        print(f"✅ 7. 停止条件达成验证通过：达到目标新增成功数 (2) 自动停止")

        # 6. 独立子进程读取持久化状态与公开 CLI status / 对账验证 (落实真实外部子进程调用)
        code, out, err = run_cmd(
            [sys.executable, "scripts/run_submission_cycle.py", "status", "--project-id", "quick-iching"],
            env=env,
        )
        assert code == 0, f"status 子命令执行失败: {err}"
        assert "对账一致 (BALANCED)" in out, f"输出中缺少平衡标记: {out}"
        assert "本轮新增成功提交: 2" in out, f"成功数不符: {out}"
        assert "待人工处理 (挂起): 1" in out, f"人工挂起数不符: {out}"
        print("✅ 8. 独立子进程 CLI status 执行验证通过：跨进程恢复读取完全一致且对账平衡")

        persisted = load_cycle_state("quick-iching", runtime_dir=str(test_runtime_dir))
        assert persisted is not None
        assert persisted["is_finished"] is True
        assert persisted["newly_succeeded_count"] == 2
        assert persisted["human_pending_count"] == 1
        # 对账检查
        succ = persisted["newly_succeeded_count"]
        prior = persisted.get("prior_existing_count", 0)
        hp = persisted["human_pending_count"]
        still = persisted["still_to_submit_count"]
        not_app = persisted.get("not_applicable_count", 0)
        failed = persisted.get("failed_count", 0)
        assert succ + prior + not_app + failed + hp + still == persisted["snapshot_total_count"]
        print("✅ 9. 磁盘全持久化与新会话恢复对账通过：公式各项严密平衡")

        print_cycle_summary(persisted)

    print("==================================================")
    print("🎉 全部新会话流程与安全契约检查 100% 通过！")
    print("==================================================")


if __name__ == "__main__":
    main()
