import json

import httpx
import pytest
from nodes.translate_blocks import _text_model
from nodes.translate_blocks._deepseek import DeepSeekError, chat_url, generate_json


@pytest.mark.parametrize(
    "base",
    [
        "https://gateway.example.org/v1",
        "https://gateway.example.org/v1/",
        "https://gateway.example.org/v1/chat/completions",
    ],
)
def test_translation_uses_configured_gateway_without_official_request(monkeypatch, base):
    monkeypatch.setattr(_text_model, "load_dotenv", lambda *args: None)
    monkeypatch.setenv("DEEPSEEK_TRANSPORT", "api")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", base)
    monkeypatch.setenv("DEEPSEEK_MODEL", "school-provided-model")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-real")
    calls = []

    def respond(request):
        assert str(request.url) == "https://gateway.example.org/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key-not-real"
        body = json.loads(request.content)
        assert body["model"] == "school-provided-model"
        assert "thinking" not in body
        assert not {'max_tokens', 'max_completion_tokens', 'max_output_tokens'} & body.keys()
        calls.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": '{"items": []}'}}]},
        )

    client_class = httpx.Client
    monkeypatch.setattr(
        _text_model.httpx,
        "Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs),
    )
    assert _text_model.request_json(instruction="Test", payload={}) == {"items": []}
    assert len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://gateway.example.org/v1",
        "https://user:secret@gateway.example.org/v1",
        "https://gateway.example.org/v1?token=secret",
    ],
)
def test_invalid_gateway_does_not_echo_credentials(url):
    with pytest.raises(DeepSeekError) as error:
        chat_url(url)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize('base', ['https://api.deepseek.com', 'https://gateway.example.org/v1'])
def test_large_response_has_no_client_output_token_cap(base):
    expected={'items':[{'segment_id':str(i),'zh_subtitle':'这是完整保留的中文测试译文'} for i in range(500)]}
    def respond(request):
        body=json.loads(request.content)
        assert not {'max_tokens','max_completion_tokens','max_output_tokens','max_new_tokens'} & body.keys()
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(expected)}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert generate_json(client,'test',{},api_key='fake-key',base_url=base)==expected


def test_server_length_limit_is_still_reported_not_accepted_as_complete():
    def respond(request):
        return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{"items":[]}'}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(DeepSeekError,match='服务端'):
            generate_json(client,'test',{},api_key='fake-key')
