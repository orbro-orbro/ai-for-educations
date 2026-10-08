"""Compare the actual generated routes/models with the frozen shared contract."""
import json
from pathlib import Path
import pytest
import yaml
from app.main import create_app

ROOT = Path(__file__).resolve().parents[3]
SHARED = yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text(encoding="utf-8"))
METHODS = {"get","post","patch","delete","put"}


def operations(doc):
    return {(path,method): op for path,item in doc["paths"].items() for method,op in item.items() if method in METHODS}


def resolve(value, doc, names=False):
    if isinstance(value, list):
        return [resolve(v,doc) for v in value]
    if not isinstance(value,dict):
        return value
    if "$ref" in value:
        target = doc
        for key in value["$ref"][2:].split("/"):
            target = target[key]
        value = {**target, **{k:v for k,v in value.items() if k != "$ref"}}
    result = {k:resolve(v,doc, names=k in {"properties", "mapping"}) for k,v in value.items() if names or k not in {"title","description"}}
    if names:
        return result
    # Nullable OpenAPI3.0/3.1 spellings express the same accepted value set.
    choices = result.get("anyOf")
    if choices and len(choices)==2 and {"type":"null"} in choices:
        other = next(v for v in choices if v != {"type":"null"})
        result.pop("anyOf")
        result.update(other)
        result["type"] = sorted([result["type"],"null"]) if isinstance(result.get("type"),str) else result.get("type")
        if "enum" in result and None not in result["enum"]:
            result["enum"].append(None)
    if result.pop("nullable",False):
        result["type"] = sorted([result["type"],"null"]) if isinstance(result.get("type"),str) else result.get("type")
    for key in ("required","enum","type"):
        if isinstance(result.get(key),list):
            if key == "type":
                result[key] = ["null" if v is None else v for v in result[key]]
            result[key] = sorted(result[key], key=lambda v:json.dumps(v,sort_keys=True))
    for key in ("oneOf","anyOf"):
        if key in result:
            result[key] = sorted(result[key],key=lambda v:json.dumps(v,sort_keys=True))
    if "discriminator" in result:
        # An explicit mapping to these same resolved branches is optional; its
        # targets must correspond to the discriminator's actual const values.
        discriminator = result["discriminator"]
        mapping = discriminator.pop("mapping",None)
        if mapping:
            property_name = discriminator["propertyName"]
            for label,target in mapping.items():
                schema = resolve({"$ref":target},doc)
                assert schema["properties"][property_name]["const"] == label
                assert schema in result["oneOf"]
    return result


def parameters(doc, path, operation):
    result = {}
    for p in doc["paths"][path].get("parameters",[]) + operation.get("parameters",[]):
        p = resolve(p,doc)
        result[(p["name"],p["in"])] = {**p, "required":p.get("required",False)}
    return result


def test_full_runtime_operation_set_matches_frozen_shared_contract():
    assert set(operations(create_app().openapi())) == set(operations(SHARED))


@pytest.mark.parametrize("path,method", list(operations(SHARED)), ids=lambda x:x)
def test_every_runtime_operation_matches_contract(path, method):
    runtime = create_app().openapi()
    expected = operations(SHARED)[path,method]
    actual = operations(runtime).get((path,method))
    assert actual is not None
    assert actual["operationId"] == expected["operationId"]
    assert actual.get("security",[]) == expected.get("security",[])
    assert parameters(runtime,path,actual) == parameters(SHARED,path,expected)
    assert resolve(actual.get("requestBody"),runtime) == resolve(expected.get("requestBody"),SHARED)
    assert resolve(actual["responses"],runtime) == resolve(expected["responses"],SHARED)
