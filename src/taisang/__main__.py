"""python -m taisang 入口。

让 `python -m taisang doc <repo>` 可用,等价于 `taisang doc <repo>`。
"""

from taisang.cli.main import cli

if __name__ == "__main__":
    cli()
