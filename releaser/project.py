"""Finds an app's Flatpak manifest and metainfo, and reads its release history."""
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", ".flatpak-builder", "build", "_build", "builddir", "target", "node_modules", ".frogpak-releaser"}
MANIFEST_DIRS = ("build-aux", "flatpak", "packaging", ".")


class ProjectError(Exception):
    pass


@dataclass
class Manifest:
    path: Path
    app_id: str
    branch: str

    @property
    def name(self):
        return self.app_id.rsplit(".", 1)[-1]


@dataclass
class Release:
    version: str
    development: bool
    notes: str


def _load_manifest(path):
    text = path.read_text()
    if path.suffix == ".json":
        try:
            return json.loads(text)
        except ValueError:
            return None
    try:
        import yaml
    except ImportError:
        raise ProjectError(f"{path} is a YAML manifest and PyYAML is not installed") from None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def _as_manifest(path, data):
    if not isinstance(data, dict) or "modules" not in data:
        return None
    app_id = data.get("app-id") or data.get("id")
    if not isinstance(app_id, str):
        return None
    branch = data.get("branch") or data.get("default-branch") or "master"
    return Manifest(path, app_id, str(branch))


def find_manifest(root, given=None):
    root = Path(root)
    if given:
        path = root / given
        if not path.is_file():
            raise ProjectError(f"manifest {given} does not exist")
        manifest = _as_manifest(path, _load_manifest(path))
        if manifest is None:
            raise ProjectError(f"{given} is not a Flatpak app manifest (needs app-id and modules)")
        return manifest
    for folder in MANIFEST_DIRS:
        found = []
        for path in sorted((root / folder).glob("*")):
            if path.suffix in (".json", ".yml", ".yaml") and path.is_file():
                manifest = _as_manifest(path, _load_manifest(path))
                if manifest:
                    found.append(manifest)
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            names = ", ".join(str(m.path.relative_to(root)) for m in found)
            raise ProjectError(f"several manifests in {folder}/ ({names}); set the manifest input")
    raise ProjectError("no Flatpak manifest found in build-aux/, flatpak/, packaging/ or the repository root; "
                       "set the manifest input")


def find_metainfo(root, app_id, given=None):
    root = Path(root)
    if given:
        path = root / given
        if not path.is_file():
            raise ProjectError(f"metainfo {given} does not exist")
        return path
    names = re.compile(rf"^{re.escape(app_id)}\.(metainfo|appdata)\.xml(\.in)*$")
    found = []
    for path in root.rglob("*.xml*"):
        if names.match(path.name) and not SKIP_DIRS.intersection(path.relative_to(root).parts):
            found.append(path)
    if len(found) > 1:
        names = ", ".join(str(p.relative_to(root)) for p in sorted(found))
        raise ProjectError(f"several metainfo files ({names}); set the metainfo input")
    return found[0] if found else None


def _when(release):
    """Sortable release time; AppStream allows a date or a Unix timestamp."""
    if release.get("timestamp"):
        try:
            from datetime import datetime, timezone
            return datetime.fromtimestamp(int(release.get("timestamp")), timezone.utc).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return (release.get("date") or "")[:10] or None


def _markdown(description):
    """Converts AppStream description markup (p, ul, ol, li, em, code) to Markdown."""
    if description is None:
        return ""
    def inline(element):
        text = element.text or ""
        for child in element:
            inner = inline(child)
            text += f"*{inner}*" if child.tag == "em" else f"`{inner}`" if child.tag == "code" else inner
            text += child.tail or ""
        return " ".join(text.split())
    blocks = []
    for element in description:
        if element.tag == "p":
            blocks.append(inline(element))
        elif element.tag in ("ul", "ol"):
            items = [li for li in element if li.tag == "li"]
            marker = (lambda i: "-") if element.tag == "ul" else (lambda i: f"{i}.")
            blocks.append("\n".join(f"{marker(i)} {inline(li)}" for i, li in enumerate(items, 1)))
    return "\n\n".join(b for b in blocks if b)


def read_releases(path):
    """Releases from a metainfo file, newest first, or None when releases live elsewhere."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ProjectError(f"cannot parse {path}: {error}") from None
    releases = root.find("releases")
    if releases is None:
        return []
    if releases.get("type") == "external":
        return None
    entries = releases.findall("release")
    times = [_when(r) for r in entries]
    for i in range(1, len(entries)):
        if times[i] and times[i - 1] and times[i] > times[i - 1]:
            raise ProjectError(f"{path}: releases must be listed newest first; "
                               f"{entries[i].get('version')} ({times[i]}) is below {entries[i - 1].get('version')}")
    result = []
    for entry in entries:
        version = entry.get("version")
        if not version:
            raise ProjectError(f"{path}: a <release> has no version")
        result.append(Release(version, entry.get("type") == "development", _markdown(entry.find("description"))))
    return result
