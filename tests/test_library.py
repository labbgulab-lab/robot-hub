"""The shared robot-file library never uploads a key (hub/keyscrub.py), and
reads back what it stored (hub/library.py). Offline: no GitHub here."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import keyscrub  # noqa: E402
from hub.library import LibraryError, _public, asset_name, safe_name  # noqa: E402

FAKE_OPENAI = "sk-proj-" + "A1b2C3d4E5" * 4


def _skill(path: Path, props: str, extra: dict[str, bytes] | None = None) -> Path:
    """A miniature Furhat skill: manifest first, the key file, a class."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        z.writestr("furhatchat/openai.properties", props)
        z.writestr("furhatos/app/Main.class", b"\xca\xfe\xba\xbe task-runner-thread-pool-executor")
        # Bundled libraries: error texts with secret-sounding names, the bare
        # PEM marker, and a public test key in a class -- none is ours.
        z.writestr("com/mysql/cj/LocalizedErrorMessages.properties",
                   "ConnectionProperties.Password=The password to use when connecting\n")
        z.writestr("furhatos/telemetry/TelemetryModule.class",
                   b"\x00-----BEGIN PRIVATE KEY-----\x00replace")
        z.writestr("io/netty/OpenSsl.class",
                   b"-----BEGIN PRIVATE KEY-----\n" + b"MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" * 3)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def test_the_key_is_removed_and_its_slot_remembered(tmp_path):
    src = _skill(tmp_path / "Chat.skill", "#built\napiKey=" + FAKE_OPENAI + "\n")
    work = tmp_path / "work"
    work.mkdir()
    result = keyscrub.scrub(src, work)
    assert result.removed == ["furhatchat/openai.properties#apiKey"]
    assert [(s.entry, s.prop, s.provider) for s in result.slots] == [
        ("furhatchat/openai.properties", "apiKey", "gpt")]
    with zipfile.ZipFile(result.path) as z:
        assert z.read("furhatchat/openai.properties") == b"#built\napiKey=\n"
        assert z.infolist()[0].filename == "META-INF/MANIFEST.MF"
        # A library's error text is not a secret, however it is named.
        assert b"The password to use" in z.read("com/mysql/cj/LocalizedErrorMessages.properties")
    assert FAKE_OPENAI.encode() not in result.path.read_bytes()


def test_a_keyless_file_is_uploaded_as_it_is(tmp_path):
    src = _skill(tmp_path / "Chat.skill", "apiKey=\n")
    result = keyscrub.scrub(src, tmp_path)
    assert result.path == src and result.removed == []
    assert [s.prop for s in result.slots] == ["apiKey"]


def test_a_key_compiled_into_a_class_refuses_the_upload(tmp_path):
    src = _skill(tmp_path / "Chat.skill", "apiKey=\n",
                 {"furhatos/app/Key.class": b"\x01\x00" + FAKE_OPENAI.encode()})
    with pytest.raises(keyscrub.KeyFound, match="Key.class"):
        keyscrub.scrub(src, tmp_path)


def test_this_laptops_own_key_is_refused_whatever_its_shape(tmp_path):
    own = "Zq81-own-lab-key-without-a-known-prefix"
    src = tmp_path / "notes.txt"
    src.write_text("remember: " + own)
    with pytest.raises(keyscrub.KeyFound, match="this laptop's own keys"):
        keyscrub.scrub(src, tmp_path, keyscrub.known_secrets([own]))


def test_a_private_key_in_a_resource_is_refused(tmp_path):
    src = _skill(tmp_path / "Chat.skill", "apiKey=\n",
                 {"certs/robot.pem": b"-----BEGIN PRIVATE KEY-----\n" + b"A" * 64})
    with pytest.raises(keyscrub.KeyFound, match="private key"):
        keyscrub.scrub(src, tmp_path)


def test_plain_files_without_keys_pass(tmp_path):
    src = tmp_path / "behaviour.py"
    src.write_text("def run(robot):\n    robot.say('hello')\n")
    assert keyscrub.scrub(src, tmp_path).path == src


def test_download_puts_the_chosen_key_back(tmp_path):
    src = _skill(tmp_path / "Chat.skill", "apiKey=\n")
    out = tmp_path / "mine.skill"
    assert keyscrub.inject(src, out, "gpt", FAKE_OPENAI) == 1
    with zipfile.ZipFile(out) as z:
        assert z.read("furhatchat/openai.properties") == ("apiKey=" + FAKE_OPENAI + "\n").encode()
        assert z.testzip() is None
    # A Gemini key has no place in an OpenAI skill.
    assert keyscrub.inject(src, tmp_path / "other.skill", "gemini", "AIza" + "x" * 35) == 0


def test_asset_names_carry_the_robot():
    assert asset_name("furhat", "OpenAIChat 1.3.0.skill") == "furhat__OpenAIChat_1.3.0.skill"
    assert safe_name(r"C:\fakepath\a b.zip") == "a_b.zip"
    with pytest.raises(LibraryError):
        safe_name("...")


def test_listing_reads_robot_and_key_needs_back():
    item = _public({"id": 7, "name": "furhat__OpenAIChat_1.3.0.skill", "size": 10,
                    "label": "keyless; needs gpt", "updated_at": "2026-10-06T08:00:00Z",
                    "uploader": {"login": "labbgulab-lab"}})
    assert item["robot"] == "furhat" and item["name"] == "OpenAIChat_1.3.0.skill"
    assert item["needs"] == ["gpt"] and item["keyless"]
    # Something else attached to the release by hand is not shown.
    assert _public({"id": 8, "name": "notes.txt"}) is None
