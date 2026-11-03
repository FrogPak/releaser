import io
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from releaser import cli, project, versions

MANIFEST = {"app-id": "org.example.App", "runtime": "org.gnome.Platform", "modules": []}
METAINFO = """<?xml version="1.0"?>
<component type="desktop-application">
  <id>org.example.App</id>
  <releases>
{}
  </releases>
</component>
"""


def release(version, date, extra="", body=""):
    return f'    <release version="{version}" date="{date}" {extra}>{body}</release>'


class Repo:
    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def write(self, path, text):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
        return file

    def close(self):
        self.dir.cleanup()


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_manifest_json_and_yaml(self):
        self.repo.write("build-aux/org.example.App.json", json.dumps(MANIFEST))
        self.repo.write("build-aux/cargo-sources.json", "[]")
        manifest = project.find_manifest(self.repo.root)
        self.assertEqual((manifest.app_id, manifest.branch, manifest.name), ("org.example.App", "master", "App"))
        self.repo.write("build-aux/org.example.App.json", "{}")
        self.repo.write("flatpak/app.yml", "id: org.example.Other\nbranch: stable\nmodules: []\n")
        manifest = project.find_manifest(self.repo.root)
        self.assertEqual((manifest.app_id, manifest.branch), ("org.example.Other", "stable"))

    def test_manifest_ambiguous_or_missing(self):
        with self.assertRaisesRegex(project.ProjectError, "no Flatpak manifest"):
            project.find_manifest(self.repo.root)
        self.repo.write("a.json", json.dumps(MANIFEST))
        self.repo.write("b.json", json.dumps(MANIFEST))
        with self.assertRaisesRegex(project.ProjectError, "several manifests"):
            project.find_manifest(self.repo.root)
        self.assertEqual(project.find_manifest(self.repo.root, "b.json").path.name, "b.json")

    def test_metainfo_discovery(self):
        self.assertIsNone(project.find_metainfo(self.repo.root, "org.example.App"))
        self.repo.write("data/org.example.App.metainfo.xml.in.in", "<component/>")
        self.repo.write("build/org.example.App.metainfo.xml", "<component/>")
        found = project.find_metainfo(self.repo.root, "org.example.App")
        self.assertEqual(found.relative_to(self.repo.root).as_posix(), "data/org.example.App.metainfo.xml.in.in")

    def test_release_order_and_types(self):
        path = self.repo.write("m.xml", METAINFO.format("\n".join([
            release("1.1.0-rc1", "2026-11-03", 'type="development"'),
            release("1.0.0", "2026-11-01"),
        ])))
        releases = project.read_releases(path)
        self.assertEqual([(r.version, r.development) for r in releases], [("1.1.0-rc1", True), ("1.0.0", False)])
        self.repo.write("m.xml", METAINFO.format("\n".join([release("1.0.0", "2026-11-01"),
                                                            release("1.1.0", "2026-11-03")])))
        with self.assertRaisesRegex(project.ProjectError, "newest first"):
            project.read_releases(path)

    def test_timestamp_and_external(self):
        path = self.repo.write("m.xml", METAINFO.format(
            '    <release version="2.0" timestamp="1793000000"/>\n' + release("1.0", "2026-01-01")))
        self.assertEqual(project.read_releases(path)[0].version, "2.0")
        path = self.repo.write("e.xml", '<component><releases type="external"/></component>')
        self.assertIsNone(project.read_releases(path))

    def test_notes_markdown(self):
        body = ("<description><p>Fixes <em>many</em> bugs.</p><ul><li>One</li><li>Two "
                "<code>x</code></li></ul><ol><li>A</li></ol></description>")
        path = self.repo.write("m.xml", METAINFO.format(release("1.0", "2026-01-01", body=body)))
        self.assertEqual(project.read_releases(path)[0].notes,
                         "Fixes *many* bugs.\n\n- One\n- Two `x`\n\n1. A")


class VersionFileTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.repo.write("Cargo.toml", '[package]\nname = "app"\nversion = "1.2.0"\n')
        self.repo.write("meson.build", "project('app',\n  version: '1.2.0',\n)\n")

    def tearDown(self):
        self.repo.close()

    def test_read_and_check(self):
        specs = versions.parse_spec('Cargo.toml: ^version = "(.*)"\n# comment\nmeson.build: version: \'(.*)\'')
        found = versions.read(self.repo.root, specs)
        self.assertEqual(found, {"Cargo.toml": "1.2.0", "meson.build": "1.2.0"})
        versions.check(found, "1.2.0", "metainfo")
        with self.assertRaisesRegex(versions.VersionError, "Cargo.toml says 1.2.0"):
            versions.check(found, "1.3.0", "metainfo")

    def test_spec_errors(self):
        with self.assertRaisesRegex(versions.VersionError, "needs a \\(group\\)"):
            versions.parse_spec("Cargo.toml: version")
        with self.assertRaisesRegex(versions.VersionError, "expected 'path: regex'"):
            versions.parse_spec("Cargo.toml")
        with self.assertRaisesRegex(versions.VersionError, "does not exist"):
            versions.read(self.repo.root, versions.parse_spec("missing.toml: v(.*)"))

    def test_disagreement_without_reference(self):
        with self.assertRaisesRegex(versions.VersionError, "disagree"):
            versions.check({"a": "1", "b": "2"}, None, "")


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.repo.write("build-aux/org.example.App.json", json.dumps(MANIFEST))
        self.existing = set()

    def tearDown(self):
        self.repo.close()

    def metainfo(self, *entries):
        self.repo.write("data/org.example.App.metainfo.xml", METAINFO.format("\n".join(entries)))

    def plan(self, event="push", ref="refs/heads/main", version_files=""):
        args = Namespace(root=str(self.repo.root), event=event, ref=ref, default_branch="main", manifest="",
                         metainfo="", version_files=version_files, tag_prefix="v", arches="x86_64 aarch64",
                         runners="")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                cli.plan(args, exists=lambda tag, root: tag in self.existing)
            except (project.ProjectError, versions.VersionError) as problem:
                return {"error": str(problem)}
        return dict(line.split("=", 1) for line in out.getvalue().splitlines())

    def test_new_version_on_main_releases(self):
        self.metainfo(release("1.1.0", "2026-11-03"), release("1.0.0", "2026-11-01"))
        self.existing = {"v1.0.0"}
        result = self.plan()
        self.assertEqual((result["release"], result["build"], result["tag"]), ("true", "true", "v1.1.0"))
        self.assertEqual(json.loads(result["matrix"])["include"][1],
                         {"arch": "aarch64", "runner": "ubuntu-26.04-arm"})

    def test_existing_version_and_other_events_do_not_release(self):
        self.metainfo(release("1.0.0", "2026-11-01"))
        self.existing = {"v1.0.0"}
        self.assertEqual(self.plan()["release"], "false")
        self.existing = set()
        self.assertEqual(self.plan(ref="refs/heads/feature")["release"], "false")
        self.assertEqual(self.plan(event="pull_request", ref="refs/pull/1/merge")["release"], "false")
        result = self.plan(event="workflow_dispatch")
        self.assertEqual((result["release"], result["build"]), ("false", "true"))

    def test_tags(self):
        self.metainfo(release("1.0.0", "2026-11-01"))
        self.assertEqual(self.plan(ref="refs/tags/v1.0.0")["release"], "true")
        self.assertIn("does not match", self.plan(ref="refs/tags/v1.0.1")["error"])
        result = self.plan(ref="refs/tags/v1.1.0-rc1")
        self.assertEqual((result["release"], result["prerelease"]), ("true", "true"))
        self.assertEqual(self.plan(ref="refs/tags/build-7")["release"], "false")

    def test_development_release_is_prerelease(self):
        self.metainfo(release("1.1.0", "2026-11-03", 'type="development"'))
        self.assertEqual(self.plan()["prerelease"], "true")
        self.assertEqual(self.plan(ref="refs/tags/v1.1.0")["prerelease"], "true")

    def test_version_files_checked_on_every_event(self):
        self.metainfo(release("1.1.0", "2026-11-03"))
        self.repo.write("Cargo.toml", 'version = "1.0.0"\n')
        result = self.plan(event="pull_request", ref="refs/pull/1/merge",
                           version_files='Cargo.toml: ^version = "(.*)"')
        self.assertIn("Cargo.toml says 1.0.0", result["error"])

    def test_without_metainfo_only_tags_release(self):
        self.assertEqual(self.plan()["release"], "false")
        self.assertEqual(self.plan(ref="refs/tags/v2.0.0")["release"], "true")

    def test_unknown_arch_needs_runner(self):
        with self.assertRaisesRegex(project.ProjectError, "no runner known for riscv64"):
            cli.matrix("x86_64 riscv64", "")
        self.assertEqual(cli.matrix("riscv64", "riscv64: my-runner")["include"],
                         [{"arch": "riscv64", "runner": "my-runner"}])


if __name__ == "__main__":
    unittest.main()
