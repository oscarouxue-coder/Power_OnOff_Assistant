"""直接 HTTPS 调用：统一 Chat Completions / Responses，不依赖厂商 SDK。"""
from __future__ import annotations

from dataclasses import replace
import copy
import json
import threading
import requests

from src.models.ai_diagnostics import ModelReply
from src.services.ai_store import canonical_url, profile_fingerprint


class ModelServiceError(RuntimeError):
    pass


class DiagnosticModelClient:
    def __init__(self, profile, key, redactor, session=None):
        self.profile = profile
        self.key = key
        self.redactor = redactor
        self.redactor.add_secrets((key,))
        self.session = session or requests.Session()

    def _request(self, method, path, payload=None, stop=None):
        if stop is not None and stop.is_set():
            raise InterruptedError("诊断已取消")
        url = canonical_url(self.profile.base_url) + "/" + path
        try:
            response = self.session.request(
                method, url, headers={"Authorization": "Bearer " + self.key,
                                      "Content-Type": "application/json"},
                json=payload, timeout=(min(10, self.profile.timeout), self.profile.timeout),
                allow_redirects=False, stream=True,
            )
            try:
                if not 200 <= response.status_code < 300:
                    # 不输出服务响应正文/请求头，避免代理回显密钥及原始输入。
                    category = {401: "密钥无效", 403: "权限不足", 404: "地址或模型不存在",
                                429: "限流或额度不足"}.get(response.status_code, "服务请求失败")
                    raise ModelServiceError(f"{category}（HTTP {response.status_code}）")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    if stop is not None and stop.is_set():
                        raise InterruptedError("诊断已取消")
                    size += len(chunk)
                    if size > 4 * 1024 * 1024:
                        raise ModelServiceError("模型响应超过4 MiB限制")
                    chunks.append(chunk)
                result = json.loads(b"".join(chunks))
                if not isinstance(result, dict):
                    raise ModelServiceError("模型返回格式不正确")
                if isinstance(result.get("base_resp"), dict) and result["base_resp"].get("status_code", 0):
                    raise ModelServiceError("厂商返回业务错误，请检查接入配置及额度")
                return result
            finally:
                response.close()
        except (requests.RequestException, ValueError) as exc:
            raise ModelServiceError("模型网络或响应解析失败：" + type(exc).__name__) from None

    def models(self, stop=None):
        response = self._request("GET", "models", stop=stop)
        return tuple(str(x["id"]) for x in response.get("data", [])
                     if isinstance(x, dict) and isinstance(x.get("id"), str))

    def complete(self, history, tools=(), stop=None):
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
        response = self._request("POST", "responses" if profile.protocol == "responses" else "chat/completions",
                                 self.redactor.object(payload), stop)
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
