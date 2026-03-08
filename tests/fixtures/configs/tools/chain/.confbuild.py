# Tests: dependency chaining — one config depending on another

def main(dep):
    dep["conf::tools/greeter"]
    dep.sh("echo 'chain completed'")
