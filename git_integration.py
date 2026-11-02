import os
import subprocess
from typing import List, Optional, Tuple


class GitManager:
    def __init__(self, repo_path: str, pat: Optional[str] = None):
        self.repo_path = os.path.abspath(repo_path) if repo_path else ""
        self.pat = pat

    def is_valid_repo(self) -> bool:
        if not self.repo_path or not os.path.exists(self.repo_path):
            return False
        return os.path.exists(os.path.join(self.repo_path, ".git"))

    def _run_git(self, args: List[str]) -> Tuple[int, str, str]:
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            return 1, "", str(e)

    def get_status(self) -> str:
        code, out, err = self._run_git(["status", "--short"])
        return out.strip() if code == 0 else f"Error: {err}"

    def get_current_branch(self) -> str:
        code, out, _ = self._run_git(["branch", "--show-current"])
        return out.strip() if code == 0 else "unknown"

    def pull(self) -> Tuple[bool, str]:
        code, out, err = self._run_git(["pull"])
        return (code == 0, out if code == 0 else err)

    def commit_and_push(self, commit_message: str, branch: Optional[str] = None) -> Tuple[bool, str]:
        # Add all changes
        c1, _, e1 = self._run_git(["add", "-A"])
        if c1 != 0:
            return False, f"Git add failed: {e1}"

        # Commit
        c2, out2, e2 = self._run_git(["commit", "-m", commit_message])
        if c2 != 0:
            if "nothing to commit" in out2 or "nothing to commit" in e2:
                return True, "Nothing to commit, working tree clean."
            return False, f"Git commit failed: {e2}"

        # Push
        target_branch = branch or self.get_current_branch()
        c3, out3, e3 = self._run_git(["push", "origin", target_branch])
        if c3 != 0:
            return False, f"Git push failed: {e3}"

        return True, f"Successfully pushed commit '{commit_message}' to branch '{target_branch}'"

    def get_repo_structure(self, max_depth: int = 3, max_files: int = 100) -> str:
        """Returns a tree-like string of files in the repo for Claude prompt context."""
        if not self.is_valid_repo():
            return "No valid repo loaded."

        lines = []
        ignored = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".cache"}
        count = 0

        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in ignored and not d.startswith(".")]
            depth = root[len(self.repo_path):].count(os.sep)
            if depth >= max_depth:
                continue

            rel_root = os.path.relpath(root, self.repo_path)
            prefix = "  " * depth
            if rel_root != ".":
                lines.append(f"{prefix}[DIR] {os.path.basename(root)}/")

            for f in sorted(files):
                if f.startswith(".") or f.endswith((".pyc", ".png", ".jpg", ".lock")):
                    continue
                lines.append(f"{prefix}  {f}")
                count += 1
                if count >= max_files:
                    lines.append(f"{prefix}  ... (truncated)")
                    return "\n".join(lines)

        return "\n".join(lines)
