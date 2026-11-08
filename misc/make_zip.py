"""Build a distribution zip (without system/, user-data/, downloads).
Usage: python3 misc/make_zip.py [output.zip]
"""
import os
import sys
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
out = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC.parent / "avatar-chat-dist" / "avatar-chat.zip"
out.parent.mkdir(parents=True, exist_ok=True)
skip = {".git", "system", "user-data", "__pycache__", "downloads", "gen", "llama.cpp", "llama-swap", "models"}
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in skip]
        for n in files:
            p = Path(root) / n
            z.write(p, "avatar-chat/" + p.relative_to(SRC).as_posix())
names = [i.filename for i in zipfile.ZipFile(out).infolist()]
print(out)
print("\n".join(names))
