"""indexer 编排服务:fetcher → parser → linker → storage。

build() 是全量索引,update() 是增量(只重解析变动文件)。
"""

from __future__ import annotations

import logging

from ..storage.paths import PathManager
from ..types import RepoIndex, Symbol
from .fetcher import Fetcher
from .fingerprint import diff_files, file_hash
from .linker import CallGraphNode, build_call_graph
from .parser_python import parse_file
from .storage import IndexStorage

logger = logging.getLogger(__name__)


class IndexerService:
    """索引编排服务。"""

    def __init__(self, pm: PathManager) -> None:
        self.pm = pm
        self.fetcher = Fetcher(pm.cache_dir)

    def build(self, repo_url: str) -> RepoIndex:
        """全量索引:clone → 扫所有 .py → parse → linker → 入库。"""
        local_path, commit = self.fetcher.fetch(repo_url)
        repo_hash = self.pm._repo_hash(repo_url)
        storage = IndexStorage(self.pm.index_db_path(repo_url))

        py_files = sorted(local_path.rglob("*.py"))
        # 排除 .git 目录
        py_files = [f for f in py_files if ".git" not in f.parts]

        symbols: list[Symbol] = []
        errors: list[dict] = []
        fingerprints: dict[str, str] = {}
        for f in py_files:
            rel = str(f.relative_to(local_path)).replace("\\", "/")
            try:
                fp = file_hash(f)
                fingerprints[rel] = fp
                file_syms = parse_file(f, rel)
                if not file_syms and f.stat().st_size > 0:
                    # 非空文件抽出 0 符号,可能是语法错误
                    logger.warning("no symbols extracted from %s (possible syntax error)", rel)
                    errors.append(
                        {
                            "file": rel,
                            "stage": "parse",
                            "error": "no symbols extracted (possible syntax error)",
                        }
                    )
                else:
                    symbols.extend(file_syms)
            except Exception as e:
                logger.warning("parse failed for %s: %s", rel, e)
                errors.append({"file": rel, "stage": "parse", "error": str(e)})

        storage.save_symbols(repo_hash, symbols, commit_hash=commit)
        storage.save_fingerprints(repo_hash, fingerprints)
        storage.save_index_errors(repo_hash, errors)

        return RepoIndex(
            repo_url=repo_url,
            commit_hash=commit,
            symbols=symbols,
            files=list(fingerprints.keys()),
            index_errors=errors,
        )

    def update(self, repo_url: str) -> RepoIndex:
        """增量索引:基于已有 fingerprints,只重解析变动文件。

        v1 简化:如果第一次没 build 过,自动走 build()。
        """
        repo_hash = self.pm._repo_hash(repo_url)
        db = self.pm.index_db_path(repo_url)
        if not db.exists():
            return self.build(repo_url)
        local_path, commit = self.fetcher.fetch(repo_url)
        storage = IndexStorage(db)
        old_fps = storage.load_fingerprints(repo_hash)

        py_files = sorted(local_path.rglob("*.py"))
        py_files = [f for f in py_files if ".git" not in f.parts]
        new_fps: dict[str, str] = {}
        for f in py_files:
            rel = str(f.relative_to(local_path)).replace("\\", "/")
            new_fps[rel] = file_hash(f)

        added, modified, deleted, unchanged = diff_files(old_fps, new_fps)

        # 加载已有 symbols
        old_symbols = storage.load_symbols(repo_hash)
        # 删除被删/被改文件的旧 symbols
        to_drop = deleted | modified
        kept = [s for s in old_symbols if s.file not in to_drop]
        # 重新解析 added/modified
        new_symbols: list[Symbol] = []
        errors: list[dict] = []
        for f in py_files:
            rel = str(f.relative_to(local_path)).replace("\\", "/")
            if rel in added or rel in modified:
                try:
                    file_syms = parse_file(f, rel)
                    if not file_syms and f.stat().st_size > 0:
                        logger.warning("no symbols extracted from %s (possible syntax error)", rel)
                        errors.append(
                            {
                                "file": rel,
                                "stage": "parse",
                                "error": "no symbols extracted (possible syntax error)",
                            }
                        )
                    else:
                        new_symbols.extend(file_syms)
                except Exception as e:
                    logger.warning("parse failed for %s: %s", rel, e)
                    errors.append({"file": rel, "stage": "parse", "error": str(e)})
        all_symbols = kept + new_symbols
        storage.save_symbols(repo_hash, all_symbols, commit_hash=commit)
        storage.save_fingerprints(repo_hash, new_fps)
        # 保留旧的 errors,追加新的(简化)
        old_errors = storage.load_index_errors(repo_hash)
        storage.save_index_errors(repo_hash, old_errors + errors)
        return RepoIndex(
            repo_url=repo_url,
            commit_hash=commit,
            symbols=all_symbols,
            files=list(new_fps.keys()),
            index_errors=old_errors + errors,
        )

    def build_call_graph(self, idx: RepoIndex) -> dict[str, CallGraphNode]:
        """从 RepoIndex 构建调用图(给 agent_core 的 trace_call_chain 工具用)。"""
        return build_call_graph(idx.symbols)
