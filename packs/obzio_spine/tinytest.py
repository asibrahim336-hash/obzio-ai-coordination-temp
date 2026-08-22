"""Minimal test runner. stdlib only, deterministic order, verbatim output.

Ordered by declaration, not by name -- lifecycle tests read as a sequence and
alphabetical ordering would scramble them."""

import sys
import time
import traceback


class Suite:
    def __init__(self, name):
        self.name = name
        self.tests = []

    def test(self, fn):
        self.tests.append(fn)
        return fn

    def run(self) -> int:
        print("=" * 72)
        print(f"PACK: {self.name}")
        print("=" * 72)
        passed = failed = 0
        t0 = time.time()
        for fn in self.tests:
            label = fn.__name__
            doc = (fn.__doc__ or "").strip().splitlines()
            note = doc[0] if doc else ""
            try:
                fn()
            except Exception:
                failed += 1
                print(f"[FAIL] {label}")
                if note:
                    print(f"       {note}")
                for line in traceback.format_exc().rstrip().splitlines():
                    print(f"       | {line}")
            else:
                passed += 1
                print(f"[PASS] {label}")
                if note:
                    print(f"       {note}")
        dt = time.time() - t0
        print("-" * 72)
        print(f"{self.name}: {passed} passed, {failed} failed, "
              f"{len(self.tests)} total  ({dt:.3f}s)")
        print("-" * 72)
        return 0 if failed == 0 else 1


def expect_raises(exc, fn, *a, **kw):
    """Assert the call raises `exc`. Returns the exception for inspection.
    A call that does NOT raise is the failure we care about most here --
    it means a control did not fire."""
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    except Exception as e:
        raise AssertionError(
            f"expected {exc.__name__}, got {type(e).__name__}: {e}") from e
    raise AssertionError(
        f"expected {exc.__name__} but the call SUCCEEDED -- control did not fire")


def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}\n  expected: {b!r}\n  actual:   {a!r}")


def assert_true(x, msg=""):
    if x is not True and not x:
        raise AssertionError(f"{msg} (got {x!r})")


def assert_no_import(path, modules, msg=""):
    """Assert a module does not import any of `modules`.

    Parses the AST rather than grepping the source. An earlier version
    string-matched "from engine", which false-positived on the word appearing
    inside a docstring that was explaining the very restriction it enforces.
    A guard that fires on its own documentation is a bad guard."""
    import ast as _ast
    tree = _ast.parse(open(path, encoding="utf-8").read())
    found = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for a in node.names:
                found.add(a.name.split(".")[0])
        elif isinstance(node, _ast.ImportFrom):
            if node.module and node.level == 0:
                found.add(node.module.split(".")[0])
            elif node.level:
                found.add((node.module or "").split(".")[0])
    bad = sorted(set(modules) & found)
    if bad:
        raise AssertionError(
            f"{msg}\n  {path} imports {bad}, which breaks its independence "
            f"claim.\n  all imports: {sorted(found)}")
    return sorted(found)


def assert_in(needle, hay, msg=""):
    if needle not in hay:
        raise AssertionError(f"{msg}\n  {needle!r} not found in {hay!r}")
