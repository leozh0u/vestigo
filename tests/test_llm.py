"""Tests for the provider layer.

Two things are load bearing here and both are about money rather than about
models. The cache has to make a rerun free while still giving repeat sampling
three distinct answers, and the budget has to refuse rather than warn. Both are
tested harder than the wire formats are.

Nothing here touches a network or costs anything. `FakeProvider` stands in, and
the two real providers are exercised through their parsers with recorded
payloads.
"""
import json

import pytest

from vestigo.llm import (
    PRICING,
    Budget,
    BudgetExceeded,
    CompletionCache,
    Completion,
    Image,
    LLMError,
    Message,
    Price,
    Request,
    Role,
    Router,
    Text,
    Usage,
    extract_json,
)
from vestigo.providers import (
    AnthropicProvider,
    FakeProvider,
    LocalProvider,
    MoonshotProvider,
    OpenAICompatProvider,
)

SONNET = "claude-sonnet-5"
HAIKU = "claude-haiku-4-5-20251001"


def ask(text="hello", **kw):
    return Request(messages=(Message.user(text),), **kw)


# -- cost ------------------------------------------------------------------

def test_cost_follows_the_price_table():
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000, model=SONNET)
    assert usage.cost_usd == pytest.approx(PRICING[SONNET].input + PRICING[SONNET].output)


def test_a_cached_prefix_bills_at_a_tenth():
    plain = Usage(input_tokens=1_000_000, model=SONNET)
    cached = Usage(input_tokens=1_000_000, cached_tokens=1_000_000, model=SONNET)
    assert cached.cost_usd == pytest.approx(plain.cost_usd * 0.1)


def test_batching_halves_it():
    plain = Usage(1_000_000, 100_000, model=SONNET)
    batched = Usage(1_000_000, 100_000, model=SONNET, batched=True)
    assert batched.cost_usd == pytest.approx(plain.cost_usd * 0.5)


def test_the_cheap_model_is_cheaper_by_the_ratio_on_the_page():
    big = Usage(1_000_000, 100_000, model=SONNET).cost_usd
    small = Usage(1_000_000, 100_000, model=HAIKU).cost_usd
    assert small < big / 2


def test_an_unpriced_model_costs_unknown_and_never_zero():
    """The one failure a budget must not have. A model with no price on file
    reporting zero looks fine right up until the invoice."""
    assert Usage(1_000_000, 1_000_000, model="kimi-k2-0711-preview").cost_usd is None


def test_usage_adds_up():
    total = Usage(10, 5, model=SONNET) + Usage(20, 7, 3, model=SONNET)
    assert (total.input_tokens, total.output_tokens, total.cached_tokens) == (30, 12, 3)
    assert total.model == SONNET


def test_adding_across_models_marks_the_total_mixed():
    assert (Usage(10, 5, model=SONNET) + Usage(10, 5, model=HAIKU)).model == "mixed"


# -- budget ----------------------------------------------------------------

def test_the_budget_refuses_rather_than_warns():
    budget = Budget(0.20)
    provider = FakeProvider(["reply"] * 200, model=SONNET, budget=budget)
    provider.complete(ask("one"))
    with pytest.raises(BudgetExceeded, match="ceiling"):
        for i in range(200):
            provider.complete(ask(f"more {i}"))
    assert budget.spent_usd <= budget.limit_usd


def test_the_estimate_assumes_the_worst_case_output():
    """The pre-flight check bills `max_tokens` as if it were all used, so it
    refuses early rather than late. A budget that only notices after the call
    has already let the call happen."""
    budget = Budget(0.001)
    provider = FakeProvider(["a"], model=SONNET, budget=budget)
    with pytest.raises(BudgetExceeded):
        provider.complete(ask("a short prompt", max_tokens=2048))
    assert provider.calls == []                # it never went out
    # Room for a smaller reply, and the same prompt goes through.
    assert provider.complete(ask("a short prompt", max_tokens=16)).text == "a"


def test_an_unpriced_model_is_refused_by_default():
    budget = Budget(10.0)
    provider = FakeProvider(["a"], model="kimi-k2-0711-preview", budget=budget)
    with pytest.raises(BudgetExceeded, match="no price on file"):
        provider.complete(ask())


def test_an_unpriced_model_can_be_allowed_explicitly():
    budget = Budget(10.0, allow_unpriced=True)
    provider = FakeProvider(["a"], model="kimi-k2-0711-preview", budget=budget)
    assert provider.complete(ask()).text == "a"
    assert budget.unpriced_calls == 1
    assert budget.spent_usd == 0.0        # untracked, and the count says so


def test_no_ceiling_means_no_limit():
    budget = Budget()
    assert budget.remaining_usd == float("inf")
    provider = FakeProvider(["a"] * 5, model=SONNET, budget=budget)
    for _ in range(5):
        provider.complete(ask())
    assert budget.spent_usd > 0


def test_the_ledger_says_where_the_money_went():
    budget = Budget(10.0)
    provider = FakeProvider([Completion("x", SONNET, Usage(1_000_000, 0, model=SONNET)),
                             Completion("y", SONNET, Usage(10, 0, model=SONNET))],
                            model=SONNET, budget=budget)
    provider.complete(ask(label="extract"))
    provider.complete(ask("other", label="reason"))
    spend = budget.by_label()
    assert list(spend) == ["extract", "reason"]        # largest first
    assert spend["extract"] > spend["reason"]


def test_remaining_tracks_spend():
    budget = Budget(10.0)
    provider = FakeProvider([Completion("x", SONNET, Usage(1_000_000, 0, model=SONNET))],
                            model=SONNET, budget=budget)
    provider.complete(ask())
    assert budget.remaining_usd == pytest.approx(10.0 - PRICING[SONNET].input)


# -- cache -----------------------------------------------------------------

def test_a_repeat_call_is_free(tmp_path):
    cache = CompletionCache(tmp_path)
    provider = FakeProvider(["once"], model=SONNET, cache=cache)
    first = provider.complete(ask())
    second = provider.complete(ask())
    assert len(provider.calls) == 1                    # the model ran once
    assert first.text == second.text
    assert second.cached and second.cost_usd == 0.0
    assert cache.hit_rate == 0.5


def test_repeat_sampling_and_caching_coexist(tmp_path):
    """Three samples of one image cost three calls the first time and nothing
    on any rerun, while still carrying three distinct answers. Without the
    sample index one of those two properties has to go."""
    cache = CompletionCache(tmp_path)
    provider = FakeProvider(["a", "b", "c"], model=SONNET, cache=cache)
    first = [provider.complete(ask(sample=i)).text for i in range(3)]
    assert first == ["a", "b", "c"]
    assert len(provider.calls) == 3

    again = FakeProvider([], model=SONNET, cache=cache)
    assert [again.complete(ask(sample=i)).text for i in range(3)] == first
    assert again.calls == []


def test_a_different_prompt_misses(tmp_path):
    provider = FakeProvider(["a", "b"], model=SONNET, cache=CompletionCache(tmp_path))
    provider.complete(ask("one"))
    provider.complete(ask("two"))
    assert len(provider.calls) == 2


def test_a_different_model_misses(tmp_path):
    cache = CompletionCache(tmp_path)
    FakeProvider(["a"], model=SONNET, cache=cache).complete(ask())
    second = FakeProvider(["b"], model=HAIKU, cache=cache)
    assert second.complete(ask()).text == "b"


def test_a_corrupt_entry_is_a_miss_not_a_crash(tmp_path):
    cache = CompletionCache(tmp_path)
    FakeProvider(["a"], model=SONNET, cache=cache).complete(ask())
    for p in tmp_path.glob("**/*.json"):
        p.write_text("{not json")
    assert FakeProvider(["b"], model=SONNET, cache=cache).complete(ask()).text == "b"


def test_the_budget_is_not_charged_for_a_cache_hit(tmp_path):
    budget = Budget(1.0)
    cache = CompletionCache(tmp_path)
    provider = FakeProvider(["a"], model=SONNET, budget=budget, cache=cache)
    provider.complete(ask())
    spent = budget.spent_usd
    provider.complete(ask())
    assert budget.spent_usd == spent


# -- fingerprints ----------------------------------------------------------

def test_the_sample_index_changes_the_key():
    a = ask(sample=0).fingerprint("fake", SONNET)
    b = ask(sample=1).fingerprint("fake", SONNET)
    assert a != b


def test_the_same_request_gives_the_same_key():
    assert ask().fingerprint("fake", SONNET) == ask().fingerprint("fake", SONNET)


def test_an_image_is_keyed_by_its_digest_not_its_bytes():
    """So a cache key stays small and a logged request does not carry a
    megabyte of photograph."""
    payload = Image(b"\xff\xd8pretend jpeg").to_dict()
    assert "sha256" in payload and "data" not in payload
    assert len(payload["sha256"]) == 64


def test_two_identical_images_key_the_same():
    assert Image(b"same").to_dict() == Image(b"same").to_dict()
    assert Image(b"same").to_dict() != Image(b"other").to_dict()


def test_estimating_input_counts_images():
    text_only = ask("word " * 100).estimate_tokens()
    with_image = Request(messages=(Message.user("word " * 100, Image(b"x")),)).estimate_tokens()
    assert with_image > text_only + 1000


# -- routing ---------------------------------------------------------------

def test_a_router_sends_each_job_to_its_model():
    cheap = FakeProvider(["seen"] * 3, model=HAIKU)
    good = FakeProvider(["decided"] * 3, model=SONNET)
    router = Router(default=good, jobs={"extract": cheap})

    assert router.complete("extract", ask()).model == HAIKU
    assert router.complete("reason", ask()).model == SONNET
    assert len(cheap.calls) == 1 and len(good.calls) == 1


def test_the_router_labels_each_call_with_its_job():
    budget = Budget(1.0)
    provider = FakeProvider(["a", "b"], model=SONNET, budget=budget)
    router = Router(default=provider)
    router.complete("extract", ask())
    router.complete("reason", ask("x"))
    assert set(budget.by_label()) == {"extract", "reason"}


def test_the_router_lists_each_provider_once():
    shared = FakeProvider([], model=SONNET)
    router = Router(default=shared, jobs={"a": shared, "b": FakeProvider([], model=HAIKU)})
    assert len(router.providers()) == 2


# -- parsing replies -------------------------------------------------------

def test_extract_json_takes_a_bare_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_digs_it_out_of_prose_or_a_fence():
    assert extract_json('Here you go:\n```json\n{"a": 1}\n```\nhope that helps') == {"a": 1}
    assert extract_json('Sure. {"a": {"b": 2}} done.') == {"a": {"b": 2}}


def test_extract_json_raises_when_there_is_none():
    with pytest.raises(ValueError):
        extract_json("no object here at all")


# -- the wire formats ------------------------------------------------------

def test_anthropic_sends_an_image_as_base64():
    block = AnthropicProvider._content(Image(b"bytes", "image/png"))
    assert block["source"]["media_type"] == "image/png"
    assert block["source"]["type"] == "base64"


def test_openai_compat_sends_an_image_as_a_data_url():
    block = OpenAICompatProvider._content(Image(b"bytes", "image/png"))
    assert block["image_url"]["url"].startswith("data:image/png;base64,")


def test_an_unsendable_part_is_an_error():
    with pytest.raises(LLMError):
        AnthropicProvider._content(object())


def test_anthropic_counts_cached_tokens_into_the_input():
    provider = AnthropicProvider(SONNET, api_key="x")
    reply = {
        "model": SONNET,
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "hello"}],
        "usage": {"input_tokens": 100, "output_tokens": 20,
                  "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0},
    }
    out = provider._parse(reply, SONNET, ask())
    assert out.usage.input_tokens == 1000
    assert out.usage.cached_tokens == 900
    assert out.cost_usd < Usage(1000, 20, model=SONNET).cost_usd


def test_anthropic_reads_structured_output_off_the_forced_tool():
    provider = AnthropicProvider(SONNET, api_key="x")
    reply = {"model": SONNET, "content": [
        {"type": "tool_use", "id": "t1", "name": "answer", "input": {"country": "Mexico"}}
    ], "usage": {"input_tokens": 10, "output_tokens": 5}}
    out = provider._parse(reply, SONNET, ask(schema={"type": "object"}))
    assert out.structured == {"country": "Mexico"}
    assert out.tool_calls[0]["name"] == "answer"


def test_openai_compat_parses_content_and_tool_calls():
    provider = OpenAICompatProvider("m", api_key="x")
    reply = {"model": "m", "choices": [{"finish_reason": "stop", "message": {
        "content": '{"country": "Mexico"}',
        "tool_calls": [{"id": "c1", "function": {"name": "solar",
                                                 "arguments": '{"lighting": "daylight"}'}}],
    }}], "usage": {"prompt_tokens": 10, "completion_tokens": 4}}
    out = provider._parse(reply, "m", ask(schema={"type": "object"}))
    assert out.structured == {"country": "Mexico"}
    assert out.tool_calls[0]["input"] == {"lighting": "daylight"}
    assert out.stop_reason == "stop"


def test_openai_compat_falls_back_to_the_tool_call_when_the_text_is_not_json():
    """Not every compatible server honours a json mode, so the reply is parsed
    whichever way it arrives."""
    provider = OpenAICompatProvider("m", api_key="x")
    reply = {"model": "m", "choices": [{"message": {
        "content": "here is the answer",
        "tool_calls": [{"id": "c1", "function": {"name": "answer",
                                                 "arguments": '{"country": "Chile"}'}}],
    }}], "usage": {}}
    assert provider._parse(reply, "m", ask(schema={"type": "object"})).structured \
        == {"country": "Chile"}


def test_an_empty_reply_is_an_error():
    provider = OpenAICompatProvider("m", api_key="x")
    with pytest.raises(LLMError):
        provider._parse({"choices": []}, "m", ask())


def test_a_missing_key_says_where_to_put_one():
    import os
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        with pytest.raises(LLMError, match="gitignored"):
            OpenAICompatProvider("m")._send(ask(), "m")
    finally:
        if saved:
            os.environ["OPENAI_API_KEY"] = saved


def test_the_vendor_subclasses_only_change_the_endpoint():
    assert MoonshotProvider("kimi-k2-0711-preview", api_key="x").base_url.startswith("https://api.moonshot")
    assert LocalProvider().base_url.startswith("http://localhost")
    assert MoonshotProvider("m", api_key="x").key_env == "MOONSHOT_API_KEY"


def test_kimi_is_deliberately_unpriced():
    """Their rates move and depend on the host, so a stale number here would
    make the budget confident and wrong."""
    assert MoonshotProvider.default_model not in PRICING


def test_a_provider_needs_a_model():
    class Nameless(FakeProvider):
        name = ""
    with pytest.raises(ValueError):
        Nameless(model="x")


# -- the fake ---------------------------------------------------------------

def test_the_fake_returns_dicts_as_structured_output():
    out = FakeProvider([{"country": "Mexico"}], model=SONNET).complete(ask())
    assert out.structured == {"country": "Mexico"}
    assert json.loads(out.text) == {"country": "Mexico"}


def test_the_fake_can_raise():
    provider = FakeProvider([LLMError("overloaded")], model=SONNET)
    with pytest.raises(LLMError):
        provider.complete(ask())


def test_messages_carry_mixed_parts():
    m = Message.user("look at this", Image(b"x"))
    assert m.role is Role.USER
    assert isinstance(m.content[0], Text) and isinstance(m.content[1], Image)


def test_image_media_type_comes_from_the_suffix(tmp_path):
    p = tmp_path / "shot.png"
    p.write_bytes(b"x")
    assert Image.from_path(p).media_type == "image/png"


def test_a_custom_price_can_be_registered():
    """What to do the moment you know a vendor's real rate."""
    PRICING["test-model"] = Price(0.15, 0.60)
    try:
        assert Usage(1_000_000, 0, model="test-model").cost_usd == pytest.approx(0.15)
        Budget(1.0).check("test-model")
    finally:
        del PRICING["test-model"]
