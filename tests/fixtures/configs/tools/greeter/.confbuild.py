# Tests: sh action, conf action, msg action, context access

def main(dep):
    dep.conf(target_name="world")
    dep.msg("{{ greeting }}, {{ target_name }}!")
    result = dep.sh("echo '{{ greeting }} from shell'")
    dep.conf(shell_output=result.output.strip())
