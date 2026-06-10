"""Tests for superseded-read context compaction."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from aise.runtime.context_compaction import (
    SupersededReadCompactionMiddleware,
    compact_superseded_reads,
)


def _read_call(call_id, file_path, **extra):
    args = {"file_path": file_path, **extra}
    return AIMessage(content="", tool_calls=[{"name": "read_file", "args": args, "id": call_id, "type": "tool_call"}])


def _read_result(call_id, content):
    return ToolMessage(content=content, tool_call_id=call_id, name="read_file")


BIG = "x" * 4000  # comfortably larger than any stub


class TestCompactSupersededReads:
    def test_duplicate_read_earlier_is_stubbed(self):
        msgs = [
            _read_call("c1", "a.ts"),
            _read_result("c1", BIG),
            _read_call("c2", "a.ts"),
            _read_result("c2", BIG),
        ]
        out = compact_superseded_reads(msgs)
        # First read of a.ts is stubbed; the latest keeps its content.
        assert out[1].content != BIG
        assert "已被后续相同读取取代" in out[1].content
        assert "a.ts" in out[1].content
        assert out[3].content == BIG

    def test_single_read_untouched(self):
        msgs = [_read_call("c1", "a.ts"), _read_result("c1", BIG)]
        out = compact_superseded_reads(msgs)
        assert out is msgs  # nothing changed -> same object back
        assert out[1].content == BIG

    def test_different_regions_both_kept(self):
        # Full read vs ranged read of the same file are distinct views.
        msgs = [
            _read_call("c1", "a.ts"),
            _read_result("c1", BIG),
            _read_call("c2", "a.ts", offset=88),
            _read_result("c2", BIG),
        ]
        out = compact_superseded_reads(msgs)
        assert out[1].content == BIG
        assert out[3].content == BIG

    def test_three_reads_only_last_survives(self):
        msgs = [
            _read_call("c1", "a.ts"),
            _read_result("c1", BIG),
            _read_call("c2", "a.ts"),
            _read_result("c2", BIG),
            _read_call("c3", "a.ts"),
            _read_result("c3", BIG),
        ]
        out = compact_superseded_reads(msgs)
        assert "取代" in out[1].content
        assert "取代" in out[3].content
        assert out[5].content == BIG

    def test_other_files_independent(self):
        msgs = [
            _read_call("a1", "a.ts"),
            _read_result("a1", BIG),
            _read_call("b1", "b.ts"),
            _read_result("b1", BIG),
            _read_call("a2", "a.ts"),
            _read_result("a2", BIG),
        ]
        out = compact_superseded_reads(msgs)
        assert "取代" in out[1].content  # a.ts first read superseded
        assert out[3].content == BIG  # b.ts read only once -> kept
        assert out[5].content == BIG  # a.ts latest -> kept

    def test_non_read_tool_results_ignored(self):
        msgs = [
            AIMessage(
                content="",
                tool_calls=[{"name": "write_file", "args": {"file_path": "a.ts"}, "id": "w1", "type": "tool_call"}],
            ),
            ToolMessage(content=BIG, tool_call_id="w1", name="write_file"),
            AIMessage(
                content="",
                tool_calls=[{"name": "write_file", "args": {"file_path": "a.ts"}, "id": "w2", "type": "tool_call"}],
            ),
            ToolMessage(content=BIG, tool_call_id="w2", name="write_file"),
        ]
        out = compact_superseded_reads(msgs)
        assert out is msgs  # write_file is not compacted
        assert all(m.content == BIG for m in out if isinstance(m, ToolMessage))

    def test_small_content_not_stubbed(self):
        # A duplicate whose body is already tiny yields no win -> left as-is.
        small = "ok"
        msgs = [
            _read_call("c1", "a.ts"),
            _read_result("c1", small),
            _read_call("c2", "a.ts"),
            _read_result("c2", small),
        ]
        out = compact_superseded_reads(msgs)
        assert out[1].content == small

    def test_preserves_surrounding_messages_and_order(self):
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="do it"),
            _read_call("c1", "a.ts"),
            _read_result("c1", BIG),
            _read_call("c2", "a.ts"),
            _read_result("c2", BIG),
        ]
        out = compact_superseded_reads(msgs)
        assert len(out) == len(msgs)
        assert out[0].content == "sys"
        assert out[1].content == "do it"
        # Identity/linkage preserved on the stubbed message.
        assert out[3].tool_call_id == "c1"
        assert out[3].name == "read_file"

    def test_originals_not_mutated(self):
        result = _read_result("c1", BIG)
        msgs = [_read_call("c1", "a.ts"), result, _read_call("c2", "a.ts"), _read_result("c2", BIG)]
        compact_superseded_reads(msgs)
        assert result.content == BIG  # original object untouched


class _Req:
    """Minimal stand-in for ModelRequest with the bits the middleware uses."""

    def __init__(self, messages):
        self.messages = messages
        self.overridden_with = None

    def override(self, **kw):
        self.overridden_with = kw
        return _Req(kw["messages"])


class TestMiddleware:
    def test_wrap_model_call_compacts_request(self):
        mw = SupersededReadCompactionMiddleware()
        msgs = [
            _read_call("c1", "a.ts"),
            _read_result("c1", BIG),
            _read_call("c2", "a.ts"),
            _read_result("c2", BIG),
        ]
        seen = {}

        def handler(req):
            seen["messages"] = req.messages
            return "RESPONSE"

        result = mw.wrap_model_call(_Req(msgs), handler)
        assert result == "RESPONSE"
        assert "取代" in seen["messages"][1].content
        assert seen["messages"][3].content == BIG

    def test_wrap_model_call_noop_passes_request_through(self):
        mw = SupersededReadCompactionMiddleware()
        req = _Req([_read_call("c1", "a.ts"), _read_result("c1", BIG)])
        passed = {}

        def handler(r):
            passed["req"] = r
            return "R"

        mw.wrap_model_call(req, handler)
        # No duplicates -> the same request object flows through untouched.
        assert passed["req"] is req
        assert req.overridden_with is None
