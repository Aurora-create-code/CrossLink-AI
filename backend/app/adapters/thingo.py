"""Provider-neutral boundary. No endpoint, model or protocol is inferred."""
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from app.config import Settings


@dataclass(frozen=True)
class ModelRequest:
    instruction: str
    context: str
    max_tokens: int = 1600


@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider_request_id: str | None = None
    usage: dict | None = None
    model: str | None = None
    finish_reason: str | None = None


class ModelGateway(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse: ...


class ThingoNotReady(RuntimeError):
    pass


class ThingoCallError(RuntimeError):
    def __init__(self, message: str, metadata: dict | None = None):
        super().__init__(message)
        self.metadata = metadata or {}


class ThingoAdapter:
    """Verified intlapi request shape with strict local response checks.

    No platform strict JSON Schema or broader protocol compatibility is implied.
    """
    def __init__(self, settings: Settings, transport=None):
        self._settings = settings
        self._transport = transport
        self._verified = False

    def _supported(self):
        return (self._settings.thingo_endpoint == 'https://intlapi.thingo.com.cn/v1/chat/completions'
                and self._settings.thingo_model == 'gpt-6.1-sol'
                and self._settings.thingo_protocol == 'thingo_intl_chat_completions_v1')

    def configuration_status(self) -> dict:
        fields = {
            'THINGO_API_ENDPOINT': self._settings.thingo_endpoint,
            'THINGO_MODEL': self._settings.thingo_model,
            'THINGO_API_KEY': self._settings.thingo_api_key,
            'THINGO_PROTOCOL': self._settings.thingo_protocol,
        }
        missing = [key for key, value in fields.items() if not value]
        invalid: list[str] = []
        endpoint = self._settings.thingo_endpoint
        if endpoint:
            try:
                parsed = urlsplit(endpoint)
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                    invalid.append('THINGO_API_ENDPOINT')
            except ValueError:
                invalid.append('THINGO_API_ENDPOINT')
        status = 'not_configured' if len(missing) == len(fields) else (
            'incomplete' if missing or invalid else 'configured_unverified'
        )
        return {
            'configuration_status': status,
            'missing_fields': missing,
            'invalid_fields': invalid,
            'connectivity_verified': self._verified,
            'protocol_implemented': self._supported(),
        }

    async def generate(self, request: ModelRequest) -> ModelResponse:
        if not self._supported() or not self._settings.thingo_api_key:
            raise ThingoNotReady('Thingo配置缺失或不是当前已核实的国际站协议。')
        key = self._settings.thingo_api_key
        metadata = {}
        try:
            transport = self._transport or httpx.AsyncHTTPTransport(retries=0)
            async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(90, connect=15), trust_env=False, follow_redirects=False) as client:
                response = await client.post(self._settings.thingo_endpoint,
                    headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                    json={'model': self._settings.thingo_model, 'messages': [{'role':'user','content':request.instruction+'\nSOURCE TEXT:\n'+request.context}], 'max_tokens':min(max(request.max_tokens,1),3000), 'stream':False})
            metadata['http_status'] = response.status_code
            if response.status_code != 200:
                raise ThingoCallError(f'模型服务返回 HTTP {response.status_code}；未自动重试，错误正文未记录。', metadata)
            try:
                data = response.json()
            except ValueError:
                raise ThingoCallError('模型响应不是有效 JSON。',metadata) from None
            if not isinstance(data,dict):
                raise ThingoCallError('模型响应结构无效。',metadata)
            usage = data.get('usage',{})
            metadata['usage'] = {n:usage[n] for n in ('prompt_tokens','completion_tokens','total_tokens') if isinstance(usage,dict) and type(usage.get(n)) is int and usage[n]>=0}
            choices = data.get('choices')
            first = choices[0] if isinstance(choices,list) and choices and isinstance(choices[0],dict) else {}
            finish = first.get('finish_reason')
            metadata['finish_reason'] = finish if finish in ('stop','length','content_filter') else None
            if finish != 'stop':
                raise ThingoCallError('模型响应被截断、拒绝或结束状态未知，未保存知识点。',metadata)
            message = first.get('message')
            text = message.get('content') if isinstance(message,dict) else None
            if not isinstance(text,str) or not text.strip() or len(text)>30000:
                raise ThingoCallError('模型没有返回有效文字内容。',metadata)
            if key in text:
                raise ThingoCallError('响应包含敏感配置，已拒绝保存。',metadata)
            model = data.get('model')
            if model != self._settings.thingo_model:
                raise ThingoCallError('返回模型标识与请求不一致。',metadata)
            self._verified = True
            return ModelResponse(text=text,usage=metadata['usage'],model=model,finish_reason=finish)
        except ThingoCallError:
            raise
        except httpx.TimeoutException:
            raise ThingoCallError('模型调用超时；本次已记账，没有自动重试。',metadata) from None
        except Exception:
            raise ThingoCallError('模型网络或响应处理失败；敏感错误详情已隐藏，没有自动重试。',metadata) from None
