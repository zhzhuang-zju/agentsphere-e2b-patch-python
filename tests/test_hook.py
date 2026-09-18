from types import SimpleNamespace

from agentsphere_e2b_patch._hook import (
    TRAFFIC_HEADER,
    _EXTRA_ATTR,
    _FLAG,
    _call_with_extensions,
    _wrap_create_request_model,
    _patch_template_class,
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


def test_template_build_serializes_agencies():
    class TemplateBase:
        def _serialize(self, steps):
            return {"steps": steps, "force": False}

    class Template:
        def __init__(self, template):
            self._template = template

        @classmethod
        def build(cls, template, **kwargs):
            return template._template._serialize([])

        @classmethod
        def build_in_background(cls, template, **kwargs):
            return template._template._serialize([])

    _patch_template_class("e2b.template.main", TemplateBase)
    _patch_template_class("e2b.template_sync.main", Template)
    try:
        template = Template(TemplateBase())
        assert Template.build(template, agencies={"runtimeAgency": "agency"}) == {
            "steps": [],
            "force": False,
            "agencies": {"runtimeAgency": "agency"},
        }
        assert not hasattr(template._template, "_agentsphere_build_extensions")
    finally:
        uninstall()


def test_template_build_serializes_all_extensions():
    class TemplateBase:
        def _serialize(self, steps):
            return {"steps": steps, "force": False}

    class Template:
        @classmethod
        def build(cls, template, **kwargs):
            assert kwargs == {"name": "template"}
            return template._serialize([])

    _patch_template_class("e2b.template.main", TemplateBase)
    _patch_template_class("e2b.template_sync.main", Template)
    try:
        result = Template.build(
            TemplateBase(),
            name="template",
            arch="arm64",
            gateway_id="gateway",
            outbound_network={"isPrivateConnect": True},
            invoke={"protocol": "http", "port": 8080},
            agencies={"runtimeAgency": "agency"},
            ping={"enabled": True},
            observability={"logs": {"enableStdLogs": True}},
            session_storage_config={"mountDir": "/mnt/session"},
            storage_config={"obsMounts": [{"bucket": "bucket"}]},
        )
        assert result == {
            "steps": [],
            "force": False,
            "outboundNetwork": {"isPrivateConnect": True},
            "invoke": {"protocol": "http", "port": 8080},
            "agencies": {"runtimeAgency": "agency"},
            "ping": {"enabled": True},
            "observability": {"logs": {"enableStdLogs": True}},
            "sessionStorageConfig": {"mountDir": "/mnt/session"},
            "storageConfig": {"obsMounts": [{"bucket": "bucket"}]},
        }
    finally:
        uninstall()


def test_template_build_without_agencies_is_unchanged():
    class TemplateBase:
        def _serialize(self, steps):
            return {"steps": steps, "force": False}

    class Template:
        @classmethod
        def build(cls, template, **kwargs):
            return template._serialize([])

    _patch_template_class("e2b.template.main", TemplateBase)
    _patch_template_class("e2b.template_sync.main", Template)
    try:
        assert Template.build(TemplateBase()) == {"steps": [], "force": False}
    finally:
        uninstall()


def test_template_build_request_serializes_create_extensions():
    class TemplateBuildRequest:
        def __init__(self, **kwargs):
            self.alias = kwargs.get("alias")
            self.additional_properties = {}

        def to_dict(self):
            result = dict(self.additional_properties)
            if self.alias is not None:
                result["alias"] = self.alias
            return result

    _wrap_create_request_model(TemplateBuildRequest)
    try:
        result = _call_with_extensions(
            object(),
            {},
            {"alias": "my-alias", "arch": "arm64", "gateway_id": "gateway"},
            lambda: TemplateBuildRequest(),
        )
        assert result.to_dict() == {
            "alias": "my-alias",
            "arch": "arm64",
            "gatewayID": "gateway",
        }
    finally:
        uninstall()
