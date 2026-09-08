"""Explicit, one-time public model download. Runtime grouping stays offline."""

import argparse
import json
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

parser = argparse.ArgumentParser()
parser.add_argument("--output", default="workbench/models/minilm")
args = parser.parse_args()
repo = "sentence-transformers/all-MiniLM-L6-v2"
revision = HfApi(token=False).model_info(repo).sha
root = Path(args.output).resolve()
snapshot_download(
    repo_id=repo,
    revision=revision,
    token=False,
    local_dir=root,
    allow_patterns=["*.json", "*.txt", "*.safetensors", "1_Pooling/*"],
)
(root / "fixfirst_model_source.json").write_text(json.dumps({"repo": repo, "revision": revision}))
print(root)
