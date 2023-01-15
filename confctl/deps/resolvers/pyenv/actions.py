from confctl.deps.action import action, Action, is_action
from .spec import PyEnvDep as Dep


@action(
    "pyenv/install",
    prep_track_data=lambda a, d: {
        "py_version": a.caller.spec.version,
        "venv": a.caller.spec.venv,
        "env_state": a.caller.env_state,
        **d,
    },
)
def install(act: Action):
    assert isinstance(act.caller, Dep), "Can be called only for `Dep` instance"
    dep = act.caller
    spec = dep.spec

    run_sh = act.resolve_action("run/sh")

    if spec.target == "python":
        installed_versions = run_sh("pyenv versions --bare")

        if spec.version not in installed_versions:
            ret = run_sh(f"pyenv install {spec.version}")
            dep.env_state[("python", spec.version)] = (
                "failed" if ret.exitcode else "changed"
            )
        else:
            dep.env_state[("python", spec.version)] = "unchanged"

        if spec.venv not in installed_versions:
            ret = run_sh(f"pyenv virtualenv {spec.version} {spec.venv}")
            dep.env_state[("venv", spec.venv)] = "failed" if ret.exitcode else "changed"
        else:
            dep.env_state[("venv", spec.venv)] = "unchanged"


@action(
    "pyenv/state",
    prep_track_data=lambda a, d: {
        "py_version": a.caller.spec.version,
        "venv": a.caller.spec.venv,
        "env_state": a.caller.env_state,
        **d,
    },
)
def state(act: Action, *state_request):
    assert isinstance(act.caller, Dep), "Can be called only for `Dep` instance"
    dep = act.caller
    spec = dep.spec

    run_sh = act.resolve_action("run/sh")

    match state_request:
        case ("dir",):
            ret = run_sh(f"~/.pyenv/bin/pyenv prefix {spec.venv or spec.version}")
            return ret.output.strip() if ret.exitcode == 0 else None

        case ("pip-installed", *deps):
            installed_deps = run_sh(
                f"$(~/.pyenv/bin/pyenv prefix {spec.venv or spec.version})/bin/pip freeze"
            )
            deps_to_install = [d for d in deps if d not in installed_deps]
            if deps_to_install:
                ret = run_sh(
                    f"$(~/.pyenv/bin/pyenv prefix {spec.venv or spec.version})/bin/pip install {' '.join(deps_to_install)}"
                )
                state = "failed" if ret.exitcode else "changed"
                dep.env_state.update({d: state for d in deps_to_install})
                dep.env_state.update(
                    {
                        ("dependency", d): "unchanged"
                        for d in set(deps) - set(deps_to_install)
                    }
                )
            else:
                state = "unchanged"
                dep.env_state.update({("dependency", d): "unchanged" for d in deps})

            act.progress(env_state=dep.env_state)
            return state

    return dep.state


default_actions = [fn for fn in globals().values() if is_action(fn)]
