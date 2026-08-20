"""Where the money decisions live, in one file.

Routing, budgets and caching are scattered by default: a model name in the
agent, another in a script, a cache path in a third place. That is how a
project ends up running the expensive model for everything and finding out at
the end of the month.

Three presets. `cheap` is the one to run evals on and the one the numbers in
`results/` should eventually come from. `local` costs nothing per image and is
the right home for the extractor.
"""
from __future__ import annotations

from .llm import Budget, CompletionCache, Provider, Router
from .providers import AnthropicProvider, LocalProvider, MoonshotProvider

# The largest single lever, and it is a one-line decision. Reading a photograph
# and listing what is in it is the highest-volume, most image-heavy and least
# reasoning-intensive call in the pipeline. Deciding which of five clues to
# chase next runs a handful of times per image and is where a better model
# actually shows.
EXTRACTOR = "claude-haiku-4-5-20251001"
REASONER = "claude-sonnet-5"


def build(preset: str = "cheap", *, limit_usd: float | None = 5.0,
          cache_dir: str = ".cache/llm", batched: bool = False) -> tuple[Router, Budget]:
    """A router and the budget watching it.

    The budget is returned rather than hidden, because the number worth looking
    at after a run is `budget.by_label()`, which says which step spent what.

    `batched` halves the price and costs nothing in convenience on an eval,
    since nothing is waiting on one.
    """
    budget = Budget(limit_usd)
    cache = CompletionCache(cache_dir)
    common = {"cache": cache, "budget": budget, "batched": batched}

    def anthropic(model: str) -> Provider:
        return AnthropicProvider(model, **common)

    if preset == "cheap":
        # The default. A small model reads the photograph, a larger one reasons.
        return Router(anthropic(REASONER), {"extract": anthropic(EXTRACTOR)}), budget

    if preset == "quality":
        # Everything on the reasoning model. For checking whether the cheap
        # extractor is costing accuracy, which is a measurement worth making
        # once rather than an assumption worth carrying.
        return Router(anthropic(REASONER)), budget

    if preset == "local":
        # Extraction on this machine, so the highest-volume call has no
        # marginal cost at all.
        return Router(anthropic(REASONER),
                      {"extract": LocalProvider(cache=cache, budget=budget)}), budget

    if preset == "kimi":
        # A second vendor, for the comparison the calibration thesis wants.
        # Add its current rate to PRICING first, or the budget will refuse it,
        # which is the intended behaviour rather than an obstacle.
        return Router(MoonshotProvider(**common),
                      {"extract": LocalProvider(cache=cache, budget=budget)}), budget

    raise ValueError(f"unknown preset {preset!r}. "
                     "Try cheap, quality, local or kimi.")
