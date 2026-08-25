"""Install-time hook that injects the E2B traffic access token into envd requests."""

from __future__ import annotations

import functools
import importlib
import logging
import sys
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

TRAFFIC_HEADER = "e2b-traffic-access-token"
_FLAG = "_agentsphere_e2b_patched"
_EXTRA_ATTR = "_ConnectionConfig__extra_sandbox_headers"

_logger = logging.getLogger(__name__)

# Class objects we have wrapped, mapped to the original ``__init__``.
_originals: Dict[int, Tuple[type, Callable[..., None]]] = {}

# Modules whose Sandbox / AsyncSandbox we wrap as soon as they appear.
_WATCHED = {
    "e2b.sandbox_sync.main": "Sandbox",
    "e2b.sandbox_async.main": "AsyncSandbox",
}


def traffic_headers(sandbox: Any) -> Dict[str, str]:
    """Headers to send when calling a sandbox port yourself (not via the SDK).

    The official SDK never attaches the traffic access token to user-issued HTTP
    against ``sandbox.get_host(port)``. Use this for those requests::

        httpx.get(f"https://{sandbox.get_host(8080)}", headers=traffic_headers(sandbox))
    """
    token = getattr(sandbox, "traffic_access_token", None)
    if not token:
        return {}
    return {TRAFFIC_HEADER: token}


def _inject(opts: dict) -> None:
    token = opts.get("traffic_access_token")
    config = opts.get("connection_config")
    if not token or config is None:
        return
    extra = getattr(config, _EXTRA_ATTR, None)
    if not isinstance(extra, dict):
        _logger.debug(
            "connection_config has no %s; skipping traffic-access-token inject",
            _EXTRA_ATTR,
        )
        return
    extra[TRAFFIC_HEADER] = token


def _wrap_init(cls: type) -> None:
    original = cls.__init__
    if getattr(original, _FLAG, False):
        return

    @functools.wraps(original)
    def __init__(self, *args, **opts):  # noqa: N807 — must match the wrapped name
        if opts:
            _inject(opts)
        original(self, *args, **opts)

    setattr(__init__, _FLAG, True)
    _originals[id(cls)] = (cls, original)
    cls.__init__ = __init__


def _iter_sandbox_classes() -> Iterable[type]:
    seen: set[int] = set()
    for modname, attr in _WATCHED.items():
        try:
            module = importlib.import_module(modname)
            cls = getattr(module, attr)
        except (ImportError, AttributeError):
            continue
        if id(cls) not in seen:
            seen.add(id(cls))
            yield cls
    try:
        e2b = importlib.import_module("e2b")
    except ImportError:
        return
    for attr in ("Sandbox", "AsyncSandbox"):
        cls = getattr(e2b, attr, None)
        if cls is not None and id(cls) not in seen:
            seen.add(id(cls))
            yield cls


def _patch_loaded_modules() -> None:
    for modname, attr in _WATCHED.items():
        module = sys.modules.get(modname)
        if module is None:
            continue
        cls = getattr(module, attr, None)
        if isinstance(cls, type):
            _wrap_init(cls)


def _try_import_and_patch() -> bool:
    """Patch now if the official SDK is importable. Return whether anything was wrapped."""
    patched = False
    for cls in _iter_sandbox_classes():
        _wrap_init(cls)
        patched = True
    return patched


class _LoaderProxy:
    def __init__(self, loader: Any, callback: Callable[[Any], None]):
        self._loader = loader
        self._callback = callback

    def create_module(self, spec: Any) -> Optional[Any]:
        create = getattr(self._loader, "create_module", None)
        if create is not None:
            return create(spec)
        return None

    def exec_module(self, module: Any) -> None:
        self._loader.exec_module(module)
        self._callback(module)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._loader, name)


class _WhenImportedFinder:
    """Run wrap callbacks after watched E2B modules are first imported.

    Needed when this package is imported before ``e2b`` is installed or
    imported, including ``.pth`` load order.
    """

    def __init__(self) -> None:
        self._busy = False

    def find_spec(self, fullname, path, target=None):  # noqa: ANN001 — import-hook signature
        if fullname not in _WATCHED or self._busy:
            return None
        self._busy = True
        try:
            spec = None
            for finder in sys.meta_path:
                if finder is self:
                    continue
                find_spec = getattr(finder, "find_spec", None)
                if find_spec is None:
                    continue
                spec = find_spec(fullname, path, target)
                if spec is not None:
                    break
            if spec is None or spec.loader is None:
                return spec
            attr = _WATCHED[fullname]

            def _callback(module: Any, _attr: str = attr) -> None:
                cls = getattr(module, _attr, None)
                if isinstance(cls, type):
                    _wrap_init(cls)

            spec.loader = _LoaderProxy(spec.loader, _callback)
            return spec
        finally:
            self._busy = False


def _ensure_import_hook() -> None:
    if any(isinstance(finder, _WhenImportedFinder) for finder in sys.meta_path):
        return
    sys.meta_path.insert(0, _WhenImportedFinder())


def install() -> None:
    """Idempotently wrap E2B sandbox constructors (and watch for later imports)."""
    _patch_loaded_modules()
    try:
        _try_import_and_patch()
    except Exception:
        _logger.debug("could not import e2b to patch immediately", exc_info=True)
    _ensure_import_hook()


def uninstall() -> None:
    """Restore original ``__init__`` methods. Intended for tests."""
    for cls, original in list(_originals.values()):
        cls.__init__ = original
    _originals.clear()
    sys.meta_path[:] = [
        finder
        for finder in sys.meta_path
        if not isinstance(finder, _WhenImportedFinder)
    ]
