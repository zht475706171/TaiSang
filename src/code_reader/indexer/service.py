"""indexer 编排服务:fetcher → parser → linker → storage。

build() 是全量索引,update() 是增量(只重解析变动文件)。
"""

from __future__ import annotations

import logging
from pathlib import Path

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
        self.fetcher = Fetcher()

    def build(self, source_root: Path) -> RepoIndex:
        """全量索引:扫 source_root 下所有 .py → parse → linker → 入库。

        索引产物落 <source_root>/.code-reader/ast.db。
        """
        source_root = source_root.expanduser().resolve()
        commit = self.fetcher.current_commit(source_root)
        storage = IndexStorage(self.pm.index_db_path(source_root))

        py_files = sorted(source_root.rglob("*.py"))
        py_files = [f for f in py_files if ".git" not in f.parts and ".code-reader" not in f.parts]

        symbols: list[Symbol] = []
        errors: list[dict] = []
        fingerprints: dict[str, str] = {}
        for f in py_files:
            rel = str(f.relative_to(source_root)).replace("\\", "/")
            try:
                fp = file_hash(f)
                fingerprints[rel] = fp
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
                    symbols.extend(file_syms)
            except Exception as e:
                logger.warning("parse failed for %s: %s", rel, e)
                errors.append({"file": rel, "stage": "parse", "error": str(e)})

        storage.save_symbols(str(source_root), symbols, commit_hash=commit)
        storage.save_fingerprints(str(source_root), fingerprints)
        storage.save_index_errors(str(source_root), errors)

        return RepoIndex(
            source_root=str(source_root),
            commit_hash=commit,
            symbols=symbols,
            files=list(fingerprints.keys()),
            index_errors=errors,
        )

    def update(self, source_root: Path) -> RepoIndex:
        """增量索引:基于已有 fingerprints,只重解析变动文件。

        v1 简化:如果第一次没 build 过,自动走 build()。
        """
        source_root = source_root.expanduser().resolve()
        db = self.pm.index_db_path(source_root)
        if not db.exists():
            return self.build(source_root)
        commit = self.fetcher.current_commit(source_root)
        storage = IndexStorage(db)
        old_fps = storage.load_fingerprints(str(source_root))

        py_files = sorted(source_root.rglob("*.py"))
        py_files = [f for f in py_files if ".git" not in f.parts and ".code-reader" not in f.parts]
        new_fps: dict[str, str] = {}
        for f in py_files:
            rel = str(f.relative_to(source_root)).replace("\\", "/")
            new_fps[rel] = file_hash(f)

        added, modified, deleted, unchanged = diff_files(old_fps, new_fps)

        old_symbols = storage.load_symbols(str(source_root))
        to_drop = deleted | modified
        kept = [s for s in old_symbols if s.file not in to_drop]
        new_symbols: list[Symbol] = []
        errors: list[dict] = []
        for f in py_files:
            rel = str(f.relative_to(source_root)).replace("\\", "/")
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
        storage.save_symbols(str(source_root), all_symbols, commit_hash=commit)
        storage.save_fingerprints(str(source_root), new_fps)
        old_errors = storage.load_index_errors(str(source_root))
        storage.save_index_errors(str(source_root), old_errors + errors)
        return RepoIndex(
            source_root=str(source_root),
            commit_hash=commit,
            symbols=all_symbols,
            files=list(new_fps.keys()),
            index_errors=old_errors + errors,
        )

    def build_call_graph(self, idx: RepoIndex) -> dict[str, CallGraphNode]:
        """从 RepoIndex 构建调用图(给 agent_core 的 trace_call_chain 工具用)。"""
        return build_call_graph(idx.symbols)
