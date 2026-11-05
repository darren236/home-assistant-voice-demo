"""Fetch public, revision-pinned assets. No household reference recording is needed."""
import hashlib
import json
from pathlib import Path
import urllib.request

SOURCE_REVISION = "8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb"
RUNTIME_SHA256 = "99477efaff28c12c0c8e16a6b4aab4e880a70851693fa303d932415ba180cbd5"
MODELS = {
    "MOSS-TTS-Nano-100M-ONNX": "f52645cb467506d8e18e746ddd59482685b74e58",
    "MOSS-Audio-Tokenizer-Nano-ONNX": "ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae",
}


def prepare(root: Path):
    from huggingface_hub import snapshot_download
    upstream = root / "upstream"
    upstream.mkdir(parents=True, exist_ok=True)
    for name in ("ort_cpu_runtime.py", "LICENSE"):
        url = f"https://raw.githubusercontent.com/OpenMOSS/MOSS-TTS-Nano/{SOURCE_REVISION}/{name}"
        with urllib.request.urlopen(url, timeout=60) as response:
            content = response.read()
        if name.endswith(".py") and hashlib.sha256(content).hexdigest() != RUNTIME_SHA256:
            raise RuntimeError("Upstream runtime checksum mismatch")
        (upstream / name).write_bytes(content)
    for name, revision in MODELS.items():
        snapshot_download(repo_id=f"OpenMOSS-Team/{name}", revision=revision,
                          local_dir=root / "models" / name,
                          allow_patterns=["*.json", "*.model", "*.onnx", "*.data", "LICENSE*", "README*"])
    (root / "assets.json").write_text(json.dumps({"source": SOURCE_REVISION, "models": MODELS}, indent=2) + "\n")
    print("Models ready. Start the service, then synthesize a sample.")


def load_upstream(root: Path):
    import importlib.util
    path = root / "upstream" / "ort_cpu_runtime.py"
    if not path.exists():
        raise RuntimeError("Run 'prepare' first to download the pinned runtime and models")
    if hashlib.sha256(path.read_bytes()).hexdigest() != RUNTIME_SHA256:
        raise RuntimeError("Upstream runtime checksum mismatch; run prepare again")
    spec = importlib.util.spec_from_file_location("bedside_ort_runtime", path)
    module = importlib.util.module_from_spec(spec)
    # dataclass resolves its module while importing.
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
