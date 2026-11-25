"""统一 Chat Completions / Responses；仅授权公司网关允许 HTTP。"""
from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
import copy
import json
import re
import threading
import requests

from src.models.ai_diagnostics import ModelReply
from src.core.ai_stream import ModelStream
from src.core.ai_source_ip import SourceIpAdapter, require_source_ip
from src.core.ai_gateway_network import collect_gateway_network, proxy_snapshot, transport_error
from src.services.ai_store import canonical_url, profile_fingerprint


class ModelServiceError(RuntimeError):
    pass


class ContextLengthError(ModelServiceError):
    """仅表示服务明确拒绝上下文长度；不携带服务原文。"""


def request_url(base_url, path):
    """保留配置身份，只在发请求时去掉已填写的Chat Completions后缀。"""
    base = canonical_url(base_url)
    suffix = "/chat/completions"
    if base.endswith(suffix) and path in ("chat/completions", "models"):
        base = base[:-len(suffix)]
    return base + "/" + path


class _SupplementDispatch:
    def __init__(self, history, positions, confirm):
        self.history, self.positions, self.confirm = history, positions, confirm
        self.payload = None
        self.matched = ()
        self.reached = False
        self.attempted = False


class DiagnosticModelClient:
    def __init__(self, profile, key, redactor, session=None, emit=None):
        self.profile = profile
        self.key = key
        self.redactor = redactor
        self.redactor.add_secrets((key,))
        self.session = session or requests.Session()
        if profile.source_ip:
            for scheme in ("http://", "https://"):
                self.session.mount(scheme, SourceIpAdapter(profile.source_ip))
        self.emit = emit
        self._supplement_dispatch = None

    @contextmanager
    def observe_supplement_dispatch(self, history, positions, confirm):
        observation = _SupplementDispatch(history, positions, confirm)
        previous = getattr(self, '_supplement_dispatch', None)
        self._supplement_dispatch = observation
        try:
            yield observation
        finally:
            self._supplement_dispatch = previous

    def _emit(self, message):
        if self.emit is not None:
            self.emit(self.redactor.text(message))

    def _request(self, method, path, payload=None, stop=None, on_text=None):
        observation = getattr(self, '_supplement_dispatch', None)
        if observation is not None and observation.payload is not None and observation.payload is payload and method == 'POST':
            observation.reached = True
        else:
            observation = None
        if stop is not None and stop.is_set():
            raise InterruptedError("诊断已取消")
        url = request_url(self.profile.base_url, path)
        try:
            require_source_ip(self.profile.source_ip)
        except Exception as exc:
            detail = str(exc) if isinstance(exc, ValueError) else "出口 IP 检查失败：" + type(exc).__name__
            self._emit("[AI请求] 失败：" + detail + "；未发送请求")
            raise ModelServiceError(detail) from None
        self._emit(f"[AI请求] TX {method} {url}；协议={self.profile.protocol}；模型={self.profile.model}；"
                   f"配置源IP={self.profile.source_ip or '不指定（自动选择）'}")
        proxy = proxy_snapshot(self.session, url)
        try:
            if observation is not None:
                observation.attempted = True
                try:
                    inputs = payload.get('input' if self.profile.protocol == 'responses' else 'messages')
                    if isinstance(inputs, list) and len(inputs) == len(observation.history):
                        observation.matched = tuple(identifier for index, identifier in observation.positions.items()
                            if inputs[index] == self.redactor.object(observation.history[index]))
                except Exception:
                    observation.matched = ()
            response = self.session.request(
                method, url, headers={"Authorization": "Bearer " + self.key,
                                      "Content-Type": "application/json"},
                json=payload, timeout=(min(10, self.profile.timeout), self.profile.timeout),
                allow_redirects=False, stream=True,
            )
            try:
                if observation is not None and observation.matched and 100 <= response.status_code <= 599:
                    try:
                        observation.confirm(observation.matched)
                    except Exception:
                        # Presentation metadata is never a condition for processing the original response.
                        pass
                if not 200 <= response.status_code < 300:
                    if response.status_code in (400, 413, 422) and self._context_error(response, stop):
                        raise ContextLengthError("服务返回上下文超限；请调整容量或缩短材料")
                    # 不输出服务响应正文/请求头，避免代理回显密钥及原始输入。
                    category = {401: "密钥无效", 403: "权限不足", 404: "地址或模型不存在",
                                429: "限流或额度不足"}.get(response.status_code, "服务请求失败")
                    detail = f"{category}（HTTP {response.status_code}）；请求地址={url}"
                    if response.status_code == 404:
                        detail += "；请核对路径及模型ID，不会自动切换/v1或重发"
                    self._emit("[AI请求] 失败：" + detail)
                    raise ModelServiceError(self.redactor.text(detail))
                chunks, size = bytearray(), 0
                decoder = ModelStream(self.profile.protocol, lambda text: on_text(self.redactor.stream_text(text))) if on_text else None
                streaming = None
                # SSE须在事件到达时交付，不能等待累计满1KiB才显示首段正文。
                for chunk in response.iter_content(1 if decoder else 65536):
                    if stop is not None and stop.is_set():
                        raise InterruptedError("诊断已取消")
                    size += len(chunk)
                    if size > 4 * 1024 * 1024:
                        raise ModelServiceError("模型响应超过4 MiB限制")
                    if streaming is None:
                        chunks.extend(chunk)
                        start = chunk.lstrip()
                        if not start:
                            continue
                        streaming = bool(decoder and not start.startswith(b"{"))
                        if streaming:
                            decoder.feed(bytes(chunks))
                            chunks.clear()
                    elif streaming:
                        decoder.feed(chunk)
                    else:
                        chunks.extend(chunk)
                result = decoder.result() if streaming else json.loads(chunks)
                if not isinstance(result, dict):
                    raise ModelServiceError("模型返回格式不正确")
                if isinstance(result.get("base_resp"), dict) and result["base_resp"].get("status_code", 0):
                    raise ModelServiceError("厂商返回业务错误，请检查接入配置及额度")
                self._emit(f"[AI请求] 成功：{method} {url}（HTTP {response.status_code}）")
                return result
            finally:
                response.close()
        except (requests.ConnectionError, requests.Timeout) as exc:
            if stop is not None and stop.is_set():
                raise InterruptedError("诊断已取消") from None
            detail = transport_error(exc)
            self._emit("[AI请求] 失败：" + detail + "；开始当前网络诊断（不重发模型请求）")
            network = collect_gateway_network(url, proxy, stop, self._emit, source_ip=self.profile.source_ip)
            raise ModelServiceError(self.redactor.text(detail + "；" + network)) from None
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            self._emit("[AI请求] 失败：网络或响应解析异常 " + type(exc).__name__)
            raise ModelServiceError("模型网络或响应解析失败：" + type(exc).__name__) from None

    @staticmethod
    def _context_error(response, stop):
        # 有界读取仅用于识别错误类别；不回显正文，防止代理回显认证密钥。
        data = bytearray()
        for chunk in response.iter_content(8192):
            if stop is not None and stop.is_set():
                raise InterruptedError("诊断已取消")
            if len(data) + len(chunk) > 65536:
                return False
            data.extend(chunk)
        try:
            body = json.loads(data)
        except (ValueError, TypeError):
            return False
        if not isinstance(body, dict):
            return False
        error = body.get("error", body)
        if isinstance(error, str):
            error = {"message": error}
        if not isinstance(error, dict):
            return False
        codes = {"context_length_exceeded", "max_context_length_exceeded", "input_too_long", "too_many_tokens"}
        if any(error.get(field) in codes for field in ("code", "type") if isinstance(error.get(field), str)):
            return True
        message = error.get("message", "")
        return isinstance(message, str) and bool(re.search(
            r"maximum context length|context length (?:is )?exceeded|exceeds? (?:the )?context window|prompt is too long",
            message, re.I))

    def model_details(self, stop=None):
        response = self._request("GET", "models", stop=stop)
        data = response.get("data", [])
        if not isinstance(data, list):
            raise ModelServiceError("模型列表格式不正确")
        models = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                continue
            capacity = next((item[key] for key in ("context_window", "context_length", "max_context_tokens")
                             if type(item.get(key)) is int and item[key] > 0), 0)
            models.append({"id": item["id"], "context_tokens": capacity})
        return tuple(models)

    def models(self, stop=None):
        return tuple(item["id"] for item in self.model_details(stop))

    def request_payload(self, history, tools=()):
        profile = self.profile
        payload = {"model": profile.model, "stream": False}
        if profile.protocol == "responses":
            payload.update(input=history, max_output_tokens=profile.max_output, store=False)
            if tools:
                payload["tools"] = [{"type": "function", **tool} for tool in tools]
        else:
            payload.update(messages=history)
            # 厂商不支持的参数不发送。MiniMax 新接口使用 max_completion_tokens。
            payload["max_completion_tokens" if profile.provider in ("MiniMax", "OpenAI") else "max_tokens"] = profile.max_output
            if tools:
                payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
                payload["tool_choice"] = "auto"
        # 出网内容仅过滤已登记的模型认证密钥，诊断材料保留真实值。
        # 当前厂商思考字段仅供协议续接。
        return self.redactor.object(payload)

    def complete(self, history, tools=(), stop=None, on_text=None):
        profile = self.profile
        payload = self.request_payload(history, tools)
        if on_text is not None:
            payload["stream"] = True
        observation = getattr(self, '_supplement_dispatch', None)
        if observation is not None and observation.history is history:
            observation.payload = payload
        response = self._request("POST", "responses" if profile.protocol == "responses" else "chat/completions",
                                 payload, stop, on_text)
        calls = []
        if profile.protocol == "responses":
            output = response.get("output", [])
            if not isinstance(output, list):
                raise ModelServiceError("Responses 输出格式不正确")
            text = "\n".join(str(c.get("text", "")) for item in output if item.get("type") == "message"
                             for c in item.get("content", []) if c.get("type") == "output_text")
            for item in output:
                if item.get("type") == "function_call":
                    calls.append({"id": item.get("call_id"), "name": item.get("name"), "arguments": item.get("arguments")})
            next_history = copy.deepcopy(history) + output
        else:
            choices = response.get("choices") or []
            if not choices or not isinstance(choices[0].get("message"), dict):
                raise ModelServiceError("模型没有返回有效回复")
            message = choices[0]["message"]
            text = message.get("content") or ""
            if not isinstance(text, str):
                raise ModelServiceError("模型文本格式不正确")
            for call in message.get("tool_calls") or []:
                if call.get("type") != "function":
                    raise ModelServiceError("不支持的模型工具类型")
                function = call.get("function") or {}
                calls.append({"id": call.get("id"), "name": function.get("name"), "arguments": function.get("arguments")})
            # 保留 DeepSeek/MiniMax reasoning_content/tool_calls；不跨配置共享历史。
            next_history = copy.deepcopy(history) + [message]
        if len(calls) > 10:
            raise ModelServiceError("模型单次工具请求超过上限")
        return ModelReply(self.redactor.text(text), calls, next_history, response.get("usage") or {})

    def tool_result(self, call, result):
        text = self.redactor.dumps(result)
        if self.profile.protocol == "responses":
            return {"type": "function_call_output", "call_id": call["id"], "output": text}
        return {"role": "tool", "tool_call_id": call["id"], "content": text}

    def complete_stream(self, history, tools=(), stop=None, on_text=None):
        return self.complete(history, tools, stop, on_text=on_text)

    def test_connection(self, stop=None):
        first = self.complete([{"role": "user", "content": "连接检查：请只回复 OK。"}], stop=stop)
        if not first.text.strip():
            raise ModelServiceError("普通问答未返回文本")
        tool = {"name": "connection_test", "description": "无副作用的连接能力测试；请调用一次。",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}
        try:
            reply = self.complete([{"role": "user", "content": "请调用 connection_test，然后根据工具返回回复 OK。"}], [tool], stop)
            if len(reply.calls) != 1 or reply.calls[0]["name"] != "connection_test" or json.loads(reply.calls[0]["arguments"]) != {}:
                return "可问答", "未完成有效工具调用；主动采集禁用"
            history = reply.history + [self.tool_result(reply.calls[0], {"ok": True})]
            final = self.complete(history, stop=stop)
            if final.calls or not final.text.strip():
                return "可问答", "工具结果续接失败；主动采集禁用"
            return "可自动诊断", "普通问答、工具调用及结果续接通过"
        except InterruptedError:
            raise
        except (ModelServiceError, ValueError, TypeError):
            return "可问答", "工具调用不兼容；主动采集禁用"

    def close(self):
        self.session.close()
