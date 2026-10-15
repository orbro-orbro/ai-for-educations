"""Shared assertions for the approved server-generated correlation policy."""
import re


def server_id(response, inbound=None):
    identifier = response.headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", identifier)
    assert identifier != inbound
    return identifier


def public_error(response, inbound=None):
    body = response.json()
    assert set(body) == {"code", "message", "request_id"}
    assert body["request_id"] == server_id(response, inbound)
    return {key: value for key, value in body.items() if key != "request_id"}
