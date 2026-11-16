"""有界SSE解码及两种模型协议的完整响应组装；不执行工具碎片。"""
import copy
import json


class ModelStream:
    def __init__(self, protocol, on_text):
        self.protocol, self.on_text = protocol, on_text
        self.buffer = bytearray()
        self.data = []
        self.text = ""
        self.message = {"role": "assistant", "content": ""}
        self.calls = {}
        self.usage = {}
        self.response = None
        self.finished = False

    def feed(self, chunk):
        # 低延迟HTTP读取可能一次仅到一个字节；避免反复复制/扫描整条长事件。
        parts = chunk.split(b"\n")
        self.buffer.extend(parts[0])
        for part in parts[1:]:
            self.line(bytes(self.buffer).rstrip(b"\r"))
            self.buffer.clear()
            self.buffer.extend(part)

    def line(self, line):
        if not line:
            if self.data:
                payload, self.data = b"\n".join(self.data), []
                if payload == b"[DONE]":
                    if self.protocol != "responses":
                        self.finished = True
                    return
                self.event(json.loads(payload))
        elif line.startswith(b"data:"):
            self.data.append(line[5:].lstrip(b" "))

    def event(self, event):
        if not isinstance(event, dict) or event.get("error"):
            raise ValueError("模型流返回错误")
        if self.protocol == "responses":
            kind = event.get("type")
            if kind == "response.output_text.delta":
                self.text += event["delta"]
                self.on_text(self.text)
            elif kind == "response.completed":
                response = event.get("response")
                if not isinstance(response, dict) or response.get("status") != "completed":
                    raise ValueError("模型流缺少完整结果")
                self.response, self.finished = response, True
            elif kind in ("error", "response.failed", "response.incomplete"):
                raise ValueError("模型流未完成")
            return
        if event.get("usage"):
            self.usage = event["usage"]
        for choice in event.get("choices", []):
            if choice.get("index", 0) != 0:
                continue
            if choice.get("finish_reason") in ("length", "content_filter"):
                raise ValueError("模型流输出被截断")
            delta = choice.get("delta", {})
            for key in ("content", "reasoning_content"):
                if delta.get(key):
                    if not isinstance(delta[key], str):
                        raise ValueError("模型流文本格式无效")
                    self.message[key] = self.message.get(key, "") + delta[key]
            if delta.get("content"):
                self.text = self.message["content"]
                self.on_text(self.text)
            for item in delta.get("tool_calls", []):
                index = item.get("index")
                if type(index) is not int or not 0 <= index < 10:
                    raise ValueError("模型流工具序号无效")
                call = self.calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if item.get("type", "function") != "function":
                    raise ValueError("模型流工具类型无效")
                call["id"] += item.get("id", "")
                for key in ("name", "arguments"):
                    call["function"][key] += item.get("function", {}).get(key, "")

    def result(self):
        if self.buffer:
            self.line(bytes(self.buffer).rstrip(b"\r"))
        self.line(b"")
        if not self.finished:
            raise ValueError("模型流意外中断，工具未执行")
        if self.protocol == "responses":
            return self.response
        message = copy.deepcopy(self.message)
        if self.calls:
            message["tool_calls"] = [self.calls[k] for k in sorted(self.calls)]
        return {"choices": [{"message": message}], "usage": self.usage}
