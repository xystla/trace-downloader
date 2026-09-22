import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

def slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")

def _safe_dir(label: str) -> str:
    return re.sub(r"[/\\:]+", "-", label).strip() or "Account"

@dataclass
class Account:
    id: str
    label: str
    profile_dir: str
    team_urls: list[str]

    def profile_path(self, root) -> Path:
        return Path(root) / self.profile_dir

    def state_path(self, root) -> Path:
        return Path(root) / "state" / f"{self.id}.json"

    def output_dir(self, base) -> Path:
        return Path(base) / _safe_dir(self.label)

@dataclass
class Accounts:
    active_id: str | None
    items: list[Account] = field(default_factory=list)

    @property
    def active(self) -> Account | None:
        return self.get(self.active_id)

    def get(self, account_id) -> Account | None:
        return next((a for a in self.items if a.id == account_id), None)

def _path(root) -> Path:
    return Path(root) / "accounts.json"

def save_accounts(root, accounts: Accounts) -> None:
    data = {"active": accounts.active_id,
            "accounts": [vars(a) for a in accounts.items]}
    _path(root).write_text(json.dumps(data, indent=2))

def load_accounts(root) -> Accounts:
    p = _path(root)
    if not p.exists():
        return _migrate(root)
    data = json.loads(p.read_text(encoding="utf-8"))
    items = [Account(**a) for a in data["accounts"]]
    return Accounts(active_id=data.get("active"), items=items)

def _migrate(root) -> Accounts:
    root = Path(root)
    if not (root / ".chrome-profile").exists():
        accounts = Accounts(active_id=None, items=[])
        save_accounts(root, accounts)
        return accounts
    team_urls = []
    cfg = root / "config.yaml"
    if cfg.exists():
        team_urls = yaml.safe_load(cfg.read_text(encoding="utf-8")).get("team_urls", []) or []
    acct = Account(id="account-1", label="Account 1",
                   profile_dir=".chrome-profile", team_urls=team_urls)
    accounts = Accounts(active_id=acct.id, items=[acct])
    old_state = root / "state.json"
    if old_state.exists():
        dest = acct.state_path(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(old_state, dest)
    save_accounts(root, accounts)
    return accounts

def add_account(root, accounts: Accounts, label: str, team_urls: list[str],
                profile_dir: str) -> Account:
    acct = Account(id=slugify(label) or f"account-{len(accounts.items)+1}",
                   label=label, profile_dir=profile_dir, team_urls=team_urls)
    accounts.items.append(acct)
    accounts.active_id = acct.id
    save_accounts(root, accounts)
    return acct

def set_active(root, accounts: Accounts, account_id: str) -> None:
    if accounts.get(account_id):
        accounts.active_id = account_id
        save_accounts(root, accounts)

def remove_account(root, accounts: Accounts, account_id: str) -> None:
    acct = accounts.get(account_id)
    if not acct:
        return
    shutil.rmtree(acct.profile_path(root), ignore_errors=True)
    acct.state_path(root).unlink(missing_ok=True)
    accounts.items = [a for a in accounts.items if a.id != account_id]
    if accounts.active_id == account_id:
        accounts.active_id = accounts.items[0].id if accounts.items else None
    save_accounts(root, accounts)
