"""git_sources: the app repo at a commit, the deploy repo from a temp clone."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/readiness/scripts"))

import git_sources as g  # noqa: E402
from tests.readiness import fixtures as fx  # noqa: E402


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tmp = Path(self._t.name)

    def sub(self, name: str) -> Path:
        p = self.tmp / name
        p.mkdir()
        return p


class SlugTest(unittest.TestCase):
    def test_forms(self):
        for url in ("git@github.com:arigsela/hk-demo.git", "https://github.com/arigsela/hk-demo",
                    "https://github.com/arigsela/hk-demo.git", "ssh://git@github.com/arigsela/hk-demo.git"):
            self.assertEqual(g.slug_from_remote(url), "arigsela/hk-demo", url)

    def test_not_github(self):
        self.assertIsNone(g.slug_from_remote("https://gitlab.com/a/b.git"))

    def test_github_url(self):
        self.assertEqual(g.github_url("a/b"), "https://github.com/a/b.git")


class ExportTest(TmpCase):
    def test_committed_only(self):
        repo = fx.git_repo(self.sub("w"), {"a.txt": "committed\n"})
        (repo / "a.txt").write_text("dirty\n")
        (repo / "app-token.txt").write_text("secret\n")
        dest = self.sub("out")
        g.export_commit(repo, fx.git(repo, "rev-parse", "HEAD"), dest)
        self.assertEqual((dest / "a.txt").read_text(), "committed\n")
        self.assertFalse((dest / "app-token.txt").exists())


class RefInfoTest(TmpCase):
    def clone(self, url: str) -> Path:
        d = self.sub("clone")
        fx.git(self.tmp, "clone", "--quiet", url, str(d))
        return d

    def advance_origin(self, url: str) -> None:
        up = self.sub("up")
        fx.git(self.tmp, "clone", "--quiet", url, str(up))
        fx.commit_files(up, {"c": "3"})
        fx.git(up, "push", "--quiet", "origin", "main")

    def test_at_origin_main(self):
        url = fx.bare_remote(self.sub("r"), {"a": "1"})
        info = g.app_ref_info(self.clone(url))
        self.assertIs(info["on_default_branch"], True)
        self.assertEqual(info["branch"], "main")
        self.assertEqual(info["default_branch"], "main")
        self.assertEqual(info["sha"], fx.git(Path(info["path"]), "rev-parse", "HEAD"))

    def test_feature_branch_with_main_local(self):
        url = fx.bare_remote(self.sub("r"), {"a": "1"})
        c = self.clone(url)
        fx.git(c, "checkout", "--quiet", "-b", "feat/x")
        fx.commit_files(c, {"b": "2"})
        self.advance_origin(url)
        fx.git(c, "fetch", "--quiet", "origin")  # main's new sha is now present locally
        info = g.app_ref_info(c)
        self.assertEqual(info["branch"], "feat/x")
        self.assertIs(info["on_default_branch"], False)
        self.assertIsNone(info["slug"])  # a file:// remote is not GitHub

    def test_default_sha_absent_locally(self):
        url = fx.bare_remote(self.sub("r"), {"a": "1"})
        c = self.clone(url)
        fx.git(c, "checkout", "--quiet", "-b", "feat/x")
        fx.commit_files(c, {"b": "2"})
        self.advance_origin(url)  # no fetch in c
        self.assertIsNone(g.app_ref_info(c)["on_default_branch"])


class RemoteCheckoutTest(TmpCase):
    def test_branch_and_head(self):
        url = fx.bare_remote(self.sub("r"), {"a.txt": "main\n"}, {"dev": {"a.txt": "dev\n"}})
        d = self.sub("d")
        sha = g.remote_checkout(url, "main", d)
        self.assertEqual(sha, fx.git(d, "rev-parse", "HEAD"))
        self.assertEqual((d / "a.txt").read_text(), "main\n")
        d2 = self.sub("d2")
        g.remote_checkout(url, "HEAD", d2)
        self.assertEqual((d2 / "a.txt").read_text(), "main\n")
        d3 = self.sub("d3")
        g.remote_checkout(url, "dev", d3)
        self.assertEqual((d3 / "a.txt").read_text(), "dev\n")
        self.assertEqual(g.default_branch(url), "main")


if __name__ == "__main__":
    unittest.main()
