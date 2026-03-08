# Tests: render/file action, conf action, path/dir deps

def main(dep):
    dep.conf(
        setting_a="value_a",
        setting_b="42",
    )
    output_dir = dep["dir::{{ output_root }}/file_renderer"]
    dep.render(
        src="template.conf",
        dst="{{ output_root }}/file_renderer/output.conf",
    )
