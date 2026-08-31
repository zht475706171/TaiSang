"""python -m code_reader 入口。

让 `python -m code_reader doc <repo>` 可用,等价于 `code-reader doc <repo>`。
"""

from code_reader.cli.main import cli

if __name__ == "__main__":
    cli()
