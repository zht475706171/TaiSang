"""持久 shell:agent 跨多次 Bash 调用复用同一个 shell 进程。

核心动机:Claude Code 风格的"动态 cwd"。每次新 subprocess 会让 `cd` 改的 cwd
随进程死亡丢失;持久 shell 让 `cd` 改的 cwd 跨 Bash 调用保留,后续 Read/Grep/
Glob 等文件工具也能跟随到新目录。

实现选型:管道 + 哨兵(非 pty)。
- 纯 stdlib,跨平台(Unix bash / Windows bash 或 cmd fallback)
- 哨兵法:`echo <token>` 标记命令结束,比 prompt 模式匹配稳
- 缺点:跑全屏 TUI(vim/top)会失败 —— coding agent 场景不需要

接口:
    shell = PipeShell(cwd=Path("/repo"))
    out = shell.run("ls")           # 返回 stdout+stderr 合并文本
    shell.run("cd /other")
    out = shell.run("pwd")          # -> /other  ← cwd 持久化生效
    shell.cwd()                     # -> Path("/other")  Python state 同步
    shell.close()                   # 关 shell 进程

线程安全:单 agent 单 shell,无并发;Web UI per-session Lock 已保证不并发。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

# 哨兵前缀,保证命令输出里不会自然出现。
_SENTINEL_PREFIX = "__TAISANG_DONE_"

# 默认超时秒数。超时后 kill shell + 重启 + 返回 timeout 错误。
_DEFAULT_TIMEOUT = 30

# 输出读取缓冲上限(字节)。超长截断,防 OOM。
_MAX_READ_BYTES = 1_000_000


class PersistentShell:
    """持久 shell 抽象接口。PipeShell 是管道实现;未来可加 PtyShell。"""

    def run(self, command: str, timeout: int | None = None) -> dict:
        """跑命令,返回 {"ok": bool, "output": str, "returncode": int | None}。

        ok: 命令是否成功(returncode == 0 或 shell 内部判定)。
        output: stdout + stderr 合并文本。
        returncode: 退出码(若 shell 能给出;否则 None)。
        """
        raise NotImplementedError

    def cwd(self) -> Path:
        """返回 shell 当前工作目录(Python state 同步值)。"""
        raise NotImplementedError

    def close(self) -> None:
        """关闭 shell 进程,释放资源。"""
        raise NotImplementedError


class PipeShell(PersistentShell):
    """管道 + 哨兵实现的持久 shell。

    工作原理:
    1. 启动时 fork 一个长驻 shell(bash 优先,fallback cmd.exe)
    2. 每次 run():往 stdin 写 `command\n` + `echo <token>\n`
    3. 从 stdout 读,直到读到 token 那一行,停止
    4. 截取 token 之前的所有行作为 output
    5. cd 命令特殊处理:Python state 立刻同步(不依赖 shell 输出)

    cwd 同步:解析命令开头的 `cd <path>`,直接更新 Python state。
    这样 cd 后即使 shell 还没跑完,文件工具也能用新 cwd。
    """

    def __init__(self, cwd: Path, timeout: int = _DEFAULT_TIMEOUT) -> None:
        self._cwd = cwd.resolve()
        self._default_timeout = timeout
        self._counter = 0
        self._proc: subprocess.Popen | None = None
        self._shell_cmd = self._pick_shell()
        self._start()

    @staticmethod
    def _pick_shell() -> list[str]:
        r"""选 shell:优先 Git for Windows 的 bash,跳过 WSL bash。

        为什么跳 WSL bash:WSL 是独立 Linux 子系统,cwd 路径形如 `/mnt/c/...`,
        跟 Windows 原生路径 `C:\...` 不一致 —— 文件工具(用 Windows 路径)和
        Bash(用 WSL 路径)会脱节。Git bash 用 `/c/...` 也不同,但 Git bash
        能直接接受 `C:\...`(Windows 路径),WSL 不能。

        顺序:
        1. Git for Windows bash(检测常见安装路径)
        2. PATH 里的 bash(但要排除 WSL 的 System32\bash.exe)
        3. Unix /bin/sh
        4. Windows cmd.exe fallback
        """
        if os.name == "nt":
            # 常见 Git for Windows bash 路径
            git_bash_candidates = [
                r"C:\Program Files\Git\usr\bin\bash.exe",
                r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
                r"D:\Git\usr\bin\bash.exe",
            ]
            for cand in git_bash_candidates:
                if os.path.isfile(cand):
                    return [cand, "--norc"]
            # PATH 里找 bash,但排除 WSL(System32\bash.exe / WindowsApps\bash.exe)
            from shutil import which

            for name in ("bash", "bash.exe"):
                path = which(name)
                if path and "System32" not in path and "WindowsApps" not in path:
                    return [path, "--norc"]
            # 没 Git bash,fallback cmd.exe
            return ["cmd.exe", "/Q"]
        # Unix:优先 bash,fallback sh
        from shutil import which

        bash_path = which("bash")
        if bash_path:
            return [bash_path, "--norc"]
        return ["/bin/sh"]

    def _start(self) -> None:
        """(重新)启动 shell 进程。"""
        # 用二进制管道 + 手动 TextIOWrapper,因为 subprocess.Popen 不支持 newline 参数。
        # newline="\n" 强制 LF:Windows text mode 默认把 \n 转 \r\n,bash 把 \r 当命令一部分
        # 导致 `$'pwd\r': command not found`。手动包装绕过这个转换。
        try:
            self._proc = subprocess.Popen(
                self._shell_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # stderr 合并进 stdout
                bufsize=0,  # 二进制无缓冲,TextIOWrapper 自己管缓冲
                cwd=str(self._cwd),
            )
        except (OSError, FileNotFoundError) as e:
            log.warning("failed to start shell %s: %s; fallback to sh", self._shell_cmd, e)
            self._shell_cmd = ["/bin/sh"] if os.name != "nt" else ["cmd.exe", "/Q"]
            self._proc = subprocess.Popen(
                self._shell_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                cwd=str(self._cwd),
            )
        # 手动包装成 text stream,强制 LF 换行 + UTF-8
        import io

        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        self._stdin = io.TextIOWrapper(
            self._proc.stdin, encoding="utf-8", errors="replace", newline="\n", line_buffering=True
        )
        self._stdout = io.TextIOWrapper(
            self._proc.stdout, encoding="utf-8", errors="replace", newline="\n"
        )
        # 启动后 drain 掉 banner(WSL/bash 启动可能输出 localhost 警告等噪音)
        self._drain_startup_banner()

    def _ensure_alive(self) -> None:
        """shell 死了就重启。"""
        if self._proc is None or self._proc.poll() is not None:
            log.info("shell dead, restarting (cwd=%s)", self._cwd)
            self._start()

    def _drain_startup_banner(self) -> None:
        """启动后清空 shell banner 输出(WSL localhost 警告 / bash 启动信息)。

        做法:写一个哨兵,读到哨兵为止,丢弃之前的所有输出。这样 banner 噪音
        不会污染第一次 run() 的结果。
        """
        if self._proc is None:
            return
        self._counter += 1
        token = f"{_SENTINEL_PREFIX}{self._counter}_{uuid.uuid4().hex[:8]}"
        try:
            self._stdin.write(f"echo {token}\n")
            self._stdin.flush()
        except (BrokenPipeError, OSError):
            return
        # 短超时读 banner(1s),避免 banner 读完但 shell 卡住时死等
        import time

        deadline = time.time() + 1.0
        while time.time() < deadline:
            line = self._stdout.readline()
            if not line:
                break
            if token in line:
                break

    def cwd(self) -> Path:
        """返回当前 cwd state。"""
        return self._cwd

    def run(self, command: str, timeout: int | None = None, cancel_event=None) -> dict:
        """跑命令,返回 {ok, output, returncode}。

        cancel_event: threading.Event,set 时 kill shell + 重启 + 返回 interrupted=True。
        中断检查周期 0.5s(同 _read_until_token 的 line_q.get timeout)。
        """
        self._ensure_alive()
        timeout = timeout or self._default_timeout

        # cd 特殊处理:更新 Python cwd state + 真正喂给 shell
        # 匹配 `cd <path>` / `cd "<path>"` / `cd '<path>'`,命令开头
        cd_match = re.match(r"^\s*cd\s+(?P<path>[^\s;&|]+|\"[^\"]+\"|'[^']+')\s*$", command)
        if cd_match:
            raw_path = cd_match.group("path").strip("'\"")
            # 解析新 cwd:相对路径基于当前 cwd
            new_path = Path(raw_path)
            if not new_path.is_absolute():
                new_path = self._cwd / new_path
            try:
                resolved = new_path.resolve()
                if not resolved.is_dir():
                    return {
                        "ok": False,
                        "output": f"cd: no such directory: {raw_path}",
                        "returncode": 1,
                    }
            except (OSError, ValueError) as e:
                return {"ok": False, "output": f"cd: {e}", "returncode": 1}
            # 真正喂 cd 给 shell(让 shell 内部 cwd 也变),用哨兵法等完成
            self._counter += 1
            token = f"{_SENTINEL_PREFIX}{self._counter}_{uuid.uuid4().hex[:8]}"
            try:
                self._stdin.write(f"cd {raw_path}\n")
                self._stdin.write(f"echo {token}\n")
                self._stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self._start()
                return {"ok": False, "output": f"shell broken: {e}", "returncode": None}
            # 读到哨兵(cd 通常瞬间完成,但用统一的超时读取逻辑)
            read_result = self._read_until_token(token, timeout, cancel_event)
            if read_result.get("timeout") or read_result.get("shell_died"):
                return {"ok": False, "output": read_result["output"], "returncode": None}
            if read_result.get("interrupted"):
                return {"ok": False, "output": "(interrupted)", "returncode": None, "interrupted": True}
            # cd 成功后更新 Python cwd state
            self._cwd = resolved
            return {"ok": True, "output": "", "returncode": 0}

        # 哨兵 token:计数器 + uuid,保证唯一
        self._counter += 1
        token = f"{_SENTINEL_PREFIX}{self._counter}_{uuid.uuid4().hex[:8]}"

        # 喂命令 + 哨兵
        try:
            self._stdin.write(f"{command}\n")
            self._stdin.write(f"echo {token}\n")
            self._stdin.flush()
        except (BrokenPipeError, OSError) as e:
            log.warning("shell stdin broken: %s; restarting", e)
            self._start()
            return {"ok": False, "output": f"shell broken: {e}", "returncode": None}

        # 读 stdout 直到哨兵行(带超时 + cancel 检查)
        read_result = self._read_until_token(token, timeout, cancel_event)
        if read_result.get("interrupted"):
            return {
                "ok": False,
                "output": read_result.get("output", "") + "(interrupted)",
                "returncode": None,
                "interrupted": True,
            }
        if read_result.get("timeout"):
            return {
                "ok": False,
                "output": read_result["output"] + f"\n(timeout after {timeout}s)",
                "returncode": None,
                "timeout": True,
            }
        if read_result.get("shell_died"):
            return {
                "ok": False,
                "output": read_result["output"],
                "returncode": None,
            }
        return {"ok": True, "output": read_result["output"], "returncode": None}

    def _read_until_token(self, token: str, timeout: int, cancel_event=None) -> dict:
        """读 stdout 直到哨兵行,带超时 + cancel。返回 {output, timeout, shell_died, interrupted}。

        Windows 管道 readline 阻塞,用后台线程 + Queue 实现超时打断。
        超时:kill shell + 重启 + 返回 timeout=True。
        shell 死:返回 shell_died=True(已重启)。
        cancel_event set:kill shell + 重启 + 返回 interrupted=True(对标 Claude Code kill 子进程)。
        """
        import queue as _queue
        import threading as _threading
        import time as _time

        line_q: _queue.Queue[str | None] = _queue.Queue()
        reader_done = _threading.Event()

        def _reader() -> None:
            try:
                while True:
                    line = self._stdout.readline()
                    if not line:
                        line_q.put(None)
                        break
                    line_q.put(line)
                    if token in line:
                        break
            except (BrokenPipeError, OSError):
                line_q.put(None)
            finally:
                reader_done.set()

        reader_thread = _threading.Thread(target=_reader, daemon=True)
        reader_thread.start()

        lines: list[str] = []
        total_bytes = 0
        deadline = _time.time() + timeout

        while _time.time() < deadline:
            # 中断检查:cancel_event set → kill shell + 重启 + 返回 interrupted
            if cancel_event is not None and cancel_event.is_set():
                log.info("shell command interrupted by user, killing shell")
                self._kill_and_restart()
                reader_done.wait(timeout=2)
                return {
                    "output": "".join(lines),
                    "timeout": False,
                    "shell_died": False,
                    "interrupted": True,
                }
            try:
                line = line_q.get(timeout=0.5)
            except _queue.Empty:
                continue
            if line is None:
                # shell 死了
                log.warning("shell EOF during read, restarting")
                self._start()
                reader_done.wait(timeout=2)
                return {
                    "output": "".join(lines) + "(shell died, restarted)",
                    "timeout": False,
                    "shell_died": True,
                    "interrupted": False,
                }
            if token in line:
                reader_done.wait(timeout=2)
                return {"output": "".join(lines), "timeout": False, "shell_died": False, "interrupted": False}
            lines.append(line)
            total_bytes += len(line.encode("utf-8"))
            if total_bytes > _MAX_READ_BYTES:
                lines.append(f"\n... [output truncated at {_MAX_READ_BYTES} bytes]")
                reader_done.wait(timeout=2)
                return {"output": "".join(lines), "timeout": False, "shell_died": False, "interrupted": False}

        # 超时:kill shell + 重启
        log.warning("shell command timeout after %ss", timeout)
        self._kill_and_restart()
        reader_done.wait(timeout=2)
        return {
            "output": "".join(lines),
            "timeout": True,
            "shell_died": False,
            "interrupted": False,
        }

    def _kill_and_restart(self) -> None:
        """超时或异常时:kill 当前 shell,重启一个干净的(cwd 保持)。"""
        if self._proc is not None:
            try:
                self._proc.kill()
            except (OSError, ProcessLookupError):
                pass
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        self._start()

    def close(self) -> None:
        """关闭 shell。"""
        if self._proc is None:
            return
        try:
            self._stdin.write("exit\n")
            self._stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            self._stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            self._stdout.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                self._proc.kill()
            except (OSError, ProcessLookupError):
                pass
        self._proc = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001 — 析构期不容错抛
            pass
