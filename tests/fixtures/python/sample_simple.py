"""一个简单的 fixture 文件,用于测试 parser。"""
import os
from pathlib import Path


def greet(name: str) -> str:
    """Greet someone."""
    return f"hello, {name}"


def main():
    name = os.environ.get("USER", "world")
    print(greet(name))
    Path("log.txt").write_text("done")


if __name__ == "__main__":
    main()