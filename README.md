# worktree-gc

Fail-closed git worktree garbage collector (stdlib Python, zero dependencies).

Finds git worktrees under a set of roots, classifies each as
`reclaimable` / `protected` / `dirty` / `unmerged`, and — only in `--fix`
mode — removes the provably-merged ones via `git worktree remove`.

The design is **fail-closed**: if any worktree cannot be inspected, no removal
happens.

## Usage

```bash
python -m worktree_gc --roots ~/projects ~/_worktrees       # report only
python -m worktree_gc --roots ~/_worktrees --fix             # remove reclaimable
```

## License

MIT.
