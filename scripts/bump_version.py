#!/usr/bin/env python3
"""Automated Semantic Versioning Bumper for yt-vd based on Conventional Commits.

Analyzes commit messages since the last git tag to determine the next version:
- BREAKING CHANGE / feat!: -> Major bump (x.0.0)
- feat: -> Minor bump (x.y.0)
- fix: / refactor: / perf: / chore: / etc. -> Patch bump (x.y.z)
"""

import re
import subprocess
import sys
from pathlib import Path


def run_git(args: list[str]) -> str:
    """Helper to execute git commands safely."""
    try:
        res = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Git command failed: {' '.join(args)} - {e.stderr.strip()}", file=sys.stderr)
        return ""


def get_latest_tag() -> str:
    """Retrieve the latest git tag matching version patterns."""
    tag = run_git(["describe", "--tags", "--abbrev=0"])
    return tag


def get_commits_since(tag: str) -> list[str]:
    """Retrieve all commit messages since the specified tag."""
    if tag:
        commits_range = f"{tag}..HEAD"
        commits = run_git(["log", commits_range, "--format=%s"])
    else:
        commits = run_git(["log", "--format=%s"])
    return [c.strip() for c in commits.splitlines() if c.strip()]


def determine_bump_type(commits: list[str]) -> str:
    """Analyze commit logs and return 'major', 'minor', 'patch', or 'none'."""
    if not commits:
        return "none"

    bump = "patch"  # Default fallback
    for commit in commits:
        # Check for breaking change markers
        if "BREAKING CHANGE" in commit or "!" in commit.split(":", 1)[0]:
            return "major"
        # Check for new features
        if commit.startswith("feat"):
            bump = "minor"
    return bump


def bump_version(current: str, bump_type: str) -> str:
    """Increment semantic version based on bump type."""
    parts = current.lstrip("v").split(".")
    if len(parts) < 3:
        parts += ["0"] * (3 - len(parts))
    major, minor, patch = map(int, parts[:3])

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return current


def update_pyproject_toml(new_version: str) -> None:
    """Write the new version back into pyproject.toml."""
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        print("Error: pyproject.toml not found!", file=sys.stderr)
        sys.exit(1)

    content = pyproject.read_text(encoding="utf-8")
    # Replace version = "X.Y.Z"
    new_content, count = re.subn(
        r'^version\s*=\s*["\'][^"\']+["\']',
        f'version = "{new_version}"',
        content,
        flags=re.MULTILINE
    )
    if count == 0:
        print("Warning: Could not find version line in pyproject.toml!", file=sys.stderr)
    pyproject.write_text(new_content, encoding="utf-8")
    print(f"Updated pyproject.toml version to {new_version}")


def main() -> None:
    # 1. Fetch tags to ensure we have context
    run_git(["fetch", "--tags"])

    # 2. Get latest tag and commits
    latest_tag = get_latest_tag()
    print(f"Latest git tag: {latest_tag or 'None'}")

    commits = get_commits_since(latest_tag)
    print(f"Found {len(commits)} commit(s) since last tag.")
    if commits:
        print("Commits analyzed:")
        for c in commits[:10]:
            print(f" - {c}")
        if len(commits) > 10:
            print(f" ... and {len(commits) - 10} more")

    # 3. Read current version from pyproject.toml
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        print("Error: pyproject.toml not found!", file=sys.stderr)
        sys.exit(1)

    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, flags=re.MULTILINE)
    if not match:
        print("Error: Could not extract version from pyproject.toml!", file=sys.stderr)
        sys.exit(1)
    current_version = match.group(1)
    print(f"Current version in pyproject.toml: {current_version}")

    # 4. Determine bump type
    bump_type = determine_bump_type(commits)
    print(f"Determined bump type: {bump_type}")

    if bump_type == "none":
        print("No new commits. Version bump skipped.")
        # Exit with a special output for Github actions if needed
        print(f"NEW_VERSION={current_version}")
        return

    # 5. Calculate new version
    new_version = bump_version(current_version, bump_type)
    print(f"New target version: {new_version}")

    # 6. Save new version
    update_pyproject_toml(new_version)
    print(f"NEW_VERSION={new_version}")


if __name__ == "__main__":
    main()
