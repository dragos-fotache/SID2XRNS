# SPDX-License-Identifier: AGPL-3.0-only
import json
from pathlib import Path

root = Path(SPECPATH).resolve().parents[1]
assets = {"docs/runtime-lock.json", "docs/runtime-lock-v4.json"}
for manifest in sorted(assets):
    # Locked Python sources are data too. The CLI checks their original bytes.
    assets.update(json.loads((root / manifest).read_text())["files"])

analysis = Analysis(
    [str(root / "bin/sid2xrns")],
    pathex=[str(root)],
    datas=[(str(root / asset), str(Path(asset).parent)) for asset in sorted(assets)],
)
Path(workpath, "bundled-libraries.json").write_text(
    json.dumps(sorted({source for _, source, _ in analysis.binaries})),
    encoding="utf-8",
)

exe = EXE(
    PYZ(analysis.pure),
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    name="sid2xrns",
    console=True,
    upx=False,
)
