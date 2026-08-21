"""含 class 和 method 的 fixture。"""
from typing import List


class Stack:
    def __init__(self):
        self.items: List[int] = []

    def push(self, x: int) -> None:
        self.items.append(x)

    def pop(self) -> int:
        return self.items.pop()


def use_stack():
    s = Stack()
    s.push(1)
    return s.pop()