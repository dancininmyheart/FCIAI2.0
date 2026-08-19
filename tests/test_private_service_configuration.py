import asyncio

import pytest

from app.function import translate_deepseek_async, translate_gpt4o_async
from app.function.pynuo_fuc import api_translate_uno
from app.services.authing_provider import AuthingOAuth2Provider
from app.services.sso_service import SSOError


@pytest.mark.parametrize(
    ("translation_module", "setting_name"),
    (
        (translate_gpt4o_async, "GPT4O_TRANSLATION_API_URL"),
        (translate_deepseek_async, "DEEPSEEK_TRANSLATION_API_URL"),
    ),
)
def test_legacy_async_proxies_fail_closed_without_configuration(
    monkeypatch,
    translation_module,
    setting_name,
) -> None:
    monkeypatch.delenv(setting_name, raising=False)

    def unexpected_request(*args, **kwargs):
        raise AssertionError("an unconfigured proxy must not make an HTTP request")

    monkeypatch.setattr(translation_module.requests, "post", unexpected_request)

    with pytest.raises(RuntimeError, match=setting_name):
        asyncio.run(
            translation_module.Translate_texts(
                "general",
                "Hello",
                [],
                {},
                "English",
                "Chinese",
            )
        )


def test_uno_legacy_proxy_uses_only_the_configured_full_url(monkeypatch) -> None:
    configured_url = "https://translation.example.test/run"
    monkeypatch.setenv("GPT4O_TRANSLATION_API_URL", configured_url)
    calls = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "code": 200,
                "data": {"translated_json": '[{"target_language":"你好"}]'},
            }

    def record_request(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(api_translate_uno.requests, "post", record_request)

    result = api_translate_uno.call_backend_translate_ppt_page(
        "Hello",
        "gpt4o",
        "general",
        "",
        "",
        "English",
        "Chinese",
    )

    assert calls[0][0] == configured_url
    assert "你好" in result


def test_uno_legacy_proxy_fails_before_http_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_TRANSLATION_API_URL", raising=False)

    def unexpected_request(*args, **kwargs):
        raise AssertionError("an unconfigured proxy must not make an HTTP request")

    monkeypatch.setattr(api_translate_uno.requests, "post", unexpected_request)

    with pytest.raises(RuntimeError, match="DEEPSEEK_TRANSLATION_API_URL"):
        api_translate_uno.call_backend_translate_ppt_page(
            "Hello",
            "deepseek",
            "general",
            "",
            "",
            "English",
            "Chinese",
        )


def test_authing_endpoints_derive_only_from_configured_tenant(monkeypatch) -> None:
    monkeypatch.delenv("AUTHING_APP_HOST", raising=False)
    provider = AuthingOAuth2Provider(
        {
            "client_id": "demo-client",
            "client_secret": "demo-secret",
            "app_host": "https://identity.example.test/",
            "redirect_uri": "http://localhost/auth/sso/callback",
        }
    )

    assert provider.auth_url == "https://identity.example.test/oidc/auth"
    assert provider.token_url == "https://identity.example.test/oidc/token"
    assert provider.userinfo_url == "https://identity.example.test/oidc/me"


def test_authing_token_exchange_fails_closed_without_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("AUTHING_APP_HOST", raising=False)
    provider = AuthingOAuth2Provider(
        {
            "client_id": "demo-client",
            "client_secret": "demo-secret",
            "redirect_uri": "http://localhost/auth/sso/callback",
        }
    )

    def unexpected_request(*args, **kwargs):
        raise AssertionError("unconfigured SSO must not make an HTTP request")

    monkeypatch.setattr("app.services.authing_provider.requests.post", unexpected_request)

    with pytest.raises(SSOError, match="OAUTH2_TOKEN_URL"):
        provider._exchange_code_for_token("demo-code")
