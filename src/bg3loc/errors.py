from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BG3LocError(Exception):
    code: int
    key: str
    message: str

    def __str__(self) -> str:
        return f"[{self.key}] {self.message}"


class UsageError(BG3LocError):
    def __init__(self, message: str) -> None:
        super().__init__(64, "USAGE_ERROR", message)


class NotImplementedCommandError(BG3LocError):
    def __init__(self, command: str) -> None:
        super().__init__(69, "COMMAND_NOT_IMPLEMENTED", f"Command '{command}' is specified but not implemented yet.")
