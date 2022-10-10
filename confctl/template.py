from dataclasses import dataclass
from typing import Callable

from jinja2 import Template as JinjaTemplate


@dataclass
class LazyTemplate:
    template: str
    render: Callable[[str], str]

    def __str__(self) -> str:
        return self.render(self.template)


Template = JinjaTemplate
