from importlib.metadata import distributions
from pathlib import Path
import shutil
import sys


target = Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
for package in distributions():
    for entry in package.files or ():
        name = entry.name.lower()
        if not (name.startswith(("license", "licence", "copying", "notice", "thirdparty", "third-party"))
                or "licenses" in entry.parts):
            continue
        if ".." in entry.parts:
            continue
        original = package.locate_file(entry)
        if not original.is_file():
            continue
        folder = target / package.metadata["Name"]
        folder.mkdir(exist_ok=True)
        shutil.copyfile(original, folder / ("-".join(entry.parts[-3:])))
for candidate in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
    if candidate.is_file():
        shutil.copyfile(candidate, target / "Python-License.txt")
        break

