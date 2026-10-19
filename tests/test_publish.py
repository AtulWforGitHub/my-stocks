"""The publish step is tested against real local git repositories (a bare 'remote', the job's clone, and a second clone that plays you)."""
import os, shutil, subprocess, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "publish.sh"


def sh(cmd, cwd, check=True, env=None):
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, check=check, env=env)


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "git/bash needed")
class TestPublish(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        sh("git init -q --bare remote.git", self.d)
        ident = "git config user.email t@t && git config user.name t"
        sh(f"git clone -q remote.git runner 2>/dev/null; cd runner && {ident} && mkdir -p docs state && echo old > docs/index.html && touch state/.gitkeep && git add . && git commit -qm init && git branch -M main && git push -q -u origin main", self.d)
        sh(f"git clone -q remote.git user 2>/dev/null; cd user && {ident}", self.d)
        self.runner, self.user = self.d / "runner", self.d / "user"

    def remote_file(self, path):
        return sh(f"git --git-dir=remote.git show main:{path}", self.d).stdout.strip()

    def test_publishes_when_remote_unchanged(self):
        (self.runner / "docs" / "index.html").write_text("NEW")
        sh(f"bash {SCRIPT}", self.runner)
        self.assertEqual(self.remote_file("docs/index.html"), "NEW")

    def test_publishes_even_when_remote_moved_during_the_run(self):
        sh("git pull -q origin main && echo 'owner_email: x' > config.yaml && git add . && git commit -qm 'edit on github' && git push -q origin HEAD:main", self.user)
        (self.runner / "docs" / "index.html").write_text("NEW REPORT")
        sh(f"bash {SCRIPT}", self.runner)
        self.assertEqual(self.remote_file("docs/index.html"), "NEW REPORT")          # the old script silently left this as 'old'
        self.assertEqual(self.remote_file("config.yaml"), "owner_email: x")           # and your edit is preserved

    def test_nothing_to_publish_is_success(self):
        r = sh(f"bash {SCRIPT}", self.runner); self.assertIn("Nothing new", r.stdout)

    def test_failure_is_loud_not_silent(self):
        hook = self.d / "remote.git" / "hooks" / "pre-receive"; hook.write_text("#!/bin/sh\nexit 1\n"); hook.chmod(0o755)
        (self.runner / "docs" / "index.html").write_text("NEW")
        env = dict(os.environ); r = subprocess.run(["bash", "-c", f"sleep() {{ :; }}; export -f sleep; bash {SCRIPT}"], cwd=self.runner, capture_output=True, text=True, env=env)
        self.assertNotEqual(r.returncode, 0); self.assertIn("NOT updated", r.stderr)



@unittest.skipUnless(shutil.which("git"), "git needed")
class TestPublishToGithubScript(unittest.TestCase):
    """The one-command upload, tested against a local bare repository standing in for GitHub."""

    def setUp(self):
        import sys as _sys
        self.py = _sys.executable
        self.d = Path(tempfile.mkdtemp()); sh("git init -q --bare remote.git", self.d)
        self.proj = self.d / "proj"; (self.proj / "scripts").mkdir(parents=True); (self.proj / ".venv").mkdir(); (self.proj / "state").mkdir()
        shutil.copy(SCRIPT.parent / "publish_to_github.py", self.proj / "scripts" / "publish_to_github.py")
        (self.proj / "a.txt").write_text("v1"); (self.proj / ".gitignore").write_text(".venv/\n"); (self.proj / ".venv" / "junk").write_text("x"); (self.proj / "state" / "cache.json").write_text("{}")

    def run_script(self, *extra):
        return subprocess.run([self.py, str(self.proj / "scripts" / "publish_to_github.py"), str(self.d / "remote.git"), "--yes", *extra], cwd=self.proj, capture_output=True, text=True)

    def remote_files(self):
        return sh("git --git-dir=remote.git ls-tree -r --name-only main", self.d).stdout.split()

    def test_first_upload_second_upload_and_nothing_changed(self):
        r = self.run_script(); self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        files = self.remote_files(); self.assertIn("a.txt", files); self.assertIn("state/cache.json", files); self.assertNotIn(".venv/junk", files)   # progress uploaded, environment not
        (self.proj / "a.txt").write_text("v2"); self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(sh("git --git-dir=remote.git show main:a.txt", self.d).stdout.strip(), "v2")
        again = self.run_script(); self.assertEqual(again.returncode, 0); self.assertIn("Nothing new", again.stdout)

    def test_confirmation_is_required_without_yes(self):
        r = subprocess.run([self.py, str(self.proj / "scripts" / "publish_to_github.py"), str(self.d / "remote.git")], cwd=self.proj, input="no\n", capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        has_main = sh("git --git-dir=remote.git rev-parse --verify -q main", self.d, check=False).returncode == 0
        self.assertFalse(has_main, "nothing may be uploaded without confirmation")


if __name__ == "__main__":
    unittest.main()
