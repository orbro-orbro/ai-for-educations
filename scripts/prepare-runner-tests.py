"""Copy existing pure Python test tools into an isolated image build context."""
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1]).resolve()
if not target.is_relative_to((root / ".superpowers").resolve()):
    raise ValueError("Test context must remain in this task's ignored workspace")
target.mkdir(parents=True, exist_ok=False)
deps = target / "deps"
deps.mkdir()
for name in ("pytest", "_pytest", "pluggy", "packaging", "iniconfig", "pygments", "py", "yaml", "httpx", "httpcore"):
    module = importlib.util.find_spec(name)
    source = Path(module.origin)
    if module.submodule_search_locations is None:
        shutil.copyfile(source, deps / source.name)
    else:
        shutil.copytree(source.parent, deps / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyd", "*.so", "*.dll"))
for name in ("runner", "contracts"):
    shutil.copytree(root / name, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
shutil.copyfile(root / "infra/compose/wave3-runner-tests.Dockerfile", target / "Dockerfile")
print(json.dumps({"context":str(target),"host_python":sys.version,"tools":{name:importlib.metadata.version(name) for name in ("pytest","pluggy","packaging","iniconfig","pygments","PyYAML","httpx","httpcore")},"downloads":False}))
