from types import SimpleNamespace

from agentsphere_e2b_patch._hook import (
    TRAFFIC_HEADER,
    _EXTRA_ATTR,
    _FLAG,
    _inject,
    _wrap_init,
    install,
    traffic_headers,
    uninstall,
)


def _config_with_extra(extra=None):
    config = SimpleNamespace()
    setattr(config, _EXTRA_ATTR, extra if extra is not None else {"E2b-Sandbox-Id": "sbx"})
    return config


def _dummy_sandbox_cls():
    class DummySandbox:
        def __init__(self, **opts):
            extra = getattr(opts["connection_config"], _EXTRA_ATTR)
            self.seen_headers = dict(extra)

    return DummySandbox


def test_inject_writes_traffic_header():
    extra = {"E2b-Sandbox-Id": "sbx"}
    config = _config_with_extra(extra)
    _inject({"traffic_access_token": "tok", "connection_config": config})
    assert extra[TRAFFIC_HEADER] == "tok"


def test_inject_skips_without_token():
    extra = {"E2b-Sandbox-Id": "sbx"}
    config = _config_with_extra(extra)
    _inject({"traffic_access_token": None, "connection_config": config})
    _inject({"connection_config": config})
    assert TRAFFIC_HEADER not in extra


def test_inject_skips_without_extra_attr():
    _inject(
        {
            "traffic_access_token": "tok",
            "connection_config": SimpleNamespace(),
        }
    )


def test_wrap_init_injects_before_constructor():
    cls = _dummy_sandbox_cls()
    _wrap_init(cls)
    try:
        extra = {"E2b-Sandbox-Id": "sbx", "E2b-Sandbox-Port": "49983"}
        config = _config_with_extra(extra)
        sandbox = cls(
            traffic_access_token="tok",
            connection_config=config,
        )
        assert extra[TRAFFIC_HEADER] == "tok"
        assert sandbox.seen_headers[TRAFFIC_HEADER] == "tok"
        assert getattr(cls.__init__, _FLAG)
    finally:
        uninstall()


def test_wrap_init_is_idempotent():
    cls = _dummy_sandbox_cls()
    _wrap_init(cls)
    wrapped = cls.__init__
    _wrap_init(cls)
    assert cls.__init__ is wrapped
    uninstall()


def test_uninstall_restores_original_init():
    cls = _dummy_sandbox_cls()
    original = cls.__init__
    _wrap_init(cls)
    assert cls.__init__ is not original
    uninstall()
    assert cls.__init__ is original


def test_traffic_headers():
    sandbox = SimpleNamespace(traffic_access_token="tok")
    assert traffic_headers(sandbox) == {TRAFFIC_HEADER: "tok"}
    assert traffic_headers(SimpleNamespace(traffic_access_token=None)) == {}
    assert traffic_headers(SimpleNamespace()) == {}


def test_install_without_e2b_does_not_raise():
    install()
