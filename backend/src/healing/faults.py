"""Immutable per-request fault options. No process-global scenario state."""
from dataclasses import dataclass


class InjectedFault(TimeoutError):
    pass


@dataclass(frozen=True)
class Faults:
    values: frozenset[str] = frozenset()

    def __post_init__(self):
        if isinstance(self.values, str):
            raise ValueError('fault must be a list/set, not a string')
        values = frozenset(self.values)
        if not values <= {'vital', 'iot', 'vision', 'llm'}:
            raise ValueError('Unknown fault option')
        object.__setattr__(self, 'values', values)

    def check(self, target):
        if target in self.values:
            raise InjectedFault('Injected failure')
