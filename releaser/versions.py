"""Opt-in cross-checks: other files that also state the version."""
import re
from pathlib import Path


class VersionError(Exception):
    pass


def parse_spec(text):
    """Lines of 'path: regex'; the regex's first group captures the version."""
    specs = []
    for number, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        path, sep, pattern = line.partition(": ")
        if not sep or not pattern:
            raise VersionError(f"version-files line {number}: expected 'path: regex', got {line!r}")
        try:
            regex = re.compile(pattern.strip(), re.MULTILINE)
        except re.error as error:
            raise VersionError(f"version-files line {number}: bad regex: {error}") from None
        if regex.groups < 1:
            raise VersionError(f"version-files line {number}: the regex needs a (group) around the version")
        specs.append((path.strip(), regex))
    return specs


def read(root, specs):
    """Maps each path to the version found in it; problems are raised together."""
    found, problems = {}, []
    for path, regex in specs:
        file = Path(root) / path
        try:
            text = file.read_text()
        except OSError:
            problems.append(f"{path} does not exist")
            continue
        match = regex.search(text)
        if not match:
            problems.append(f"{path}: no line matches {regex.pattern}")
            continue
        found[path] = match.group(1).strip()
    if problems:
        raise VersionError("; ".join(problems))
    return found


def check(found, expected, source):
    """Raises when any file disagrees with expected, or with each other when nothing is expected."""
    if expected is None:
        if len(set(found.values())) > 1:
            listing = ", ".join(f"{p} says {v}" for p, v in found.items())
            raise VersionError(f"version files disagree: {listing}")
        return
    wrong = [f"{p} says {v}" for p, v in found.items() if v != expected]
    if wrong:
        raise VersionError(f"{source} says {expected}, but " + ", ".join(wrong))
