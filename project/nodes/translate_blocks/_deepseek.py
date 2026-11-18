"""DeepSeek Chat Completions adapter for JSON responses."""

import json
from urllib.parse import urlsplit

import httpx

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
CHAT_URL = "https://api.deepseek.com/chat/completions"


def chat_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise DeepSeekError("DEEPSEEK_BASE_URL 必须是无凭据、无查询参数的 HTTPS 接口地址。")
    return base if parsed.path.endswith("/chat/completions") else base + "/chat/completions"


class DeepSeekError(RuntimeError):
    """An API or response-format error safe to show to an operator."""


def generate_json(
    client: httpx.Client,
    system_prompt: str,
    payload: dict,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
) -> dict:
    if not api_key.strip():
        raise DeepSeekError("请在本地 .env 中配置 DEEPSEEK_API_KEY。")
    url = chat_url(base_url)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
    }
    # Provider-specific parameters are not part of the generic compatible API.
    if urlsplit(url).hostname == "api.deepseek.com":
        body["thinking"] = {"type": "disabled"}
    try:
        response = client.post(
            url,
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            json=body,
        )
    except httpx.RequestError:
        raise DeepSeekError("无法连接 DeepSeek API，请检查网络并重试。") from None

    if response.is_error:
        hints = {
            401: "请检查密钥是否有效。",
            402: "请检查 API 账户余额。",
            403: "服务拒绝访问，请检查密钥权限、模型授权或网关的访问限制。",
            429: "请求过于频繁，请稍后重试。",
        }
        hint = hints.get(response.status_code, "请检查服务状态和模型配置。")
        raise DeepSeekError(f"DeepSeek API 返回 HTTP {response.status_code}。{hint}")

    try:
        choice = response.json()["choices"][0]
        if choice["finish_reason"] == "length":
            raise DeepSeekError("模型服务端报告输出被截断（finish_reason=length）；本程序未设置输出 token 上限。请检查服务端默认限制，或缩小单次请求批次。")
        result = json.loads(choice["message"]["content"])
    except (ValueError, TypeError, KeyError, IndexError):
        raise DeepSeekError("DeepSeek 返回了空白或无效的 JSON，请重试。") from None
    if not isinstance(result, dict):
        raise DeepSeekError("DeepSeek 响应必须是一个 JSON 对象。")
    return result
