"""Keep the process-level E2B constructor patch installed across tests."""

import pytest

from agentsphere_e2b_patch import install


@pytest.fixture(autouse=True)
def _reinstall_patch():
    yield
    install()
