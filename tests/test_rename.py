"""Things stored under the old name (AutoCV) keep working after the rename to TailorbirdCV."""

from tailorbirdcv import apikey, pdf

KEY = "sk-ant-" + "x" * 40


def test_a_key_stored_under_the_old_name_moves_to_the_new_one(memory_keyring):
    memory_keyring.set_password("AutoCV", "anthropic-api-key", KEY)
    assert apikey.get("anthropic") == (KEY, "keychain")
    assert memory_keyring.store == {("TailorbirdCV", "anthropic-api-key"): KEY}  # moved, not copied
    assert apikey.get("anthropic") == (KEY, "keychain")


def test_deleting_a_key_also_clears_the_old_entry(memory_keyring):
    memory_keyring.set_password("AutoCV", "openai-api-key", "sk-" + "y" * 40)
    apikey.delete("openai")
    assert apikey.get("openai") == (None, None)


def test_libreoffice_rules_written_before_the_rename_are_replaced_not_duplicated(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "installed", lambda family: False)
    xcu = tmp_path / "user" / "registrymodifications.xcu"
    xcu.parent.mkdir(parents=True)
    old_rule = (f'<item oor:path="{pdf._SUBST_PATH}/FontPairs"><node oor:name="autocv-georgia" oor:op="replace">'
                '<prop oor:name="ReplaceFont" oor:op="fuse"><value>Georgia</value></prop></node></item>\n')
    xcu.write_text(pdf._XCU_EMPTY.replace("</oor:items>", old_rule + "</oor:items>"), encoding="utf-8")
    pdf.configure_substitutes(tmp_path, {"Georgia"})
    text = xcu.read_text(encoding="utf-8")
    assert "autocv-georgia" not in text and text.count('oor:name="tailorbirdcv-georgia"') == 1
