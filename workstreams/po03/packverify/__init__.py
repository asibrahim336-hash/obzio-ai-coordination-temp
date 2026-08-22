"""Independent, dependency-free qualification of immutable operator packs."""

from .git_tree import GitTree, GitTreeError

__all__ = ["GitTree", "GitTreeError"]
