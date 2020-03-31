import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run_parallel(*commands):
    import asyncio

    async def _run(*args):
        proc = await asyncio.create_subprocess_shell(*args)
        await proc.communicate()

    tasks = asyncio.gather(*[_run(cmd) for cmd in commands])
    loop = asyncio.get_event_loop()

    try:
        loop.run_until_complete(tasks)
    except KeyboardInterrupt:
        tasks.cancel()
        tasks.add_done_callback(lambda e: loop.stop())
        loop.run_forever()
        tasks.exception()

    loop.close()


def run_sh(*commands):
    import subprocess
    import shlex

    outputs = []
    any_failed = False
    for cmd in commands:
        if not any_failed:
            logger.debug("[ -> sh] %s", cmd)
            try:
                output = subprocess.check_output(cmd, shell=True)
                outputs.append(output)
            except subprocess.SubprocessError:
                logger.error("[ -> sh:failed] %s", cmd)
                outputs.append(None)
                any_failed = True
        else:
            logger.warning("[ -> sh:skipped] %s", cmd)

    return outputs


def install_packages(packages):
    if isinstance(packages, str):
        packages = packages.splitlines()
        packages = [p.strip() for p in packages if not p.strip().startswith("#")]
    packages = " ".join(packages)
    run_sh(f"sudo apt install -y {packages}")


def ensure_folders(*folders, silent=False):
    for f in folders:
        folder = Path(f).expanduser()
        not silent and logger.debug("[ -> folder] Ensure exists %s", folder)
        folder.mkdir(parents=True, exist_ok=True)


def template(src, dst, **context):
    from jinja2 import Template

    src = Path(src).expanduser()
    dst = Path(dst).expanduser()

    with open(src) as _in:
        template = Template(_in.read())
        logger.debug("[ -> template] Rendering %s --> %s", src.name, dst)
        template.stream(**context).dump(str(dst))

    return dst


