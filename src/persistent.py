import contextlib
import os
from typing import Optional


class PersistentString:
    """A string wrapper which is persistent across reboots.

    Methods:
        get(value):
            Gets the value of the string
        set(value):
            Sets the value of the string and writes to disk
    """

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self._value: Optional[str] = None
        # Load string if it exists
        with contextlib.suppress(FileNotFoundError):
            with open(self.filepath, "r") as f:
                self._value = f.read()

    def set(self, value: Optional[str]):
        self._value = value

        # Either save string, or delete state file if None
        if self._value is None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(self.filepath)
        else:
            with open(self.filepath, "w") as f:
                f.write(self._value)

    def get(self) -> Optional[str]:
        return self._value
