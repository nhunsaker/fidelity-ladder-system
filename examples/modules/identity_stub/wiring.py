"""Register the stub provider into the IDENTITY registry under kind "stub".

Point the engine at this module to load it:  FLS_MODULES=identity_stub.wiring
Importing it (the engine does this via importlib) runs the registration side effect below, and
`FLS_IDENTITY_KIND=stub` then selects it.

This is the whole extension story for the seventh seam, and it is why `identity` is a NEW
registry rather than a widened `Auth` Protocol: adding a kind to a registry cannot break a
module already in it, whereas adding a method to a published structural Protocol silently can.
"""
from __future__ import annotations

from fls import modules

from .module import StubIdentity


def _factory(header: str = "X-Stub-User", **kw) -> StubIdentity:
    return StubIdentity(header=header)


modules.IDENTITY["stub"] = _factory
