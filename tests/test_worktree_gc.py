import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from worktree_gc.core import Worktree, decide, find_worktrees, inspect, remove


class TestDecide(unittest.TestCase):
    def test_dirty(self):
        self.assertEqual(decide("feat/x", clean=False, merged=True, open_pr=False), "dirty")

    def test_reserved_protected(self):
        self.assertEqual(decide("main", clean=True, merged=True, open_pr=False), "protected")
        self.assertEqual(decide("HEAD", clean=True, merged=True, open_pr=False), "protected")

    def test_unmerged(self):
        self.assertEqual(decide("feat/x", clean=True, merged=False, open_pr=False), "unmerged")

    def test_open_pr_protected(self):
        self.assertEqual(decide("feat/x", clean=True, merged=True, open_pr=True), "protected")

    def test_reclaimable(self):
        self.assertEqual(decide("feat/x", clean=True, merged=True, open_pr=False), "reclaimable")


class TestRemoveGuard(unittest.TestCase):
    def test_remove_refuses_non_reclaimable(self):
        wt = Worktree(Path("."), "main", clean=True, merged=True, open_pr=False)
        ok, _ = remove(wt)
        self.assertFalse(ok)


class TestGitIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = Path(self.tmp) / "repo"
        self.repo.mkdir()
        run = lambda *a: subprocess.run(["git", *a], cwd=self.repo, capture_output=True, text=True, check=True)
        run("init", "-b", "main")
        run("config", "user.email", "t@example.com")
        run("config", "user.name", "t")
        (self.repo / "f.txt").write_text("x")
        run("add", "f.txt")
        run("commit", "-m", "init")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detect_and_classify_worktree(self):
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-b", "feat/x", "wt"], check=True, capture_output=True)
        paths = find_worktrees([self.repo])
        self.assertIn(self.repo / "wt", paths)
        wt = inspect(self.repo / "wt")
        self.assertIsNotNone(wt)
        self.assertEqual(wt.branch, "feat/x")
        self.assertTrue(wt.clean)
        self.assertFalse(wt.merged)  # branch tip not merged into main
        self.assertEqual(decide(wt.branch, wt.clean, wt.merged, wt.open_pr), "unmerged")


if __name__ == "__main__":
    unittest.main()
