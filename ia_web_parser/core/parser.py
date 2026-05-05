"""Shared parser for prompt-based tool calls in XML format.

Also supports auto-wrapping raw JSON tool calls if ``auto_wrap_json=True``.
"""
import json


class WebToolParser:
    """Parse ``<tool_call>{...}</tool_call>`` tags from model output.

    Works in streaming mode: feed chunks via :meth:`parse_chunk` and
    collect finished tool calls from :attr:`tool_calls`.  Any text
    that is *not* inside a ``<tool_call>`` block is returned as display
    text so it can be rendered in real time.

    Args:
        auto_wrap_json: If ``True``, also scan display text for raw JSON
            objects that look like ``{"name":"...", "input":{...}}`` and
            silently convert them into :class:`ToolCall` instances.
    """

    def __init__(self, auto_wrap_json: bool = False):
        self._in_call = False
        self._call_buf = ""
        self._raw_buf = ""
        self._auto_wrap_json = auto_wrap_json
        self.tool_calls: list[dict] = []

    # ── Streaming API ────────────────────────────────────────────────────

    def parse_chunk(self, chunk: str) -> str:
        """Consume *chunk* and return displayable text."""
        if not chunk:
            return ""
        self._raw_buf += chunk
        display = ""

        while True:
            if not self._in_call:
                # Look for start tag
                pos = self._raw_buf.find("<tool_call>")
                if pos == -1:
                    # No start tag. Check for partial start tag at the very end
                    last_lt = self._raw_buf.rfind("<")
                    if last_lt != -1 and "<tool_call>".startswith(self._raw_buf[last_lt:]):
                        display += self._raw_buf[:last_lt]
                        self._raw_buf = self._raw_buf[last_lt:]
                    else:
                        display += self._raw_buf
                        self._raw_buf = ""
                    break
                else:
                    # Found start tag: everything before is text
                    display += self._raw_buf[:pos]
                    self._in_call = True
                    self._raw_buf = self._raw_buf[pos + len("<tool_call>"):]
                    continue  # Look for end tag in the rest of buffer
            else:
                # Inside a tag: look for end tag
                pos = self._raw_buf.find("</tool_call>")
                if pos == -1:
                    # End tag not found yet, wait for more chunks
                    self._call_buf += self._raw_buf
                    self._raw_buf = ""
                    break
                else:
                    # Found end tag: extract JSON and continue
                    self._call_buf += self._raw_buf[:pos]
                    self._raw_buf = self._raw_buf[pos + len("</tool_call>"):]
                    try:
                        data = json.loads(self._call_buf.strip())
                        # Robust name/input extraction
                        name = data.get("name") or (
                            data.get("function", {}).get("name")
                            if isinstance(data.get("function"), dict)
                            else None
                        )
                        if name:
                            self.tool_calls.append({
                                "id": f"call_pt_{len(self.tool_calls)}",
                                "name": name,
                                "input": data.get("input")
                                or data.get("function", {}).get("arguments")
                                or {},
                            })
                    except Exception:
                        pass
                    self._call_buf = ""
                    self._in_call = False
                    continue  # Look for more tags in the rest of buffer

        # 2. Raw JSON Fallback (only if enabled and NOT inside a tag)
        if self._auto_wrap_json and not self._in_call and "{" in display:
            search_pos = 0
            while True:
                start = display.find("{", search_pos)
                if start == -1:
                    break

                snippet = display[start : start + 500]
                if '"name"' in snippet and (
                    '"input"' in snippet or '"arguments"' in snippet
                ):
                    brace_count = 0
                    end_pos = -1
                    for j in range(start, len(display)):
                        if display[j] == "{":
                            brace_count += 1
                        elif display[j] == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                end_pos = j + 1
                                break
                    if end_pos != -1:
                        try:
                            json_str = display[start:end_pos]
                            data = json.loads(json_str)
                            name = data.get("name") or (
                                data.get("function", {}).get("name")
                                if isinstance(data.get("function"), dict)
                                else None
                            )
                            if name:
                                self.tool_calls.append({
                                    "id": f"call_pt_{len(self.tool_calls)}",
                                    "name": name,
                                    "input": data.get("input")
                                    or data.get("function", {}).get("arguments")
                                    or {},
                                })
                                display = display[:start] + display[end_pos:]
                                search_pos = start
                                continue
                        except Exception:
                            pass
                search_pos = start + 1

        return display

    def flush(self) -> str:
        """Return any remaining text in the buffer."""
        res = self._raw_buf
        self._raw_buf = ""
        # If we were in a call but it never ended, output the partial call
        if self._in_call:
            res = "<tool_call>" + self._call_buf + res
            self._call_buf = ""
            self._in_call = False
        return res
