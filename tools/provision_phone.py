#!/usr/bin/env python3
"""Install the reference APK and public INT8 bundle on an explicitly selected phone."""
import argparse
import io
import json
from pathlib import Path
import secrets
import subprocess
import tarfile
import time
import urllib.request

PACKAGE = "com.darren236.bedsidevoice"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="An authorized adb device; never auto-select")
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path(".local"))
    args = parser.parse_args()
    root = args.data.resolve()
    bundle = root / "models-int8"
    manifest = json.loads((bundle / "MOSS-TTS-Nano-100M-ONNX/browser_poc_manifest.json").read_text())
    voice = next(row for row in manifest["builtin_voices"] if row["voice"] == "Ava")
    fixtures = json.dumps({"prompt_audio_codes": voice["prompt_audio_codes"]}).encode()
    token = secrets.token_hex(32)
    adb = ["adb", "-s", args.serial]

    def run(*command, **kwargs):
        return subprocess.run([*adb, *command], check=True, **kwargs)

    run("get-state", stdout=subprocess.DEVNULL)
    run("install", "-r", str(args.apk.resolve()))
    run("shell", "am", "force-stop", PACKAGE)
    external = f"/sdcard/Android/data/{PACKAGE}/files"
    run("shell", "run-as", PACKAGE, "mkdir", "-p", external, "files")
    # No shared storage staging: tar enters the app's own directory as that app.
    archive = root / "phone-bundle.tar"
    try:
        with tarfile.open(archive, "w") as tar:
            tar.add(bundle, arcname="models-int8", filter=lambda info: None if "/.cache/" in info.name else info)
            info = tarfile.TarInfo("fixtures.json")
            info.size = len(fixtures)
            tar.addfile(info, io.BytesIO(fixtures))
        with archive.open("rb") as content:
            run("shell", "-T", "run-as", PACKAGE, "tar", "-xf", "-", "-C", external, stdin=content)
    finally:
        archive.unlink(missing_ok=True)
    run("shell", "-T", "run-as", PACKAGE, "tee", "files/auth.token", input=token.encode(), stdout=subprocess.DEVNULL)
    run("shell", "run-as", PACKAGE, "chmod", "600", "files/auth.token")
    run("forward", "tcp:12883", "tcp:12882")
    run("shell", "am", "start-foreground-service", "-n", PACKAGE + "/.PhoneSpeechService")
    config = {"port": 12883, "token": token, "preset": "Ava"}
    deadline = time.monotonic() + 180
    while True:
        request = urllib.request.Request("http://127.0.0.1:12883/health", headers={"Authorization": "Bearer " + token})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                config["fingerprint"] = json.load(response)["fingerprint"]
            break
        except (OSError, ValueError):
            if time.monotonic() > deadline:
                raise RuntimeError("Phone did not become ready; inspect adb logcat -s BedsideSpeech")
            time.sleep(2)
    path = root / "phone.json"
    # Create a new credential file with private permissions even if an older one exists.
    path.unlink(missing_ok=True)
    with path.open("x", opener=lambda p, flags: __import__("os").open(p, flags, 0o600)) as output:
        json.dump(config, output)
    print("Phone ready. Import phone.json into the speech data volume and restart moss.")


if __name__ == "__main__":
    main()
