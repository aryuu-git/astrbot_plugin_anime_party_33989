"""Build a small, explicit allowlist archive; never include runtime or secrets."""

import hashlib
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
paths = [
    root / n
    for n in (
        "__init__.py",
        "main.py",
        "metadata.yaml",
        "_conf_schema.json",
        "requirements.txt",
        "README.md",
        "LICENSE",
        "SOURCES.md",
        "CHANGELOG.md",
    )
]
paths += sorted((root / "game").glob("*.py"))
paths += [root / "game/data/questions.zh-CN.json"]
paths += sorted((root / "docs").glob("*.md"))
dest = root / "dist" / f"{root.name}-0.1.0.zip"
dest.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
    for p in paths:
        if not p.is_file():
            raise FileNotFoundError(p)
        archive.write(p, (Path(root.name) / p.relative_to(root)).as_posix())
assert dest.stat().st_size < 16 * 1024 * 1024
print(dest)
print("bytes:", dest.stat().st_size)
print("sha256:", hashlib.sha256(dest.read_bytes()).hexdigest())
