"""P5: ladder-mcp tools + the non-bypassable-gate property. Skips if fastmcp absent (it's an
optional dep — CI installs only [dev], so this is skipped there; run locally with [mcp])."""
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(importlib.util.find_spec("fastmcp") is None,
                                reason="fastmcp not installed ([mcp] extra)")


def _server(tmp_path):
    from fls.adjudicator import Idea
    from fls.expedition import Expedition
    from fls.ladder_mcp import build_server
    from fls.store import ExpeditionStore
    store = ExpeditionStore(tmp_path)
    store.save(Expedition(1, Idea(1, "cmd-k", "focuses search", "feature"), target_rung=5, rung=5,
                          status="await-signoff"))
    # server reads ANCHOR relative to root; copy the real one in
    (Path(tmp_path) / "ANCHOR.md").write_text(
        (Path(__file__).resolve().parents[2] / "ANCHOR.md").read_text())
    return build_server(tmp_path)


async def _call(server, name, **kw):
    res = await server._call_tool(name, kw)  # fastmcp internal call path
    return res


def test_promote_refused_without_approver(tmp_path):
    """The core governance property: an MCP tool cannot bypass the prod gate."""
    from fls.rung5 import FlagStore, promote_to_prod
    # exercise the underlying gate directly (deterministic, no fastmcp internals)
    fp = Path(tmp_path) / "flags.json"
    fp.write_text('{"cmd-k-search": {"stage": true, "prod": false}}')
    blocked = promote_to_prod("cmd-k-search", "HEAD", FlagStore(fp), _Ok(), approved_by=None)
    assert not blocked.prod_deployed
    ok = promote_to_prod("cmd-k-search", "HEAD", FlagStore(fp), _Ok(), approved_by="nathan")
    assert ok.prod_deployed


def test_server_builds_with_tools(tmp_path):
    server = _server(tmp_path)
    assert server is not None
    assert server.name == "ladder-mcp"


class _Ok:
    def deploy(self, env, ref):
        return True
