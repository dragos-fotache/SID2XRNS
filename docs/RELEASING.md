# GitHub Actions

**Build** runs on every push. It runs the Python tests on Ubuntu, packages
the checked-out commit, and converts the included SID fixture from the
extracted archive. The run publishes a Linux CLI archive and SHA-256
checksum as the `sid2xrns-linux` artifact.

**Release** runs manually from **Actions → Release → Run workflow**. Select
the ref to release. The workflow runs the same tests and packaging steps,
then publishes a GitHub release tagged `v<version>` using the CLI version
from that commit. It attaches the tested archive and checksum. Check
`dry_run` to verify the package and keep it as an Actions artifact.

The archive is the tracked source tree and runs with Python 3 on Linux.
Renoise and the separately installed SIDSynth VST3 are needed for playback.
The hosted checks cover conversion and packaging. See the project status
for Renoise playback evidence. [Project status](STATUS.md)

The workflows pin the GitHub Actions below to their commit SHAs. All four
are MIT-licensed. Test dependencies use the versions in the project's
reference lock.

- [Checkout v7.0.1](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/LICENSE)
- [Setup Python v7.1.0](https://github.com/actions/setup-python/blob/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0/LICENSE)
- [Upload Artifact v7.0.2](https://github.com/actions/upload-artifact/blob/cf430e030ddbb5b0abf93d22962f4752f3646cd9/LICENSE)
- [Download Artifact v8.0.2](https://github.com/actions/download-artifact/blob/9000827ccba6bdab643e8b6fd33ac0654aef8333/LICENSE)
