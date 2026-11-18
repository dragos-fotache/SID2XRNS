# SPDX-License-Identifier: AGPL-3.0-only
"""Build the Linux distribution inside the pinned Debian build container."""
import argparse
from hashlib import file_digest, md5
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]


def debian_package(path):
    candidates = {str(path), str(path.resolve())}
    for name in sorted(candidates | {name.removeprefix("/usr") for name in candidates}):
        result = subprocess.run(["dpkg-query", "--search", name], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.split(": ", 1)[0].split(":", 1)[0]
    raise RuntimeError(f"Cannot find the Debian package that provides bundled library {path}")


def write_licenses(path, version, libraries):
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    libpython = (Path(sysconfig.get_config_var("LIBDIR")) /
                 sysconfig.get_config_var("LDLIBRARY")).resolve()
    pyinstaller = distribution("PyInstaller")
    bootloader_license = next(item for item in pyinstaller.files if item.name == "COPYING.txt")
    sources = [
        ("SID2XRNS (AGPL-3.0-only)", ROOT / "LICENSE"),
        ("ChiptuneSAK (MIT)", ROOT / "third_party/chiptunesak/LICENSE"),
        ("libresidfp authors", ROOT / "third_party/licenses/libresidfp-AUTHORS"),
        ("libresidfp (GPL-2.0-or-later)", ROOT / "third_party/licenses/libresidfp-GPL-2.0.txt"),
        ("GNU General Public License, version 3", ROOT / "third_party/licenses/GPL-3.0.txt"),
        (f"CPython {sys.version.split()[0]}", stdlib / "LICENSE.txt"),
        (f"PyInstaller {pyinstaller.version} bootloader and exception",
         pyinstaller.locate_file(bootloader_license)),
    ]
    packages = set()
    for path_name in libraries:
        library = Path(path_name)
        resolved = library.resolve()
        if resolved != libpython and not resolved.is_relative_to(stdlib):
            packages.add(debian_package(library))
    texts = [(name, source.read_text(encoding="utf-8")) for name, source in sources]
    common_licenses = set()
    for package in sorted(packages):
        copyright_text = (Path("/usr/share/doc") / package / "copyright").read_text(encoding="utf-8")
        texts.append((f"Bundled Debian library package {package}", copyright_text))
        references = re.findall(r"/usr/share/common-licenses/([A-Za-z0-9_.+-]+)", copyright_text)
        common_licenses.update(name.rstrip(".") for name in references)
    for name in sorted(common_licenses):
        text = (Path("/usr/share/common-licenses") / name).read_text(encoding="utf-8")
        texts.append((f"Debian common license {name}", text))

    with path.open("w", encoding="utf-8") as notice:
        notice.write(f"SID2XRNS {version} and bundled software notices\n")
        notice.write(f"Release source: https://github.com/dragos-fotache/SID2XRNS/tree/v{version}\n")
        notice.write(f"CPython source: https://github.com/python/cpython/tree/v{sys.version.split()[0]}\n")
        notice.write(f"PyInstaller source: https://github.com/pyinstaller/pyinstaller/tree/v{pyinstaller.version}\n")
        notice.write("libresidfp credits: Leandro Nini (2011–2020), VICE Project (2018), "
                     "Antti Lankila (2007–2010), Dag Lem (2004, 2010).\n")
        for name, text in texts:
            notice.write(f"\n{'=' * 72}\n{name}\n{'=' * 72}\n{text.rstrip()}\n")


def smoke_test(executable, directory, version):
    # The frozen program must work from a clean directory without Python on PATH.
    env = {**os.environ, "PATH": ""}
    assert subprocess.check_output([executable, "--version"], cwd=directory, env=env,
                                   text=True).strip() == version
    fixture = ROOT / "fixtures/cli-performance.sid"
    digest = md5(fixture.read_bytes(), usedforsecurity=False).hexdigest()
    (directory / "Songlengths.md5").write_text(f"[Database]\n{digest}=0:00.1\n", encoding="ascii")
    for timing in ("source", "legacy"):
        expected = directory / f"{timing}-source.xrns"
        actual = directory / f"{timing}-executable.xrns"
        subprocess.run([sys.executable, ROOT / "bin/sid2xrns", "convert", fixture,
                        "--play-calls", "6", "--envelope-timing", timing, "-o", expected],
                       cwd=directory, check=True, capture_output=True)
        subprocess.run([executable, "convert", fixture, "--hvsc-db",
                        "--envelope-timing", timing, "-o", actual],
                       cwd=directory, env=env, check=True)
        if actual.read_bytes() != expected.read_bytes():
            raise RuntimeError(f"Packaged executable changed the {timing} XRNS export")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    version = subprocess.check_output([sys.executable, ROOT / "bin/sid2xrns", "--version"],
                                      text=True).strip()
    if re.fullmatch(r"\d+\.\d+\.\d+", version, flags=re.ASCII) is None:
        raise ValueError(f"Expected a numeric CLI version, got {version!r}")
    package_name = f"SID2XRNS-{version}-linux-x86_64"
    with TemporaryDirectory(prefix="sid2xrns-build-") as temporary:
        temporary = Path(temporary)
        staging = temporary / "staging"
        work = temporary / "pyinstaller"
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                        "--distpath", staging, "--workpath", work,
                        ROOT / "tools/packaging/sid2xrns.spec"],
                       cwd=ROOT, check=True)
        notice = staging / "LICENSES.txt"
        libraries = json.loads((work / "sid2xrns/bundled-libraries.json").read_text())
        write_licenses(notice, version, libraries)

        archive = temporary / f"{package_name}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name in ("sid2xrns", "LICENSES.txt"):
                bundle.add(staging / name, arcname=f"{package_name}/{name}")
        smoke = temporary / "smoke"
        smoke.mkdir()
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(smoke, filter="data")
        smoke_test(smoke / package_name / "sid2xrns", smoke, version)

        with archive.open("rb") as file:
            checksum = file_digest(file, "sha256").hexdigest()
        shutil.copyfile(archive, args.output_dir / archive.name)
        (args.output_dir / f"{archive.name}.sha256").write_text(
            f"{checksum}  {archive.name}\n", encoding="ascii")
        print(args.output_dir / archive.name)


if __name__ == "__main__":
    main()
