from __future__ import annotations


class DocaiError(Exception):
    """Base class for all docai errors."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def format_compact(self) -> str:
        """Render the error chain as: [CODE] message → [CODE] message → ..."""
        parts: list[str] = []
        current: BaseException | None = self
        while current is not None and isinstance(current, DocaiError):
            parts.append(f"[{current.code}] {current.message}")
            current = current.__cause__
        return " → ".join(parts)
