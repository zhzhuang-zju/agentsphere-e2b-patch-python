"""Diagnose an installed agentsphere-e2b-patch environment.

Usage:
    python diagnose_patch_environment.py
    python diagnose_patch_environment.py /path/to/agentsphere_e2b_patch.whl

The script does not call E2B APIs or require an API key. It only checks local
installation, import, and runtime wrapping stages.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import inspect
import pathlib
import site
import sys
import zipfile
from typing import Any, Callable, Optional

PACKAGE_NAME = "agentsphere-e2b-patch"
PATCH_MODULE = "agentsphere_e2b_patch"
MARKER = "_agentsphere_e2b_patched"


def stage(number: int, title: str) -> None:
    print(f"\n[{number}] {title}")


def ok(message: str) -> None:
    print(f"  OK: {message}")


def warn(message: str) -> None:
    print(f"  WARN: {message}")


def fail(message: str) -> None:
    print(f"  FAIL: {message}")


def file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def installed_distribution() -> Optional[importlib.metadata.Distribution]:
    try:
        return importlib.metadata.distribution(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return None


def site_package_dirs() -> list[pathlib.Path]:
    directories: list[str] = []
    try:
        directories.extend(site.getsitepackages())
    except AttributeError:
        pass
    try:
        directories.append(site.getusersitepackages())
    except AttributeError:
        pass
    return list(dict.fromkeys(pathlib.Path(path) for path in directories))


def check_wheel(path: pathlib.Path) -> bool:
    if not path.is_file():
        fail(f"wheel does not exist: {path}")
        return False
    print(f"  wheel: {path}")
    print(f"  sha256: {file_hash(path)}")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            hook_names = [
                name
                for name in names
                if name.endswith("agentsphere_e2b_patch/_hook.py")
            ]
            if not hook_names:
                fail("wheel does not contain agentsphere_e2b_patch/_hook.py")
                return False
            hook = archive.read(hook_names[0]).decode("utf-8")
            required = (
                "inspect.getattr_static",
                "_CREATE_BUILD_EXTENSIONS",
                "gatewayID",
            )
            missing = [token for token in required if token not in hook]
            if missing:
                fail(f"wheel hook is missing expected code: {', '.join(missing)}")
                return False
            ok("wheel contains the current create-template and build wrappers")
            return True
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as error:
        fail(f"cannot inspect wheel: {error}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", nargs="?", type=pathlib.Path)
    args = parser.parse_args()

    failures = 0

    stage(1, "Python interpreter")
    print(f"  executable: {sys.executable}")
    print(f"  version: {sys.version.split()[0]}")
    if sys.version_info < (3, 9):
        fail("Python must be >= 3.9")
        failures += 1
    else:
        ok("Python version is supported")

    stage(2, "Installed patch distribution")
    distribution = installed_distribution()
    if distribution is None:
        fail(f"distribution {PACKAGE_NAME!r} is not installed in this Python")
        failures += 1
    else:
        ok(f"version={distribution.version}")
        print(f"  location: {distribution.locate_file('')}")

    stage(3, "Wheel contents")
    if args.wheel is not None and not check_wheel(args.wheel):
        failures += 1
    elif args.wheel is None:
        warn("no wheel path supplied; skipped wheel freshness check")
        print("  tip: pass the exact wheel path as the first argument")

    stage(4, "site-packages and .pth")
    patch_pth: list[pathlib.Path] = []
    for directory in site_package_dirs():
        print(f"  site directory: {directory}")
        candidate = directory / "agentsphere_e2b_patch.pth"
        if candidate.is_file():
            patch_pth.append(candidate)
            print(f"  .pth: {candidate}")
            print(f"  .pth content: {candidate.read_text(errors='replace').strip()}")
    if not patch_pth:
        warn("agentsphere_e2b_patch.pth was not found in the inspected site directories")
        warn("the package may still work with an explicit import, but automatic loading is unavailable")
    else:
        ok("patch .pth file is installed")

    stage(5, "Patch import")
    try:
        patch = importlib.import_module(PATCH_MODULE)
        print(f"  module: {getattr(patch, '__file__', '<unknown>')}")
        ok("patch module imports")
    except Exception as error:
        fail(f"patch import failed: {type(error).__name__}: {error}")
        return 1

    stage(6, "E2B import")
    try:
        e2b = importlib.import_module("e2b")
        print(f"  module: {getattr(e2b, '__file__', '<unknown>')}")
        try:
            print(f"  version: {importlib.metadata.version('e2b')}")
        except importlib.metadata.PackageNotFoundError:
            print("  version: <distribution metadata unavailable>")
        ok("E2B imports")
    except Exception as error:
        fail(f"E2B import failed: {type(error).__name__}: {error}")
        return 1

    stage(7, "Template.build runtime patch")
    template = getattr(e2b, "Template", None)
    if template is None:
        fail("e2b.Template is not exported by this E2B SDK")
        failures += 1
    else:
        build = getattr(template, "build", None)
        print(f"  Template class: {template!r}")
        print(f"  Template module: {template.__module__}")
        print(f"  build module: {getattr(build, '__module__', '<unknown>')}")
        print(f"  build signature: {inspect.signature(build) if build else '<missing>'}")
        descriptor = inspect.getattr_static(template, "build", None)
        print(f"  build descriptor: {type(descriptor).__name__}")
        print(f"  patched marker: {getattr(build, MARKER, False)}")
        if not callable(build):
            fail("e2b.Template.build is missing or not callable")
            failures += 1
        elif not getattr(build, MARKER, False):
            warn("Template.build is not patched after automatic import")
            mro = [f"{item.__module__}.{item.__name__}" for item in template.__mro__]
            print(f"  MRO: {mro}")
            failures += 1
        else:
            ok("Template.build is patched")

    stage(8, "Manual install re-check")
    try:
        install = getattr(patch, "install")
        install()
        build = getattr(getattr(e2b, "Template", None), "build", None)
        print(f"  patched marker after install(): {getattr(build, MARKER, False)}")
        if getattr(build, MARKER, False):
            ok("manual install() activates the Template.build patch")
        else:
            fail("manual install() could not patch Template.build; SDK layout is unsupported by this wheel")
            failures += 1
    except Exception as error:
        fail(f"manual install() failed: {type(error).__name__}: {error}")
        failures += 1

    print("\nResult")
    if failures:
        print(f"  FAIL: {failures} stage(s) need attention")
        return 1
    print("  PASS: environment is using the patch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
