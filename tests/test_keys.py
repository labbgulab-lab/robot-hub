"""The hub's key store: the only place a speaking key lives."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.keys import KeyError_, KeyStore  # noqa: E402

GEM = "AIzaSyGEMINIsecret0001"
OAI = "sk-openaiSECRET0002"


def test_public_view_never_contains_a_secret(tmp_path):
    store = KeyStore(tmp_path / "k.json")
    store.add("gemini", "Lab Gemini", GEM)
    store.add("gpt", "OpenAI", OAI)
    blob = json.dumps(store.public())
    assert GEM not in blob and OAI not in blob
    assert "0001" in blob and "0002" in blob          # the last four, to tell apart


def test_keys_survive_a_restart_and_assignments_follow(tmp_path):
    path = tmp_path / "k.json"
    store = KeyStore(path)
    kid = store.add("gpt", "OpenAI", OAI)["id"]
    store.assign("robotA", kid)
    again = KeyStore(path)
    entry, how = again.for_robot("robotA")
    assert entry["key"] == OAI and how == "assigned"


def test_unassigned_robot_falls_back_to_the_first_gemini_key(tmp_path):
    store = KeyStore(tmp_path / "k.json")
    store.add("qwen", "Qwen", "sk-qwen-secret-3")
    store.add("gemini", "Lab Gemini", GEM)
    entry, how = store.for_robot("robotB")
    assert entry["key"] == GEM and "first Gemini" in how


def test_deleting_a_key_unassigns_it(tmp_path):
    store = KeyStore(tmp_path / "k.json")
    kid = store.add("gpt", "OpenAI", OAI)["id"]
    store.assign("robotA", kid)
    store.remove(kid)
    entry, _how = store.for_robot("robotA")
    assert entry is None
    assert store.public()["assign"] == {}


def test_bad_input_is_refused_with_a_sentence(tmp_path):
    store = KeyStore(tmp_path / "k.json")
    with pytest.raises(KeyError_):
        store.add("claude", "x", GEM)                   # not a provider we list
    with pytest.raises(KeyError_):
        store.add("gemini", "x", "short")
    store.add("gemini", "x", GEM)
    with pytest.raises(KeyError_):
        store.add("gemini", "dup", GEM)                 # same secret twice
    with pytest.raises(KeyError_):
        store.assign("robotA", "k-does-not-exist")


def test_first_run_imports_the_existing_gemini_key(tmp_path):
    token = tmp_path / "token.txt"
    token.write_text(GEM + "\n", encoding="utf-8")
    store = KeyStore(tmp_path / "k.json")
    store._seed(token)
    entry, _how = store.for_robot("any")
    assert entry["key"] == GEM and entry["label"] == "Lab Gemini"


def test_the_api_adds_lists_assigns_and_never_echoes_a_secret(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from hub import main

    monkeypatch.setattr(main.hub, "keys", KeyStore(tmp_path / "k.json"))
    client = TestClient(main.app)

    added = client.post("/api/keys", json={"provider": "gpt", "label": "OpenAI",
                                           "key": OAI}).json()
    assert added["ok"] and OAI not in json.dumps(added)
    kid = added["keys"][0]["id"]

    assert client.post("/api/keys", json={"provider": "gpt", "key": OAI}).json()["ok"] is False
    assert client.put("/api/robots/robotA/key", json={"key_id": kid}).json()["assign"] == {"robotA": kid}
    listed = client.get("/api/keys").json()
    assert OAI not in json.dumps(listed) and listed["keys"][0]["tail"] == "0002"
    assert client.delete("/api/keys/" + kid).json()["keys"] == []


def test_launch_env_carries_one_key_per_provider(tmp_path):
    store = KeyStore(tmp_path / "k.json")
    store.add("gemini", "Lab Gemini", GEM)
    second = store.add("gemini", "Gemini #2", "AIzaSyGEMINIsecret0009")["id"]
    store.add("gpt", "OpenAI", OAI)
    store.add("elevenlabs", "ElevenLabs", "el-secret-0003")
    store.add("qwen", "Qwen", "sk-qwen-secret-3")
    store.assign("robotA", second)
    env = store.env_for_robot("robotA")
    assert env == {"GEMINI_API_KEY": "AIzaSyGEMINIsecret0009",   # its own pick wins
                   "OPENAI_API_KEY": OAI,
                   "ELEVENLABS_API_KEY": "el-secret-0003"}       # no Qwen backend
    assert store.env_for_robot("robotB")["GEMINI_API_KEY"] == GEM
