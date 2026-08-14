"""Zero-cred, zero-network dry run for the demo IdeaSource.

A STUB Worker returns a canned JSON array, so no key and no HTTP call are needed. We assert the
agent files ideas through an in-memory ListSink and that it NEVER self-admits (the sink only
records filings — admission is a separate gate the agent cannot reach).
"""
from fls.feeder import ListSink
from fls.llm import Call

from .module import ClaudeDemoAgent


class StubBuilder:
    """A Worker with no creds/network — returns a fixed brainstorm array."""

    def available(self) -> bool:
        return True

    def complete(self, prompt, max_tokens=1024, system=None):
        text = ('[{"intent": "cmd-k palette", "success": "opens in <100ms", "altitude": "feature"},'
                ' {"intent": "bolder primary button", "success": "picked without changes", "altitude": "ticket"},'
                ' {"intent": "empty-state art", "success": "fewer bounces", "altitude": "feature"}]')
        return text, Call("stub", "stub")


def test_demo_agent_files_through_sink_and_cannot_self_admit():
    sink = ListSink()
    agent = ClaudeDemoAgent(builder=StubBuilder(), n=3)
    run = agent.run(anchor=None, anchor_text="North star: a design-token bridge.", sink=sink)

    # every proposed idea entered by the one door (the sink), none admitted by the agent
    assert run.proposed == 3
    assert len(run.filed) == 3
    assert len(sink.filed) == 3
    assert [f.candidate.intent for f in sink.filed] == [
        "cmd-k palette", "bolder primary button", "empty-state art"]
    # ListSink only exposes filing — the agent has no admit path at all
    assert not hasattr(sink, "admit")


def test_demo_agent_honors_n_cap():
    sink = ListSink()
    agent = ClaudeDemoAgent(builder=StubBuilder(), n=2)
    run = agent.run(anchor=None, anchor_text="anchor", sink=sink)
    assert len(run.filed) == 2
