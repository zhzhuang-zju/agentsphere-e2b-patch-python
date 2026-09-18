"""Install-time hook that injects the E2B traffic access token into envd requests."""

from __future__ import annotations

import functools
import importlib
import logging
import sys
from contextvars import ContextVar
from collections.abc import Mapping
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

TRAFFIC_HEADER = "e2b-traffic-access-token"
_FLAG = "_agentsphere_e2b_patched"
_EXTRA_ATTR = "_ConnectionConfig__extra_sandbox_headers"
_EXTENSIONS_ATTR = "_agentsphere_build_extensions"
_CREATE_EXTENSIONS = "_agentsphere_create_extensions"

_logger = logging.getLogger(__name__)

# Class objects we have wrapped, mapped to the original ``__init__``.
_originals: Dict[int, Tuple[type, Callable[..., None]]] = {}
_template_originals: Dict[int, Tuple[type, str, Any]] = {}

# Modules whose Sandbox / AsyncSandbox we wrap as soon as they appear.
_WATCHED = {
    "e2b.sandbox_sync.main": "Sandbox",
    "e2b.sandbox_async.main": "AsyncSandbox",
}

_TEMPLATE_MODULES = {
    "e2b.template.main": "TemplateBase",
    "e2b.template_sync.main": "Template",
    "e2b.template_async.main": "AsyncTemplate",
}
_BUILD_MODEL_MODULE = "e2b.api.client.models.template_build_request_v3"
_WATCHED_MODULES = {
    **_WATCHED,
    **_TEMPLATE_MODULES,
    _BUILD_MODEL_MODULE: "TemplateBuildRequestV3",
}
_BUILD_EXTENSIONS = {
    "outbound_network": "outboundNetwork",
    "invoke": "invoke",
    "agencies": "agencies",
    "ping": "ping",
    "observability": "observability",
    "session_storage_config": "sessionStorageConfig",
    "storage_config": "storageConfig",
}
_CREATE_BUILD_EXTENSIONS = {
    "arch": "arch",
    "gateway_id": "gatewayID",
}
_create_extensions: ContextVar[Dict[str, Any]] = ContextVar(
    _CREATE_EXTENSIONS, default={}
)


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


def _wrap_template_serialize(cls: type) -> None:
    original = cls._serialize
    if getattr(original, _FLAG, False):
        return

    @functools.wraps(original)
    def _serialize(self, *args, **kwargs):
        serialized = original(self, *args, **kwargs)
        extensions = getattr(self, _EXTENSIONS_ATTR, None)
        if extensions is not None:
            for field_name, value in extensions.items():
                if not isinstance(value, Mapping):
                    raise TypeError(f"{field_name} must be a mapping")
                serialized[_BUILD_EXTENSIONS[field_name]] = dict(value)
        return serialized

    setattr(_serialize, _FLAG, True)
    _template_originals[id(cls)] = (cls, "_serialize", original)
    cls._serialize = _serialize


def _wrap_create_request_model(cls: type) -> None:
    original = cls.__init__
    if getattr(original, _FLAG, False):
        return

    @functools.wraps(original)
    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        extensions = _create_extensions.get()
        if not extensions:
            return
        if "alias" in extensions:
            if hasattr(self, "alias"):
                self.alias = extensions["alias"]
            else:
                self.additional_properties["alias"] = extensions["alias"]
        for field_name, value in extensions.items():
            if field_name == "alias":
                continue
            self.additional_properties[_CREATE_BUILD_EXTENSIONS[field_name]] = value

    setattr(__init__, _FLAG, True)
    _template_originals[id(cls)] = (cls, "__init__", original)
    cls.__init__ = __init__


def _call_with_extensions(
    template: Any,
    extensions: Dict[str, Any],
    create_extensions: Dict[str, Any],
    callback: Callable[[], Any],
) -> Any:
    if not extensions and not create_extensions:
        return callback()
    template_impl = getattr(template, "_template", template) if extensions else None
    had_previous = template_impl is not None and hasattr(template_impl, _EXTENSIONS_ATTR)
    previous = getattr(template_impl, _EXTENSIONS_ATTR, None)
    if template_impl is not None:
        setattr(template_impl, _EXTENSIONS_ATTR, extensions)
    token = _create_extensions.set(create_extensions)
    try:
        return callback()
    finally:
        _create_extensions.reset(token)
        if template_impl is not None:
            if had_previous:
                setattr(template_impl, _EXTENSIONS_ATTR, previous)
            else:
                delattr(template_impl, _EXTENSIONS_ATTR)


def _wrap_template_build(cls: type, name: str) -> None:
    descriptor = cls.__dict__.get(name)
    if not isinstance(descriptor, classmethod):
        return
    original = descriptor.__func__
    if getattr(original, _FLAG, False):
        return

    @functools.wraps(original)
    def build(owner, template, *args, **kwargs):
        extensions = {
            field_name: kwargs.pop(field_name)
            for field_name in _BUILD_EXTENSIONS
            if field_name in kwargs and kwargs[field_name] is not None
        }
        create_extensions = {}
        for field_name in _CREATE_BUILD_EXTENSIONS:
            if field_name in kwargs:
                value = kwargs.pop(field_name)
                if value is not None:
                    create_extensions[field_name] = value
        if kwargs.get("alias") is not None:
            create_extensions["alias"] = kwargs["alias"]
        return _call_with_extensions(
            template,
            extensions,
            create_extensions,
            lambda: original(owner, template, *args, **kwargs),
        )

    setattr(build, _FLAG, True)
    _template_originals[id(cls) ^ hash(name)] = (cls, name, descriptor)
    setattr(cls, name, classmethod(build))


def _patch_template_class(module_name: str, cls: type) -> None:
    if module_name == "e2b.template.main":
        _wrap_template_serialize(cls)
    else:
        _wrap_template_build(cls, "build")
        _wrap_template_build(cls, "build_in_background")


def _patch_loaded_model() -> None:
    module = sys.modules.get(_BUILD_MODEL_MODULE)
    if module is None:
        return
    cls = getattr(module, "TemplateBuildRequestV3", None)
    if isinstance(cls, type):
        _wrap_create_request_model(cls)


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


def _iter_template_classes() -> Iterable[Tuple[str, type]]:
    for modname, attr in _TEMPLATE_MODULES.items():
        try:
            module = importlib.import_module(modname)
            cls = getattr(module, attr)
        except (ImportError, AttributeError):
            continue
        if isinstance(cls, type):
            yield modname, cls


def _patch_loaded_modules() -> None:
    _patch_loaded_model()
    for modname, attr in _WATCHED.items():
        module = sys.modules.get(modname)
        if module is None:
            continue
        cls = getattr(module, attr, None)
        if isinstance(cls, type):
            _wrap_init(cls)
    for modname, attr in _TEMPLATE_MODULES.items():
        module = sys.modules.get(modname)
        if module is None:
            continue
        cls = getattr(module, attr, None)
        if isinstance(cls, type):
            _patch_template_class(modname, cls)


def _try_import_and_patch() -> bool:
    """Patch now if the official SDK is importable. Return whether anything was wrapped."""
    patched = False
    try:
        module = importlib.import_module(_BUILD_MODEL_MODULE)
        cls = getattr(module, "TemplateBuildRequestV3")
        _wrap_create_request_model(cls)
        patched = True
    except (ImportError, AttributeError):
        pass
    for cls in _iter_sandbox_classes():
        _wrap_init(cls)
        patched = True
    for modname, cls in _iter_template_classes():
        _patch_template_class(modname, cls)
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
        if fullname not in _WATCHED_MODULES or self._busy:
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
            attr = _WATCHED_MODULES[fullname]

            def _callback(
                module: Any, _attr: str = attr, _modname: str = fullname
            ) -> None:
                cls = getattr(module, _attr, None)
                if isinstance(cls, type):
                    if _modname in _WATCHED:
                        _wrap_init(cls)
                    elif _modname == _BUILD_MODEL_MODULE:
                        _wrap_create_request_model(cls)
                    else:
                        _patch_template_class(_modname, cls)

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
    for cls, name, original in list(_template_originals.values()):
        setattr(cls, name, original)
    _template_originals.clear()
    sys.meta_path[:] = [
        finder
        for finder in sys.meta_path
        if not isinstance(finder, _WhenImportedFinder)
    ]
