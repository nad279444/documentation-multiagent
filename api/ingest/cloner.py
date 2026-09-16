"""STEP 2 — Repo cloning, with the input guardrails applied at the door.

Guardrails implemented here:
  * URL validation  — only public github.com repos, no arbitrary hosts
  * Size caps       — max files / max file size / max total MB
  * Secret scanning — files containing credential patterns are EXCLUDED
                      from the index entirely rather than redacted
  * Path confinement — everything stays under CLONE_DIR

Cloud Run's filesystem is ephemeral, so /tmp is the correct place to clone.
Callers should always call cleanup() when done.
"""

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from config import Settings, get_settings

logger = logging.getLogger(__name__)

# Only these extensions get indexed. Everything else is noise for doc generation.
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rb",
    ".java",
    ".rs",
    ".php",
    ".cs",
    ".kt",
    ".swift",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
}
DOC_EXTENSIONS = {".md", ".rst", ".txt"}

SKIP_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    "vendor",
    "target",
    ".next",
    ".nuxt",
    "coverage",
    ".pytest_cache",
    "site-packages",
}

# Deliberately conservative: a false positive costs one skipped file,
# a false negative means a live credential gets embedded into Pinecone.
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style keys
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key IDs
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),  # private keys
    re.compile(
        r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{16,}['\"]"
    ),
]


class IngestError(Exception):
    """Raised when a repo fails validation or cloning."""


@dataclass
class RepoFile:
    path: str  # repo-relative, e.g. "app/main.py"
    abs_path: Path
    text: str
    extension: str


@dataclass
class ClonedRepo:
    url: str
    commit_sha: str
    root: Path
    files: list[RepoFile] = field(default_factory=list)
    skipped_secrets: list[str] = field(default_factory=list)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def validate_repo_url(url: str) -> str:
    """Input guardrail: only accept public github.com repo URLs."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise IngestError("Repository URL must start with http:// or https://")
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise IngestError("Only public github.com repositories are supported")
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise IngestError("URL must be of the form https://github.com/<owner>/<repo>")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    clean = f"https://github.com/{owner}/{repo}.git"

    # Quick check via GitHub API that the repo exists and is not empty
    import urllib.request
    import json

    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        req = urllib.request.Request(api_url, headers={"Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("size", 0) == 0:
                raise IngestError(f"Repository {owner}/{repo} is empty")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise IngestError(f"Repository {owner}/{repo} not found or is private")
        # Other errors (rate limit, etc.) — let git clone try anyway
    except urllib.error.URLError:
        pass  # Network issue — let git clone try

    return clean


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def clone_repo(url: str, branch: str | None = None) -> ClonedRepo:
    """Shallow-clone a public repo and read its indexable files into memory."""
    settings = get_settings()
    clean_url = validate_repo_url(url)

    Path(settings.clone_dir).mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(dir=settings.clone_dir))

    cmd = ["git", "clone", "--depth", "1", "--single-branch"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [clean_url, str(workdir)]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise IngestError("Cloning timed out after 300s") from exc
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        stderr = exc.stderr.decode(errors="replace")[:400]
        raise IngestError(f"git clone failed: {stderr}") from exc

    sha = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    repo = ClonedRepo(url=clean_url, commit_sha=sha, root=workdir)
    _collect_files(repo, settings)
    logger.info(
        "Cloned %s @ %s — %d files indexed, %d skipped for secrets",
        clean_url,
        sha[:8],
        len(repo.files),
        len(repo.skipped_secrets),
    )
    return repo


def _collect_files(repo: ClonedRepo, settings: Settings) -> None:
    total_bytes = 0
    max_total = settings.max_repo_mb * 1024 * 1024
    allowed = CODE_EXTENSIONS | DOC_EXTENSIONS

    for path in sorted(repo.root.rglob("*")):
        if len(repo.files) >= settings.max_files:
            logger.warning("Hit max_files cap (%d); truncating", settings.max_files)
            break
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in allowed:
            continue

        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > settings.max_file_bytes or size == 0:
            continue
        if total_bytes + size > max_total:
            logger.warning(
                "Hit max_repo_mb cap (%d MB); truncating", settings.max_repo_mb
            )
            break

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        rel = str(path.relative_to(repo.root))

        # Guardrail: never index a file that contains what looks like a credential.
        if contains_secret(text):
            repo.skipped_secrets.append(rel)
            continue

        total_bytes += size
        repo.files.append(
            RepoFile(path=rel, abs_path=path, text=text, extension=path.suffix.lower())
        )


def changed_files(repo: ClonedRepo, since_sha: str | None) -> set[str] | None:
    """Diff-based incremental indexing: which files changed since the last run.

    Returns None when a full re-index is required (no previous SHA, or the
    shallow clone lacks the history needed to diff).
    """
    if not since_sha:
        return None
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(repo.root),
                "diff",
                "--name-only",
                since_sha,
                repo.commit_sha,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Shallow clone usually can't reach the old SHA — fall back to full re-index.
        return None
    return {line.strip() for line in out.splitlines() if line.strip()}
