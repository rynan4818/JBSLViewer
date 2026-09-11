"""Refresh the pinned, local Swagger UI assets. Never run during server startup."""

import base64
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

VERSION = "5.32.15"
INTEGRITY = "TSFER+rFQlf1nzk6WvKkMaHTxAPQ3eAAxigFThnxQedSREanfZgSbJFayZVs/ULnSbNdrJOb99vLD6xpb3R3eg=="
URL = f"https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-{VERSION}.tgz"
DESTINATION = Path(__file__).resolve().parent.parent / "jbsl_score" / "static" / "vendor" / "swagger-ui"


def main():
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024 or base64.b64encode(hashlib.sha512(data).digest()).decode() != INTEGRITY:
        raise ValueError("Swagger UI archive integrity check failed")
    DESTINATION.mkdir(parents=True, exist_ok=True)
    hashes = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for name in ("swagger-ui-bundle.js", "swagger-ui.css", "LICENSE", "NOTICE", "swagger-ui-bundle.js.LICENSE.txt"):
            try:
                member = archive.getmember("package/" + name)
            except KeyError:
                if name in ("NOTICE", "swagger-ui-bundle.js.LICENSE.txt"):
                    continue
                raise
            if not member.isfile() or member.size > 10 * 1024 * 1024:
                raise ValueError("Unexpected Swagger asset")
            contents = archive.extractfile(member).read()
            (DESTINATION / name).write_bytes(contents)
            hashes[name] = hashlib.sha256(contents).hexdigest()
    (DESTINATION / "manifest.json").write_text(
        json.dumps(
            {
                "package": "swagger-ui-dist",
                "version": VERSION,
                "source": URL,
                "integrity": "sha512-" + INTEGRITY,
                "sha256": hashes,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Swagger UI {VERSION}: saved {len(hashes)} files with verified archive integrity")


if __name__ == "__main__":
    main()
