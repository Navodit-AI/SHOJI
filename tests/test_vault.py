"""The encrypted placeholder vault."""

import logging
import os
import stat

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from shoji.app import create_app
from shoji.config import Settings
from shoji.redact import Mapping, redact_messages
from shoji.synthetic import generate
from shoji.vault import Vault, VaultError, open_vault

KEY = Fernet.generate_key().decode()


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def path(tmp_path):
    return tmp_path / "vault.db"


def sample_mapping():
    m = Mapping()
    m.placeholder_for("PHONE", "+91 98765 43210")
    m.placeholder_for("PAN", "ABCPD1234F")
    m.placeholder_for("PHONE", "91234 56780")
    return m


def test_save_and_load_round_trip(path):
    vault = Vault(path, KEY)
    vault.save("conv-1", sample_mapping())
    loaded = Vault(path, KEY).load("conv-1")  # a fresh process sees the same data
    assert list(loaded.items()) == list(sample_mapping().items())
    assert loaded.type_of("<PAN_1>") == "PAN"


def test_loaded_mapping_continues_numbering_and_reuses_values(path):
    vault = Vault(path, KEY)
    vault.save("c", sample_mapping())
    m = vault.load("c")
    assert m.placeholder_for("PHONE", "+91-98765-43210") == "<PHONE_1>"  # same value
    assert m.placeholder_for("PHONE", "99999 88888") == "<PHONE_3>"  # new one numbered after
    vault.save("c", m)
    assert [p for p, _ in vault.load("c").items()] == [
        "<PHONE_1>",
        "<PAN_1>",
        "<PHONE_2>",
        "<PHONE_3>",
    ]


def test_trimmed_history_keeps_placeholders(path):
    vault = Vault(path, KEY)
    turn1 = redact_messages([{"role": "user", "content": "PAN ABCPD1234F, phone 98765 43210"}])
    vault.save("c", turn1.mapping)
    # The client dropped the first message; the phone still gets <PHONE_1>.
    turn2 = redact_messages(
        [{"role": "user", "content": "call 98765 43210 again"}], mapping=vault.load("c")
    )
    assert turn2.messages[0]["content"] == "call <PHONE_1> again"


def test_conversations_are_separate(path):
    vault = Vault(path, KEY)
    vault.save("a", sample_mapping())
    assert len(vault.load("b")) == 0
    assert len(vault.load("a")) == 3


def test_saving_twice_is_idempotent(path):
    vault = Vault(path, KEY)
    vault.save("c", sample_mapping())
    vault.save("c", sample_mapping())
    assert len(vault.load("c")) == 3


def test_delete(path):
    vault = Vault(path, KEY)
    vault.save("c", sample_mapping())
    assert vault.delete("c") is True
    assert len(vault.load("c")) == 0
    assert vault.delete("c") is False
    rows = vault._db.execute("SELECT COUNT(*) FROM vault_entries").fetchone()[0]
    assert rows == 0  # entries go with their conversation


def test_ttl(path):
    clock = Clock()
    vault = Vault(path, KEY, ttl_hours=1, clock=clock)
    vault.save("old", sample_mapping())
    clock.t += 1800
    vault.save("new", sample_mapping())
    clock.t += 2400  # "old" last saved 70 min ago, "new" 40 min ago
    assert len(vault.load("old")) == 0
    assert len(vault.load("new")) == 3
    clock.t += 1800
    assert vault.expire() == 1
    assert len(vault.load("new")) == 0


def test_saving_refreshes_expiry(path):
    clock = Clock()
    vault = Vault(path, KEY, ttl_hours=1, clock=clock)
    vault.save("c", sample_mapping())
    clock.t += 3000
    vault.save("c", vault.load("c"))
    clock.t += 3000
    assert len(vault.load("c")) == 3


def test_no_plaintext_in_database_file(path):
    vault = Vault(path, KEY)
    secrets = set()
    for i, s in enumerate(generate(200, seed=25)):
        m = Mapping()
        for g in s.spans:
            m.placeholder_for(g.type, g.text)
            secrets.add(g.text)
        vault.save(f"conversation-{i}", m)
    vault.close()
    raw = b"".join(p.read_bytes() for p in path.parent.iterdir())  # db plus any journal
    leaked = [v for v in secrets if v.encode() in raw or v.lower().encode() in raw]
    assert leaked == []
    assert b"conversation-1" not in raw


def test_file_is_owner_only(path):
    Vault(path, KEY).close()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_wrong_key_fails_clearly(path):
    Vault(path, KEY).save("c", sample_mapping())
    with pytest.raises(VaultError, match="does not match"):
        Vault(path, Fernet.generate_key().decode())


@pytest.mark.parametrize("bad", ["not-a-key", "", "a" * 44])
def test_invalid_key_rejected(path, bad):
    with pytest.raises(VaultError, match="python -m shoji.vault"):
        Vault(path, bad)


def test_open_vault_without_key_warns(path, caplog):
    with caplog.at_level(logging.WARNING, logger="shoji.vault"):
        assert open_vault("", path, 24) is None
    assert len(caplog.records) == 1 and "SHOJI_VAULT_KEY" in caplog.text
    assert not path.exists()


def test_open_vault_expires_old_conversations(path):
    clock = Clock(0)
    Vault(path, KEY, ttl_hours=1, clock=clock).save("c", sample_mapping())
    vault = open_vault(KEY, path, ttl_hours=1)  # real clock: decades later
    assert vault._db.execute("SELECT COUNT(*) FROM vault_conversations").fetchone()[0] == 0


def test_app_opens_vault_at_startup(path):
    settings = Settings(_env_file=None, groq_api_key="k", shoji_vault_key=KEY,
                        shoji_vault_path=str(path))  # fmt: skip
    with TestClient(create_app(settings)) as client:
        assert isinstance(client.app.state.vault, Vault)
    assert path.exists()


def test_app_with_bad_key_fails_at_startup(path):
    settings = Settings(_env_file=None, groq_api_key="k", shoji_vault_key="nope",
                        shoji_vault_path=str(path))  # fmt: skip
    with pytest.raises(VaultError), TestClient(create_app(settings)):
        pass


def test_app_without_key_has_no_vault():
    with TestClient(create_app(Settings(_env_file=None, groq_api_key="k"))) as client:
        assert client.app.state.vault is None


def test_mapping_add_existing_validation():
    m = Mapping()
    m.add_existing("<PHONE_4>", "PHONE", "9876543210")
    assert m.placeholder_for("PHONE", "9123456780") == "<PHONE_5>"
    with pytest.raises(ValueError):
        m.add_existing("<PHONE_4>", "PHONE", "9999999999")  # placeholder taken
    with pytest.raises(ValueError):
        m.add_existing("<PHONE_9>", "PHONE", "98765 43210")  # value taken
    with pytest.raises(ValueError):
        m.add_existing("<PAN_1>", "PHONE", "9000000000")  # wrong type
