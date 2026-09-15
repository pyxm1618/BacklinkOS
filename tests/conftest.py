import os
import shutil
import tempfile
import pytest

from scripts.master_sheet_sync import DaemonProbeExecutor

@pytest.fixture(autouse=True)
def isolate_test_runtime_environment(monkeypatch):
    """为每一个自动化测试自动提供完全隔离的临时 runtime 目录并重置执行器状态。"""
    tmp_runtime = tempfile.mkdtemp(prefix="backlinkos_test_isolated_runtime_")
    monkeypatch.setenv("BACKLINKOS_RUNTIME_DIR", tmp_runtime)

    # 重置执行器
    DaemonProbeExecutor._semaphore = None
    DaemonProbeExecutor._concurrency = 0
    DaemonProbeExecutor._active_probes_count = 0

    yield tmp_runtime

    DaemonProbeExecutor._semaphore = None
    DaemonProbeExecutor._concurrency = 0
    DaemonProbeExecutor._active_probes_count = 0
    shutil.rmtree(tmp_runtime, ignore_errors=True)
