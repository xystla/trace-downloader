import json
from pathlib import Path
import yaml
from trace_grabber.accounts import (
    Account, Accounts, slugify, load_accounts, save_accounts,
    add_account, remove_account, set_active,
)

def test_slugify():
    assert slugify("Demo FC") == "demo-fc"
    assert slugify("Athletic!! 2") == "athletic-2"

def test_account_paths(tmp_path):
    a = Account(id="x", label="Demo FC", profile_dir="profiles/x",
                team_urls=["u"])
    assert a.profile_path(tmp_path) == tmp_path / "profiles" / "x"
    assert a.state_path(tmp_path) == tmp_path / "state" / "x.json"
    assert a.output_dir(tmp_path / "Vids") == tmp_path / "Vids" / "Demo FC"

def test_migration_from_chrome_profile(tmp_path):
    (tmp_path / ".chrome-profile").mkdir()
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(
        {"output_dir": "~/V", "check_interval_hours": 3, "quality": "highest",
         "team_urls": ["https://go.traceup.com/traceid/team/demoteam1"]}))
    (tmp_path / "state.json").write_text(json.dumps(["g-1"]))
    accts = load_accounts(tmp_path)
    assert len(accts.items) == 1
    a = accts.active
    assert a is not None
    assert a.profile_dir == ".chrome-profile"
    assert a.team_urls == ["https://go.traceup.com/traceid/team/demoteam1"]
    # prior history copied to the per-account state file
    assert json.loads(a.state_path(tmp_path).read_text()) == ["g-1"]
    # accounts.json now persisted
    assert (tmp_path / "accounts.json").exists()

def test_add_and_set_active(tmp_path):
    accts = Accounts(active_id="a", items=[Account("a", "A", "profiles/a", ["ua"])])
    save_accounts(tmp_path, accts)
    b = add_account(tmp_path, accts, label="Bee", team_urls=["ub"], profile_dir="profiles/bee")
    assert b.id == "bee"
    assert accts.active_id == "bee"
    reloaded = load_accounts(tmp_path)
    assert {x.id for x in reloaded.items} == {"a", "bee"}
    set_active(tmp_path, reloaded, "a")
    assert load_accounts(tmp_path).active_id == "a"

def test_remove_account_switches_active(tmp_path):
    accts = Accounts(active_id="a", items=[
        Account("a", "A", "profiles/a", ["ua"]),
        Account("b", "B", "profiles/b", ["ub"])])
    (tmp_path / "profiles" / "a").mkdir(parents=True)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "a.json").write_text("[]")
    save_accounts(tmp_path, accts)
    remove_account(tmp_path, accts, "a")
    assert accts.active_id == "b"
    assert not (tmp_path / "profiles" / "a").exists()
    assert not (tmp_path / "state" / "a.json").exists()

def test_migration_empty_when_no_profile(tmp_path):
    from trace_grabber.accounts import load_accounts
    accts = load_accounts(tmp_path)  # no .chrome-profile, no config
    assert accts.items == []
    assert accts.active_id is None

def test_remove_account_deletes_saved_analytics(tmp_path):
    acct = Account("a", "A", "profiles/a", ["ua"])
    assert acct.analytics_dir(tmp_path) == tmp_path / "analytics" / "a"
    accts = Accounts(active_id="a", items=[acct])
    acct.analytics_dir(tmp_path).mkdir(parents=True)
    (acct.analytics_dir(tmp_path) / "7.json").write_text("{}")
    save_accounts(tmp_path, accts)
    remove_account(tmp_path, accts, "a")
    assert not acct.analytics_dir(tmp_path).exists()

def test_remove_account_deletes_saved_thumbnails(tmp_path):
    acct = Account("a", "A", "profiles/a", ["ua"])
    assert acct.thumbs_dir(tmp_path) == tmp_path / "thumbs" / "a"
    accts = Accounts(active_id="a", items=[acct])
    acct.thumbs_dir(tmp_path).mkdir(parents=True)
    (acct.thumbs_dir(tmp_path) / "a-7.jpg").write_bytes(b"x")
    save_accounts(tmp_path, accts)
    remove_account(tmp_path, accts, "a")
    assert not acct.thumbs_dir(tmp_path).exists()
