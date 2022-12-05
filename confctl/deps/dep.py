import typing as t

from dataclasses import dataclass, field
from functools import cache

from .ctx import Ctx
from .spec import Spec


@dataclass
class Dep:
    # user-defined dependency spec
    spec: Spec
    # context with globally available and dependency-level values
    ctx: Ctx

    # actions that can be triggered on dependency
    actions: dict[str, t.Callable] = field(default_factory=dict)

    # do not trigger error globally
    failsafe: bool = False

    # arbitrary options passed to UI
    class UIOptions(t.TypedDict, total=False):
        visibility: t.Literal["hidden", "visible"]

    ui_options: UIOptions = field(default_factory=UIOptions)

    def __getattr__(self, name):
        """Proxies attribute access to target's configuration."""
        if name in self.actions:
            return self.get_action(name)
        return getattr(self.ctx, name)

    def __hash__(self) -> int:
        return hash(self.spec)

    def __call__(self, *deps: str, **conf):
        self.conf(**conf)

        for dep in deps:
            self.dep(dep)

    @cache
    def get_action(self, action_name: str):
        fn = next(
            (
                f
                for f_name, f in self.actions.items()
                if action_name == f_name
                or getattr(f, "__confclt_action_name__", "") == action_name
            ),
            None,
        )

        if fn is None:
            fn = self.ctx[action_name]  # TODO: improve how actions are stored in `ctx`

        if callable(fn):
            return lambda *args, **kwargs: fn(
                *args, **kwargs, __ctx=self.ctx, __caller=self
            )

        raise RuntimeError(
            f"Cannot resolve {action_name} action for {self.spec} dependency."
        )
