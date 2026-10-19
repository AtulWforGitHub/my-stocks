#!/usr/bin/env python3
"""ONE-COMMAND upload to GitHub (so the free cloud job and website can run for you).

1) In your browser create an EMPTY public repository (github.com > New repository, no README). Copy its https URL.
2) Run:   py -3.12 scripts\\publish_to_github.py https://github.com/YOUR_NAME/YOUR_REPO.git

It uploads the project including your saved progress (state/ and docs/). It uploads research data only: your holdings are
stored in your browser and are never part of this folder. If the GitHub CLI (gh) is installed and signed in, it also turns on
Pages, the write permission and the first run; otherwise it prints the three clicks needed.
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*args, check=True, capture=False):
    r = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=capture)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{(r.stderr or r.stdout or '').strip()}")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo_url"); ap.add_argument("--branch", default="main"); ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    a = ap.parse_args()
    if not shutil.which("git"):
        sys.exit("Git is not installed. Install 'Git for Windows' from https://git-scm.com, reopen PowerShell, and run this again.")
    if not a.yes:
        print("This uploads this folder (code, settings, data/governance_flags.csv, state/, docs/) to a PUBLIC repository.")
        print("Your portfolio holdings are NOT in this folder (they live in your browser). Do not put secrets in config.yaml.")
        if input("Type YES to continue: ").strip() != "YES":
            sys.exit("Cancelled.")
    if not (ROOT / ".git").exists():
        if git("init", "-b", a.branch, check=False).returncode != 0:
            git("init"); git("checkout", "-B", a.branch)
    if not git("config", "user.name", check=False, capture=True).stdout.strip():
        git("config", "user.name", "MIS user"); git("config", "user.email", "mis-user@users.noreply.github.com")
    git("add", "-A")
    if git("diff", "--cached", "--quiet", check=False).returncode != 0:
        git("commit", "-q", "-m", "MIS update")
    else:
        print("Nothing new to commit.")
    if git("remote", "get-url", "origin", check=False, capture=True).returncode == 0:
        git("remote", "set-url", "origin", a.repo_url)
    else:
        git("remote", "add", "origin", a.repo_url)
    print("Uploading... (a browser window may open asking you to sign in to GitHub)")
    git("push", "-u", "origin", f"HEAD:{a.branch}")
    print("Uploaded.")

    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", a.repo_url)
    if not m:
        return
    owner, repo = m.groups()
    manual = [f"1. Turn on the website: https://github.com/{owner}/{repo}/settings/pages  -> Deploy from a branch -> main -> /docs -> Save",
              f"2. Allow the job to save: https://github.com/{owner}/{repo}/settings/actions  -> Workflow permissions -> Read and write -> Save",
              f"3. Run it once: https://github.com/{owner}/{repo}/actions  -> Update dashboard -> Run workflow"]
    ok = False
    if shutil.which("gh") and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0:
        steps = [["gh", "api", "-X", "PUT", f"repos/{owner}/{repo}/actions/permissions/workflow", "-f", "default_workflow_permissions=write"],
                 ["gh", "api", "-X", "POST", f"repos/{owner}/{repo}/pages", "-f", "build_type=legacy", "-f", f"source[branch]={a.branch}", "-f", "source[path]=/docs"],
                 ["gh", "workflow", "run", "daily.yml", "-R", f"{owner}/{repo}"]]
        results = [subprocess.run(c, capture_output=True, text=True).returncode == 0 for c in steps]
        ok = all(results)
        print("Automatic setup:", ["write permission", "Pages", "first run"], results)
    if ok:
        print(f"\nAll set. Your site will be at https://{owner.lower()}.github.io/{repo}/ in a few minutes (the first run takes 10-30 minutes).")
    else:
        print("\nThree clicks left (they cannot be done from a script without a GitHub token):")
        print("\n".join(manual))
        print(f"\nThen your site is https://{owner.lower()}.github.io/{repo}/")


if __name__ == "__main__":
    main()
