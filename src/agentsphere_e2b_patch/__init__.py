"""Patch the official E2B Python SDK to send ``e2b-traffic-access-token``.

Installing this package is enough: a ``.pth`` file imports it at interpreter
startup. Explicit ``import agentsphere_e2b_patch`` also works, including
editable installs where the ``.pth`` may not be placed in site-packages.

The hook wraps ``Sandbox.__init__`` / ``AsyncSandbox.__init__`` and writes the
create-response traffic access token into ``ConnectionConfig``'s extra sandbox
headers *before* envd HTTP/RPC clients are built (or, on older SDKs, before
they are lazily created on first use).
"""

from agentsphere_e2b_patch._hook import (
    TRAFFIC_HEADER,
    install,
    uninstall,
    traffic_headers,
)

install()

__all__ = [
    "TRAFFIC_HEADER",
    "install",
    "uninstall",
    "traffic_headers",
]
