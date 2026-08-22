#!/usr/bin/env python3
"""Anchored git-style path globs with decidable pattern intersection.

The PO-03 ownership grants in ``workstreams/po03/control/path-ownership.json``
are repository-root-relative pathspec globs, not ``.gitignore`` patterns.  The
two git dialects are not interchangeable: a ``.gitignore`` pattern that contains
no separator matches a basename at any depth, while a ``:(glob)`` pathspec is
anchored at the tree root.  Conflating them would silently widen an ownership
grant to unrelated directories, so this module implements the anchored pathspec
dialect only and rejects patterns whose intent would be ambiguous.

Beyond matching, the module decides whether two patterns can ever match the same
path, and returns a concrete witness path when they can.  Overlap between two
ownership grants is therefore detectable from the patterns alone, before any
subordinate writes a file.

Semantics implemented, mirroring git's ``:(glob)`` pathspec magic:

* patterns are anchored at the repository root and match file paths only;
* ``?`` matches exactly one character other than ``/``;
* ``*`` matches zero or more characters other than ``/``;
* ``[...]`` is a POSIX-style character class supporting ranges, ``!``/``^``
  negation, a leading literal ``]`` and backslash escapes; it never matches
  ``/``;
* ``**`` is meaningful only as a complete segment; a leading or interior ``**``
  matches zero or more segments, and a trailing ``**`` matches one or more
  segments, so ``a/**`` matches everything inside ``a`` but not a file ``a``;
* backslash escapes the following character inside a segment.
"""

from __future__ import annotations

import unicodedata
from collections import deque
from typing import Iterable, Sequence

SEPARATOR = "/"
MAX_CODEPOINT = 0x10FFFF

_CONTROL_CHARS = frozenset(chr(code) for code in range(0x20)) | frozenset("\x7f")

# Sentinels are tried first so that witness paths read like real paths.  The
# high private-use character guarantees a witness outside every explicitly
# mentioned range, which is what a negated character class needs.
_SENTINEL_CHARS = ("a", "b", "z", "A", "Z", "0", "9", "_", "-", ".", "~", "\uf8ff")


class GlobSyntaxError(ValueError):
    """Raised when a pattern cannot be compiled under the anchored dialect."""


class PathSyntaxError(ValueError):
    """Raised when a changed path is not a plain repository-relative file path."""


class _Star:
    """Matches zero or more characters other than the separator."""

    __slots__ = ()

    def endpoints(self) -> frozenset[str]:
        return frozenset()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "STAR"


class _AnyChar:
    """Matches exactly one character other than the separator."""

    __slots__ = ()

    def matches(self, char: str) -> bool:
        return char != SEPARATOR

    def endpoints(self) -> frozenset[str]:
        return frozenset()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _AnyChar)

    def __hash__(self) -> int:
        return hash("_AnyChar")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ANY"


class _Literal:
    __slots__ = ("char",)

    def __init__(self, char: str) -> None:
        self.char = char

    def matches(self, char: str) -> bool:
        return char == self.char

    def endpoints(self) -> frozenset[str]:
        return frozenset({self.char})

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Literal) and other.char == self.char

    def __hash__(self) -> int:
        return hash(("_Literal", self.char))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"LIT({self.char!r})"


class _CharClass:
    __slots__ = ("negated", "singles", "ranges")

    def __init__(
        self,
        negated: bool,
        singles: Iterable[str],
        ranges: Iterable[tuple[str, str]],
    ) -> None:
        self.negated = bool(negated)
        self.singles = frozenset(singles)
        self.ranges = tuple(sorted(ranges))

    def _contains_raw(self, char: str) -> bool:
        if char in self.singles:
            return True
        return any(low <= char <= high for low, high in self.ranges)

    def matches(self, char: str) -> bool:
        if char == SEPARATOR:
            return False
        return self._contains_raw(char) != self.negated

    def endpoints(self) -> frozenset[str]:
        found = set(self.singles)
        for low, high in self.ranges:
            found.add(low)
            found.add(high)
        return frozenset(found)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _CharClass)
            and other.negated == self.negated
            and other.singles == self.singles
            and other.ranges == self.ranges
        )

    def __hash__(self) -> int:
        return hash(("_CharClass", self.negated, self.singles, self.ranges))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CLASS(neg={self.negated}, singles={sorted(self.singles)}, ranges={self.ranges})"


STAR = _Star()
ANY_CHAR = _AnyChar()


def _parse_class(text: str, start: int) -> tuple[_CharClass, int] | None:
    """Parse a bracket expression starting at ``text[start] == '['``.

    Returns ``None`` for an unterminated bracket, which POSIX ``fnmatch`` and
    git both treat as a literal ``[``.
    """
    index = start + 1
    length = len(text)
    negated = False
    if index < length and text[index] in "!^":
        negated = True
        index += 1

    singles: set[str] = set()
    ranges: list[tuple[str, str]] = []
    first = True
    while index < length:
        char = text[index]
        if char == "]" and not first:
            return _CharClass(negated, singles, ranges), index + 1
        first = False
        if char == "\\" and index + 1 < length:
            char = text[index + 1]
            index += 2
        else:
            index += 1
        if index < length and text[index] == "-" and index + 1 < length and text[index + 1] != "]":
            high = text[index + 1]
            if high == "\\" and index + 2 < length:
                high = text[index + 2]
                index += 3
            else:
                index += 2
            if high < char:
                raise GlobSyntaxError(f"inverted character range [{char}-{high}] in {text!r}")
            ranges.append((char, high))
        else:
            singles.add(char)
    return None


def compile_segment(text: str) -> tuple[object, ...]:
    """Compile one path segment pattern into a character-level item sequence."""
    if SEPARATOR in text:
        raise GlobSyntaxError(f"segment pattern must not contain {SEPARATOR!r}: {text!r}")
    items: list[object] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            if index + 1 >= length:
                raise GlobSyntaxError(f"dangling escape in segment {text!r}")
            items.append(_Literal(text[index + 1]))
            index += 2
            continue
        if char == "*":
            if not items or items[-1] is not STAR:
                items.append(STAR)
            index += 1
            continue
        if char == "?":
            items.append(ANY_CHAR)
            index += 1
            continue
        if char == "[":
            parsed = _parse_class(text, index)
            if parsed is None:
                items.append(_Literal("["))
                index += 1
                continue
            char_class, index = parsed
            items.append(char_class)
            continue
        items.append(_Literal(char))
        index += 1
    return tuple(items)


def _segment_closure(items: Sequence[object], positions: Iterable[int]) -> frozenset[int]:
    reached = set(positions)
    pending = list(reached)
    while pending:
        position = pending.pop()
        if position < len(items) and items[position] is STAR:
            if position + 1 not in reached:
                reached.add(position + 1)
                pending.append(position + 1)
    return frozenset(reached)


def segment_matches(items: Sequence[object], text: str) -> bool:
    positions = _segment_closure(items, {0})
    for char in text:
        advanced: set[int] = set()
        for position in positions:
            if position >= len(items):
                continue
            item = items[position]
            if item is STAR:
                if char != SEPARATOR:
                    advanced.add(position)
            elif item.matches(char):  # type: ignore[union-attr]
                advanced.add(position + 1)
        if not advanced:
            return False
        positions = _segment_closure(items, advanced)
    return len(items) in positions


def _candidate_chars(*item_sequences: Sequence[object]) -> tuple[str, ...]:
    """Return a witness-complete candidate alphabet for the given patterns.

    Every predicate here denotes a finite union of codepoint intervals or the
    complement of one.  Intersecting two such sets yields another finite union of
    intervals whose endpoints are endpoints of the inputs, or those endpoints
    shifted by one when a complement is involved.  Testing the mentioned
    endpoints, their immediate neighbours and one codepoint outside every
    mentioned range therefore cannot miss a non-empty intersection.
    """
    endpoints: set[str] = set()
    for items in item_sequences:
        for item in items:
            if item is STAR:
                continue
            endpoints |= item.endpoints()  # type: ignore[union-attr]

    candidates: list[str] = []
    seen: set[str] = set()
    for char in _SENTINEL_CHARS:
        if char not in seen:
            seen.add(char)
            candidates.append(char)
    extra: set[str] = set()
    for char in endpoints:
        extra.add(char)
        code = ord(char)
        if code > 0:
            extra.add(chr(code - 1))
        if code < MAX_CODEPOINT:
            extra.add(chr(code + 1))
    for char in sorted(extra):
        if char not in seen:
            seen.add(char)
            candidates.append(char)
    return tuple(char for char in candidates if char != SEPARATOR)


def _witness_char(left: object, right: object, candidates: Sequence[str]) -> str | None:
    for char in candidates:
        if left.matches(char) and right.matches(char):  # type: ignore[union-attr]
            return char
    return None


def _segment_step_options(items: Sequence[object], position: int) -> tuple[tuple[object, int], ...]:
    if position >= len(items):
        return ()
    item = items[position]
    if item is STAR:
        return ((ANY_CHAR, position),)
    return ((item, position + 1),)


def segment_intersection_witness(
    left: Sequence[object], right: Sequence[object]
) -> str | None:
    """Return the shortest non-empty string matched by both segment patterns.

    Path segments are never empty, so an empty common match does not count as an
    overlap.  The search is a breadth-first walk of the product NFA, which keeps
    the state space at ``(len(left) + 1) * (len(right) + 1) * 2``.
    """
    candidates = _candidate_chars(left, right)
    start = (0, 0, False)
    goal = (len(left), len(right), True)
    parents: dict[tuple[int, int, bool], tuple[tuple[int, int, bool], str | None] | None] = {
        start: None
    }
    queue = deque([start])
    while queue:
        state = queue.popleft()
        if state == goal:
            return _rebuild_segment_witness(parents, state)
        left_pos, right_pos, started = state
        for successor in _epsilon_successors(left, right, left_pos, right_pos, started):
            if successor not in parents:
                parents[successor] = (state, None)
                queue.append(successor)
        for left_pred, next_left in _segment_step_options(left, left_pos):
            for right_pred, next_right in _segment_step_options(right, right_pos):
                char = _witness_char(left_pred, right_pred, candidates)
                if char is None:
                    continue
                successor = (next_left, next_right, True)
                if successor not in parents:
                    parents[successor] = (state, char)
                    queue.append(successor)
    return None


def _epsilon_successors(
    left: Sequence[object],
    right: Sequence[object],
    left_pos: int,
    right_pos: int,
    started: bool,
) -> tuple[tuple[int, int, bool], ...]:
    successors: list[tuple[int, int, bool]] = []
    if left_pos < len(left) and left[left_pos] is STAR:
        successors.append((left_pos + 1, right_pos, started))
    if right_pos < len(right) and right[right_pos] is STAR:
        successors.append((left_pos, right_pos + 1, started))
    return tuple(successors)


def _rebuild_segment_witness(
    parents: dict[tuple[int, int, bool], tuple[tuple[int, int, bool], str | None] | None],
    state: tuple[int, int, bool],
) -> str:
    chars: list[str] = []
    cursor: tuple[int, int, bool] | None = state
    while cursor is not None:
        entry = parents[cursor]
        if entry is None:
            break
        previous, char = entry
        if char is not None:
            chars.append(char)
        cursor = previous
    return "".join(reversed(chars))


def normalize_path(raw: object) -> tuple[str, ...]:
    """Validate a changed path and split it into segments.

    The checks reject the shapes that let a writer smuggle a path past a naive
    prefix comparison: absolute paths, drive letters, backslash separators,
    ``.``/``..`` segments, repeated separators, trailing separators and control
    characters.
    """
    if not isinstance(raw, str) or raw == "":
        raise PathSyntaxError("path must be a non-empty string")
    if "\x00" in raw:
        raise PathSyntaxError("path contains a NUL byte")
    for char in raw:
        if char in _CONTROL_CHARS:
            raise PathSyntaxError(f"path contains control character {ord(char):#04x}")
    if "\\" in raw:
        raise PathSyntaxError("path contains a backslash; only '/' separates changed paths")
    if raw.startswith(SEPARATOR):
        raise PathSyntaxError("path is absolute")
    if len(raw) >= 2 and raw[1] == ":":
        raise PathSyntaxError("path carries a drive letter")
    if raw.startswith('"') or raw.endswith('"'):
        raise PathSyntaxError("path looks git-quoted; read changed paths with -z instead")
    if raw.endswith(SEPARATOR):
        raise PathSyntaxError("path ends with a separator and so names a directory")
    segments = tuple(raw.split(SEPARATOR))
    for segment in segments:
        if segment == "":
            raise PathSyntaxError("path contains an empty segment")
        if segment == ".":
            raise PathSyntaxError("path contains a '.' segment")
        if segment == "..":
            raise PathSyntaxError("path contains a '..' traversal segment")
    return segments


def is_nfc(raw: str) -> bool:
    return unicodedata.normalize("NFC", raw) == raw


class PathGlob:
    """An anchored git-style pathspec glob."""

    __slots__ = ("pattern", "tokens")

    DOUBLE_STAR = "**"

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self.tokens = self._compile(pattern)

    @staticmethod
    def _compile(pattern: object) -> tuple[object, ...]:
        if not isinstance(pattern, str) or pattern == "":
            raise GlobSyntaxError("pattern must be a non-empty string")
        if pattern.startswith(SEPARATOR):
            raise GlobSyntaxError(f"pattern must be repository-root relative: {pattern!r}")
        if pattern.endswith(SEPARATOR):
            raise GlobSyntaxError(
                f"pattern must not end with {SEPARATOR!r}; write 'dir/**' to own a subtree: {pattern!r}"
            )
        tokens: list[object] = []
        for part in pattern.split(SEPARATOR):
            if part == "":
                raise GlobSyntaxError(f"pattern contains an empty segment: {pattern!r}")
            if part == PathGlob.DOUBLE_STAR:
                if tokens and tokens[-1] is PathGlob.DOUBLE_STAR:
                    continue
                tokens.append(PathGlob.DOUBLE_STAR)
                continue
            if PathGlob.DOUBLE_STAR in part:
                raise GlobSyntaxError(
                    f"'**' is only meaningful as a whole segment: {pattern!r}"
                )
            if part in (".", ".."):
                raise GlobSyntaxError(f"pattern contains a relative segment: {pattern!r}")
            tokens.append(compile_segment(part))
        if not tokens:
            raise GlobSyntaxError(f"pattern compiled to nothing: {pattern!r}")
        if tokens[-1] is PathGlob.DOUBLE_STAR:
            tokens[-1] = compile_segment("*")
            tokens.append(PathGlob.DOUBLE_STAR)
        return tuple(tokens)

    def _token_closure(self, positions: Iterable[int]) -> frozenset[int]:
        reached = set(positions)
        pending = list(reached)
        while pending:
            position = pending.pop()
            if position < len(self.tokens) and self.tokens[position] is PathGlob.DOUBLE_STAR:
                if position + 1 not in reached:
                    reached.add(position + 1)
                    pending.append(position + 1)
        return frozenset(reached)

    def matches(self, path: object) -> bool:
        segments = path if isinstance(path, tuple) else normalize_path(path)
        positions = self._token_closure({0})
        for segment in segments:
            advanced: set[int] = set()
            for position in positions:
                if position >= len(self.tokens):
                    continue
                token = self.tokens[position]
                if token is PathGlob.DOUBLE_STAR:
                    advanced.add(position)
                elif segment_matches(token, segment):  # type: ignore[arg-type]
                    advanced.add(position + 1)
            if not advanced:
                return False
            positions = self._token_closure(advanced)
        return len(self.tokens) in positions

    def intersection_witness(self, other: "PathGlob") -> str | None:
        """Return a path matched by both globs, or ``None`` if none exists."""
        any_segment = compile_segment("*")
        cache: dict[tuple[int, int], str | None] = {}

        def joint_segment(left: object, right: object) -> str | None:
            key = (id(left), id(right))
            if key not in cache:
                cache[key] = segment_intersection_witness(left, right)  # type: ignore[arg-type]
            return cache[key]

        def step_options(tokens: Sequence[object], position: int) -> tuple[tuple[object, int], ...]:
            if position >= len(tokens):
                return ()
            token = tokens[position]
            if token is PathGlob.DOUBLE_STAR:
                return ((any_segment, position),)
            return ((token, position + 1),)

        left_tokens = self.tokens
        right_tokens = other.tokens
        start = (0, 0, False)
        goal = (len(left_tokens), len(right_tokens), True)
        parents: dict[
            tuple[int, int, bool], tuple[tuple[int, int, bool], str | None] | None
        ] = {start: None}
        queue = deque([start])
        while queue:
            state = queue.popleft()
            if state == goal:
                segments: list[str] = []
                cursor: tuple[int, int, bool] | None = state
                while cursor is not None:
                    entry = parents[cursor]
                    if entry is None:
                        break
                    previous, segment = entry
                    if segment is not None:
                        segments.append(segment)
                    cursor = previous
                return SEPARATOR.join(reversed(segments))
            left_pos, right_pos, started = state
            if left_pos < len(left_tokens) and left_tokens[left_pos] is PathGlob.DOUBLE_STAR:
                successor = (left_pos + 1, right_pos, started)
                if successor not in parents:
                    parents[successor] = (state, None)
                    queue.append(successor)
            if right_pos < len(right_tokens) and right_tokens[right_pos] is PathGlob.DOUBLE_STAR:
                successor = (left_pos, right_pos + 1, started)
                if successor not in parents:
                    parents[successor] = (state, None)
                    queue.append(successor)
            for left_pred, next_left in step_options(left_tokens, left_pos):
                for right_pred, next_right in step_options(right_tokens, right_pos):
                    segment = joint_segment(left_pred, right_pred)
                    if segment is None:
                        continue
                    successor = (next_left, next_right, True)
                    if successor not in parents:
                        parents[successor] = (state, segment)
                        queue.append(successor)
        return None

    def intersects(self, other: "PathGlob") -> bool:
        return self.intersection_witness(other) is not None

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PathGlob) and other.pattern == self.pattern

    def __hash__(self) -> int:
        return hash(("PathGlob", self.pattern))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PathGlob({self.pattern!r})"


def compile_globs(patterns: Iterable[str]) -> tuple[PathGlob, ...]:
    return tuple(PathGlob(pattern) for pattern in patterns)


def first_match(globs: Iterable[PathGlob], segments: tuple[str, ...]) -> PathGlob | None:
    for glob in globs:
        if glob.matches(segments):
            return glob
    return None
