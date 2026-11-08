"""Build a no-pip-on-robot bundle for Linux aarch64 / CPython 3.10.

On a development PC, use --download-wheels to fetch locked dependencies.
The robot itself never needs pip for the bundled third-party packages.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"websockets", "httpx", "pyyaml", "pypinyin", "certifi",
            "h11", "httpcore", "idna", "sniffio", "anyio",
            "exceptiongroup", "typing-extensions"}


def download_wheels(wheelhouse):
    wheelhouse = Path(wheelhouse)
    wheelhouse.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "pip", "download", "--quiet",
               "--dest", str(wheelhouse),
               "--platform", "manylinux2014_aarch64",
               "--python-version", "3.10",
               "--implementation", "cp", "--abi", "cp310",
               "--only-binary=:all:",
               "-r", str(ROOT / "requirements-lock.txt")]
    subprocess.run(command, check=True)


def build(wheelhouse, output):
    wheels = sorted(Path(wheelhouse).glob("*.whl"))
    names = {path.name.split("-")[0].lower().replace("_", "-") for path in wheels}
    missing = EXPECTED - names
    if missing:
        raise ValueError("missing wheels: " + ", ".join(sorted(missing)))
    extra = names - EXPECTED
    if extra:
        raise ValueError("unexpected wheels: " + ", ".join(sorted(extra)))
    pins = dict(line.strip().lower().split("==", 1)
                for line in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines()
                if "==" in line and not line.lstrip().startswith("#"))
    for wheel in wheels:
        name, version = wheel.name.lower().split("-", 2)[:2]
        if pins.get(name.replace("_", "-")) != version:
            raise ValueError("wheel does not match lock file: " + wheel.name)
        if not (wheel.name.endswith("-none-any.whl") or
                ("aarch64" in wheel.name and "cp310" in wheel.name)):
            raise ValueError("wheel is not universal or CPython 3.10 aarch64: " + wheel.name)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"target": "Linux aarch64 / CPython 3.10 / AimDK v1.0.0 or v1.1.0 audio profile",
                "wheels": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in wheels},
                "source_files": {}}
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as bundle:
        written = set()

        def put(name, data):
            if name in written:
                raise ValueError("duplicate bundle path: " + name)
            written.add(name)
            bundle.writestr("eldercare_x2/" + name, data)

        source = ([ROOT / "agent.py", ROOT / "feedback_dashboard.py",
                   ROOT / "README.md", ROOT / ".env.example",
                   ROOT / "LICENSE", ROOT / "skills.yaml",
                   ROOT / "requirements-lock.txt",
                   ROOT / "scripts" / "aimdk_mic_probe.py",
                   ROOT / "scripts" / "aimdk_asr_probe.py",
                   ROOT / "scripts" / "aimdk_asr_diagnostic.py",
                   ROOT / "scripts" / "aimdk_tts_probe.py",
                   ROOT / "scripts" / "robot_preflight.py",
                   ROOT / "scripts" / "run_robot_agent.py",
                   ROOT / "docs" / "zh-CN" / "onsite-deployment.md",
                   ROOT / "docs" / "zh-CN" / "reproduce-on-x2.md",
                   ROOT / "docs" / "zh-CN" / "aimdk-v1-robot-audio.md"] +
                  sorted((ROOT / "x2_agent").glob("*.py")) +
                  sorted((ROOT / "data").glob("*.json")))
        for path in source:
            relative = path.relative_to(ROOT).as_posix()
            content = path.read_bytes()
            put(relative, content)
            manifest["source_files"][relative] = hashlib.sha256(content).hexdigest()
        for wheel in wheels:
            with ZipFile(wheel) as archive:
                for item in archive.infolist():
                    if item.is_dir():
                        continue
                    relative = PurePosixPath(item.filename)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError("unsafe wheel member: " + item.filename)
                    put("vendor/" + relative.as_posix(), archive.read(item))
        put("bundle_manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, default=ROOT / ".robot-wheelhouse")
    parser.add_argument("--download-wheels", action="store_true",
                        help="在开发电脑上下载锁定的 aarch64/CPython 3.10 依赖")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "dist" / "eldercare_x2_aarch64_py310.zip")
    args = parser.parse_args()
    if args.download_wheels:
        download_wheels(args.wheelhouse)
    print(build(args.wheelhouse, args.output))


if __name__ == "__main__":
    main()
