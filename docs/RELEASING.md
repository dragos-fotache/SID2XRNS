# GitHub Actions

**Build** runs on every push. It runs the Python tests on Ubuntu, packages
the standalone executable in the pinned Debian container, and checks
that the extracted binary converts both envelope modes byte for byte
against the source CLI. The run uploads the archive and SHA-256 checksum
as the `sid2xrns-linux` artifact.

**Release** runs manually from **Actions → Release → Run workflow**. Select
the ref to release. The workflow runs the same tests and packaging steps,
then publishes a GitHub release tagged `v<version>` using the CLI version
from that commit. It attaches the tested archive and checksum. Check
`dry_run` to verify the package and keep it as an Actions artifact.

`SID2XRNS-<version>-linux-x86_64.tar.gz` has two files inside its top-level
directory. Run `./sid2xrns --help` after extracting it. The executable
includes Python and its runtime assets. `LICENSES.txt` sits beside it and
contains both project and bundled dependency notices. GitHub's source
archive for the same release tag contains the build files and source.

The executable targets x86-64 Linux with glibc 2.36 or newer. Renoise and
SIDSynth VST3 are needed for playback. The hosted checks cover conversion and
packaging. [Renoise playback evidence](STATUS.md)

The local build command uses Docker.

```sh
bash tools/package_linux.sh work/linux-release
```

The [build container](../tools/packaging/Dockerfile) pins CPython 3.14.10
on Debian Bookworm and GNU Binutils 2.40. The
[wheel lock](../tools/packaging/requirements.txt) pins PyInstaller 6.22.3
and its build dependencies by SHA-256. The bundle includes the exact
CPython and PyInstaller licenses and the Debian notices for the shared
libraries collected by PyInstaller.

The workflows pin the GitHub Actions below to their commit SHAs. All four
are MIT-licensed. Test dependencies use the versions in the project's
reference lock.

- [Checkout v7.0.1](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/LICENSE)
- [Setup Python v7.1.0](https://github.com/actions/setup-python/blob/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0/LICENSE)
- [Upload Artifact v7.0.2](https://github.com/actions/upload-artifact/blob/cf430e030ddbb5b0abf93d22962f4752f3646cd9/LICENSE)
- [Download Artifact v8.0.2](https://github.com/actions/download-artifact/blob/9000827ccba6bdab643e8b6fd33ac0654aef8333/LICENSE)
