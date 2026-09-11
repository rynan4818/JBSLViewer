import httpx
import pytest

from mock_servers.score_manager.auth.real_provider import verify
from mock_servers.score_manager.config import Settings
from mock_servers.score_manager.errors import ApiProblem


def test_real_provider_requires_explicit_configuration():
    with pytest.raises(ApiProblem) as caught:
        verify("secret-ticket", "steamTicket", Settings(auth_mode="real-provider-test"), transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    assert caught.value.status == 503 and caught.value.code == "auth_provider_unavailable"


def test_steam_verifier_uses_appid_and_provider_identity():
    def handler(request):
        assert request.url.params["appid"] == "620980"
        assert request.url.params["key"] == "configured-key"
        assert request.url.params["ticket"] == "opaque-ticket"
        return httpx.Response(200, json={"response": {"params": {"result": "OK", "steamid": "76561198000000009"}}})
    settings = Settings(auth_mode="real-provider-test", steam_api_key="configured-key", steam_api_url="https://api.steampowered.com")
    identity = verify("opaque-ticket", "steamTicket", settings, transport=httpx.MockTransport(handler))
    assert identity.sid == "76561198000000009" and identity.provider == "steamTicket"


def test_oculus_verifier_uses_bearer_and_provider_identity():
    def handler(request):
        assert request.headers["authorization"] == "Bearer opaque-ticket"
        assert request.url.params["fields"] == "id,name"
        return httpx.Response(200, json={"id": "123456789", "name": "Oculus Player"})
    settings = Settings(auth_mode="real-provider-test", oculus_api_url="https://graph.oculus.com/me")
    identity = verify("opaque-ticket", "oculusTicket", settings, transport=httpx.MockTransport(handler))
    assert identity.sid == "123456789" and identity.display_name == "Oculus Player"


def test_provider_rejection_and_network_failure_are_distinct():
    settings = Settings(auth_mode="real-provider-test", steam_api_key="key", steam_api_url="https://api.steampowered.com")
    with pytest.raises(ApiProblem) as rejected:
        verify("bad", "steamTicket", settings, transport=httpx.MockTransport(lambda _: httpx.Response(401)))
    assert rejected.value.code == "invalid_ticket" and rejected.value.status == 401
    def unavailable(request): raise httpx.ConnectError("offline", request=request)
    with pytest.raises(ApiProblem) as failed:
        verify("unknown", "steamTicket", settings, transport=httpx.MockTransport(unavailable))
    assert failed.value.code == "auth_provider_unavailable" and failed.value.status == 503


def test_steam_response_requires_explicit_ok_result():
    settings = Settings(auth_mode="real-provider-test", steam_api_key="key", steam_api_url="https://api.steampowered.com")
    response = {"response": {"params": {"result": "Expired", "steamid": "76561198000000009"}}}
    with pytest.raises(ApiProblem) as rejected:
        verify("bad", "steamTicket", settings, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    assert rejected.value.code == "invalid_ticket" and rejected.value.status == 401
