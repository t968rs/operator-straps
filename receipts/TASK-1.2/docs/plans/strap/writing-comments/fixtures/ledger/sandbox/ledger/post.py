"""Posting journal entries to accounts."""
from dataclasses import dataclass, field
from typing import List


class Overdraft(Exception):
    pass


@dataclass
class Entry:
    timestamp: float
    seq: int
    amount: int


@dataclass
class Account:
    balance: int = 0
    limit: int = 0
    history: List[Entry] = field(default_factory=list)

    def apply(self, entry: Entry) -> None:
        if self.balance + entry.amount < -self.limit:
            raise Overdraft(f"entry {entry.seq} would overdraw the account")
        self.balance += entry.amount
        self.history.append(entry)


def post_entries(account: Account, entries: List[Entry]) -> int:
    for entry in entries:
        account.apply(entry)
    return account.balance
