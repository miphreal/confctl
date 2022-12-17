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
    actions: list[t.Callable] = field(default_factory=list)
    _actions_map: dict[str, t.Callable] = field(default_factory=dict)

    # do not trigger error globally
    failsafe: bool = False

    # arbitrary options passed to UI
    class UIOptions(t.TypedDict, total=False):
        visibility: t.Literal["hidden", "visible"]

    ui_options: UIOptions = field(default_factory=UIOptions)

    def __post_init__(self):
        from .action import get_action_name

        for fn in self.actions:
            # the actions are accessible by function name of by its alias
            self._actions_map[fn.__name__] = fn
            action_name = get_action_name(fn)
            if action_name:
                self._actions_map[action_name] = fn

    def __getattr__(self, name):
        """Proxies attribute access to target's configuration."""
        if name in self._actions_map:
            return self.get_action(name)
        return getattr(self.ctx, name)

    def __hash__(self) -> int:
        return hash(self.spec)

    @cache
    def get_action(self, action_name: str):
        fn = self._actions_map.get(action_name)
        if callable(fn):
            return lambda *args, **kwargs: fn(
                *args, **kwargs, __ctx=self.ctx, __caller=self
            )

        raise RuntimeError(
            f"Cannot resolve {action_name} action for {self.spec} dependency."
        )
