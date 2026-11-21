"""Run ASGI contracts without requiring a TCP wake-up socket for asyncio.

TestClient still uses the real FastAPI app, middleware and HTTP serialization.
Only its event-loop wake-up mechanism is replaced. This runner cannot perform
network I/O and does not validate TCP, TLS or the native Rust bridge.
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import selectors
import threading
from pathlib import Path

import pytest
from starlette.testclient import TestClient


class InProcessSelector(selectors.BaseSelector):
    def __init__(self):
        super().__init__()
        self.wakeup = threading.Event()

    def register(self, fileobj, events, data=None):
        raise RuntimeError("in-process HTTP verification does not support socket/file I/O")

    def unregister(self, fileobj):
        raise KeyError(fileobj)

    def select(self, timeout=None):
        # Bounded polling also handles a wakeup arriving immediately before clear.
        self.wakeup.wait(0.01 if timeout is None else min(max(timeout, 0), 0.01))
        self.wakeup.clear()
        return []

    def get_map(self):
        return {}

    def close(self):
        self.wakeup.set()


class InProcessLoop(asyncio.SelectorEventLoop):
    def __init__(self):
        super().__init__(selector=InProcessSelector())

    def _make_self_pipe(self):
        # Windows socketpair normally needs a loopback connection. This runner
        # uses a thread Event instead and cannot make network requests.
        pass

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        self._selector.wakeup.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-list", type=Path)
    parser.add_argument("--all", action="store_true", help="Run the full suite except seven real-network cases")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("cases", nargs="*")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = args.cases
    if args.all:
        cases = ["tests"]
    if args.case_list:
        cases += [line for line in args.case_list.read_text(encoding="utf-8").splitlines()
                  if line and "test_worker_tls.py" not in line and "test_ai_os_core.py" not in line]
    if not cases:
        parser.error("provide cases or --case-list")
    original = TestClient.__init__

    @functools.wraps(original)
    def initialize(self, *positional, **keywords):
        if keywords.get("backend", "asyncio") != "asyncio":
            raise ValueError("only asyncio TestClient is supported by this runner")
        keywords["backend_options"] = {**keywords.get("backend_options", {}),
                                       "loop_factory": InProcessLoop}
        original(self, *positional, **keywords)

    class RealNetworkExclusions:
        def pytest_collection_modifyitems(self, config, items):
            excluded = [item for item in items if "test_worker_tls.py" in item.nodeid
                        or "test_sin_pegar_tokens_core_da_el_del_broker_y_se_renueva" in item.nodeid]
            items[:] = [item for item in items if item not in excluded]
            (output / "real-network-not-run.txt").write_text(
                "\n".join(item.nodeid for item in excluded), encoding="utf-8")
            config.hook.pytest_deselected(items=excluded)

    TestClient.__init__ = initialize
    try:
        return pytest.main([*cases, "-v", "--tb=short", "-p", "no:cacheprovider",
                            f"--basetemp={output / 'temp'}", f"--junitxml={output / 'results.xml'}"],
                           plugins=[RealNetworkExclusions()])
    finally:
        TestClient.__init__ = original


if __name__ == "__main__":
    raise SystemExit(main())
