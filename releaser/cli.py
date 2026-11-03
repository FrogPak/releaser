"""Command line: releaser plan | notes."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import project, versions

DEFAULT_RUNNERS = {"x86_64": "ubuntu-latest", "aarch64": "ubuntu-26.04-arm"}


def output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as out:
            out.write(f"{name}={value}\n")
    print(f"{name}={value}")


def error(message):
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error::{message}", file=sys.stderr)
    else:
        print(f"error: {message}", file=sys.stderr)


def notice(message):
    prefix = "::notice::" if os.environ.get("GITHUB_ACTIONS") == "true" else "notice: "
    print(prefix + message, file=sys.stderr)


def tag_exists(tag, root):
    result = subprocess.run(["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"],
                            cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise project.ProjectError(f"cannot list tags: {result.stderr.strip()}")
    return bool(result.stdout.strip())


def matrix(arches_text, runners_text):
    runners = dict(DEFAULT_RUNNERS)
    for line in (runners_text or "").splitlines():
        arch, sep, runner = line.partition(":")
        if sep and arch.strip() and runner.strip():
            runners[arch.strip()] = runner.strip()
    include = []
    for arch in (arches_text or "x86_64 aarch64").replace(",", " ").split():
        if arch not in runners:
            raise project.ProjectError(f"no runner known for {arch}; add it to the runners input as '{arch}: <label>'")
        include.append({"arch": arch, "runner": runners[arch]})
    return {"include": include}


def plan(args, exists=tag_exists):
    root = Path(args.root)
    manifest = project.find_manifest(root, args.manifest)
    metainfo = project.find_metainfo(root, manifest.app_id, args.metainfo)
    releases = project.read_releases(metainfo) if metainfo else None
    if metainfo and releases is None:
        notice(f"{metainfo.relative_to(root)} keeps its releases in a separate file; push a tag to release")
    newest = releases[0] if releases else None
    found = versions.read(root, versions.parse_spec(args.version_files))
    source = str(metainfo.relative_to(root)) if metainfo else ""

    version, release, prerelease = "", False, False
    prefix = args.tag_prefix
    if args.ref.startswith("refs/tags/"):
        tag = args.ref.removeprefix("refs/tags/")
        if not tag.startswith(prefix):
            notice(f"tag {tag} does not start with {prefix}; not a release")
        else:
            version = tag.removeprefix(prefix)
            prerelease = "-" in version or bool(newest and newest.version == version and newest.development)
            if newest and not prerelease and newest.version != version:
                raise versions.VersionError(f"tag {tag} does not match the newest release in {source}, "
                                            f"{newest.version}")
            versions.check(found, version, f"tag {tag}")
            release = True
    elif newest:
        version = newest.version
        tag = prefix + version
        prerelease = newest.development or "-" in version
        versions.check(found, version, source)
        if args.event == "push" and args.ref == f"refs/heads/{args.default_branch}":
            release = not exists(tag, root)
            if not release:
                notice(f"{tag} already exists; nothing to release")
    else:
        versions.check(found, None, "")
        tag = ""

    output("app-id", manifest.app_id)
    output("app-name", manifest.name)
    output("branch", manifest.branch)
    output("manifest", str(manifest.path.relative_to(root)))
    output("metainfo", source)
    output("version", version)
    output("tag", tag if version else "")
    output("release", str(release).lower())
    output("prerelease", str(prerelease).lower())
    output("build", str(release or args.event == "workflow_dispatch").lower())
    output("matrix", json.dumps(matrix(args.arches, args.runners)))
    return 0


def notes(args):
    text = ""
    if args.metainfo:
        for entry in project.read_releases(Path(args.root) / args.metainfo) or []:
            if entry.version == args.version:
                text = entry.notes
                break
    Path(args.output).write_text(text + "\n" if text else "")
    print(text or "(no notes in metainfo)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="releaser")
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("plan", help="check versions and decide whether to release")
    p.add_argument("--root", default=".")
    p.add_argument("--event", required=True)
    p.add_argument("--ref", required=True)
    p.add_argument("--default-branch", default="main")
    p.add_argument("--manifest", default="")
    p.add_argument("--metainfo", default="")
    p.add_argument("--version-files", default=os.environ.get("VERSION_FILES", ""))
    p.add_argument("--tag-prefix", default="v")
    p.add_argument("--arches", default="x86_64 aarch64")
    p.add_argument("--runners", default=os.environ.get("RUNNERS", ""))

    n = commands.add_parser("notes", help="write a release's notes from metainfo as Markdown")
    n.add_argument("--root", default=".")
    n.add_argument("--metainfo", default="")
    n.add_argument("--version", required=True)
    n.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    try:
        return plan(args) if args.command == "plan" else notes(args)
    except (project.ProjectError, versions.VersionError) as problem:
        error(str(problem))
        return 1
