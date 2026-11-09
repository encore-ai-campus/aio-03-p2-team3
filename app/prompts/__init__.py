from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    NAME: str
    VERSION: str
    TEMPLATE: str

    @property
    def version(self) -> str:
        return f"{self.NAME}.{self.VERSION}"
