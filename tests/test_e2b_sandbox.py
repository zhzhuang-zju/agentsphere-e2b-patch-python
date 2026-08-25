"""Optional tests against an installed official ``e2b`` SDK."""

from unittest.mock import Mock

import pytest

pytest.importorskip("e2b")

from packaging.version import Version

from e2b.connection_config import ConnectionConfig
from e2b.sandbox_sync.main import Sandbox
import e2b.sandbox_sync.main as sandbox_sync_main

from agentsphere_e2b_patch import TRAFFIC_HEADER, install, uninstall
from agentsphere_e2b_patch._hook import _EXTRA_ATTR


def test_e2b_sandbox_init_snapshots_traffic_header(monkeypatch):
    """Token is in extra headers before envd clients are constructed."""
    install()
    monkeypatch.setattr(sandbox_sync_main, "Filesystem", lambda *a, **k: object())
    monkeypatch.setattr(sandbox_sync_main, "Commands", lambda *a, **k: object())
    monkeypatch.setattr(sandbox_sync_main, "Pty", lambda *a, **k: object())
    monkeypatch.setattr(sandbox_sync_main, "Git", lambda *a, **k: object())
    monkeypatch.setattr(sandbox_sync_main, "get_envd_api", lambda *a, **k: Mock())

    extra = {
        "E2b-Sandbox-Id": "sbx-test",
        "E2b-Sandbox-Port": str(ConnectionConfig.envd_port),
    }
    config = ConnectionConfig(
        api_key="e2b_test",
        extra_sandbox_headers=extra,
        debug=True,
    )
    try:
        sandbox = Sandbox(
            sandbox_id="sbx-test",
            sandbox_domain="e2b.app",
            envd_version=Version("0.2.4"),
            envd_access_token="envd-tok",
            traffic_access_token="traffic-tok",
            connection_config=config,
        )
        assert extra[TRAFFIC_HEADER] == "traffic-tok"
        assert sandbox.connection_config.sandbox_headers[TRAFFIC_HEADER] == "traffic-tok"
        assert sandbox.traffic_access_token == "traffic-tok"
    finally:
        uninstall()
        install()
