"""Hydroweave 运行清单（repro）子包。

从 :mod:`hydroweave.repro.manifest` 重新导出常用名字，调用方可用
``from hydroweave.repro import ...`` 或 ``from hydroweave.repro.manifest import ...``。
"""
from hydroweave.repro.manifest import (
    atomic_write_json,
    atomic_write_text,
    canonical_json,
    config_hash,
    file_sha256,
    git_revision,
    input_fingerprint,
    load_json,
    new_manifest,
    package_versions,
    update_manifest,
    utc_now,
)

__all__ = [
    "atomic_write_json",
    "atomic_write_text",
    "canonical_json",
    "config_hash",
    "file_sha256",
    "git_revision",
    "input_fingerprint",
    "load_json",
    "new_manifest",
    "package_versions",
    "update_manifest",
    "utc_now",
]
