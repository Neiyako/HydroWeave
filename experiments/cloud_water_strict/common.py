"""cloud_water_strict 的配置、DBAS catalog 输入索引与运行清单共用代码。

只读消费 DBAS catalog（``volumes``/``files`` 两表）：本实验不写 catalog、
不复制原始数据；输入完整性由每文件 sha256 + catalog 逻辑指纹共同记录。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from hydroweave.repro.manifest import (
    atomic_write_json,
    atomic_write_text,
    config_hash,
    file_sha256,
    input_fingerprint,
    load_json,
    new_manifest,
    update_manifest,
    utc_now,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGES = ("dask", "flox", "matplotlib", "netCDF4", "numpy", "pandas", "xarray")
# catalog 中这些状态的文件视为不可用于计算（缺失/下线/已移除），绝不静默跳过后当完整输入。
_UNAVAILABLE_STATUS = ("removed", "missing_pending", "offline")


@dataclass(frozen=True)
class InputFile:
    """catalog 登记的一个输入 NetCDF 文件（含落盘路径与 sha256）。"""

    volume_id: str
    dataset_id: str
    rel_path: str
    path: Path
    size_bytes: int
    mtime: float
    status: str
    sha256: str

    def as_record(self) -> dict[str, Any]:
        """可写入 JSON 的输入记录（不含 Path 对象）。"""
        return {
            "volume_id": self.volume_id,
            "dataset_id": self.dataset_id,
            "rel_path": self.rel_path,
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "mtime": self.mtime,
            "status": self.status,
            "sha256": self.sha256,
        }


def load_config(path: str | Path) -> dict[str, Any]:
    """读取 YAML 配置；``_config_path`` 是运行时注记，不参与配置哈希。"""
    source = Path(path).expanduser()
    if not source.is_absolute():
        source = ROOT / source
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise TypeError(f"实验配置必须是映射: {source}")
    raw["_config_path"] = str(source)
    return raw


def path_from_config(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def run_dir(config: dict[str, Any], run_id: str, *, create: bool = True) -> Path:
    """运行目录 ``output_dir/runs/<run_id>``；不与已有 run 共享产物。"""
    target = path_from_config(config["output_dir"]) / "runs" / run_id
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def _clean(config: dict[str, Any]) -> dict[str, Any]:
    """去掉以 ``_`` 开头的运行时注记键，保证哈希只反映用户配置。"""
    return {key: value for key, value in config.items() if not key.startswith("_")}


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"DBAS catalog 不存在: {db_path}；请先在 DBAS 仓导入/扫描数据卷，"
            "或在 config 中改用正确 catalog 路径")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _resolve_volume_root(db_path: Path, row: sqlite3.Row) -> Path:
    """解析卷当前可访问根路径：绝对路径直接用，相对路径按 cwd/catalog 父目录回退。"""
    candidates: list[Path] = []
    row_keys = row.keys()
    for key in ("last_mount_path", "root_path"):
        value = row[key] if key in row_keys else None
        if not value:
            continue
        raw = Path(str(value)).expanduser()
        if raw.is_absolute():
            candidates.append(raw)
        else:
            candidates.extend((Path.cwd() / raw, db_path.parent / raw,
                               db_path.parent.parent / raw))
    checked = []
    for candidate in candidates:
        checked.append(str(candidate))
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "catalog 中卷的挂载路径都不可访问；检查数据卷是否挂载。已检查: "
        + ", ".join(checked))


def _local_override_input(config: dict[str, Any]) -> dict[str, Any] | None:
    """interim 真实文件显式覆盖（``config.input_file``），绕过 catalog。

    仅用于 RDH 交付链尚未完成时的 interim 真值核对；正式 run 必须留空走
    ``volume_id + dataset_id`` 的 catalog 路径。报告会标注 ``catalog_imported=false``。
    """
    raw = config.get("input_file")
    if not raw:
        return None
    path = path_from_config(str(raw))
    if not path.is_file():
        raise FileNotFoundError(f"config.input_file 指向的文件不存在: {path}")
    stat = path.stat()
    record = InputFile(
        volume_id="local",
        dataset_id="interim_local",
        rel_path=path.name,
        path=path,
        size_bytes=int(stat.st_size),
        mtime=float(stat.st_mtime),
        status="local_override",
        sha256=file_sha256(path),
    )
    return {
        "volume_id": "local",
        "dataset_id": "interim_local",
        "volume_root": str(path.parent),
        "volume_status": "local_override",
        "catalog_imported": False,
        "files": [record],
        "note": "interim 本地真实文件覆盖；尚未经 RDH 交付链导入 DBAS catalog，最终版待 catalog 路径",
    }


def catalog_inputs(config: dict[str, Any]) -> dict[str, Any]:
    """按 ``volume_id + dataset_id`` 从 DBAS catalog 定位 clwc/ciwc 的 NetCDF。

    返回 ``{"volume_id", "dataset_id", "volume_root", "volume_status",
    "catalog_imported", "files"}``；文件按 ``rel_path`` 排序，走的是 catalog
    的 ``files`` 表而不是目录遍历。任何登记文件缺失都直接报错，不把残缺输入
    当完整输入。若 config 给了 ``input_file``，改用该本地文件的 interim 覆盖。
    """
    override = _local_override_input(config)
    if override is not None:
        return override
    db_path = path_from_config(config["catalog"])
    volume_id = str(config["volume_id"])
    dataset_id = str(config["dataset_id"])
    db = _connect(db_path)
    try:
        volume = db.execute(
            "SELECT * FROM volumes WHERE volume_id=?", (volume_id,)).fetchone()
        if volume is None:
            raise ValueError(f"catalog 中没有卷: {volume_id}（{db_path}）")
        volume_root = _resolve_volume_root(db_path, volume)
        rows = db.execute(
            "SELECT file_id, volume_id, rel_path, file_name, size_bytes, mtime, "
            "status, dataset_id FROM files "
            "WHERE volume_id=? AND dataset_id=? "
            "AND status NOT IN (?,?,?) "
            "AND (lower(rel_path) LIKE '%.nc' OR lower(file_name) LIKE '%.nc') "
            "ORDER BY rel_path",
            (volume_id, dataset_id, *_UNAVAILABLE_STATUS),
        ).fetchall()
    finally:
        db.close()
    if not rows:
        raise ValueError(
            f"catalog 中没有 {volume_id}/{dataset_id} 的 .nc 文件；"
            "真实样本需先由 DBAS 导入并扫描（dataset_id=era5_cloud_water）")
    files: list[InputFile] = []
    missing: list[str] = []
    for row in rows:
        rel_path = str(row["rel_path"])
        path = volume_root / rel_path
        if not path.exists():
            missing.append(str(path))
            continue
        files.append(InputFile(
            volume_id=str(row["volume_id"]),
            dataset_id=str(row["dataset_id"]),
            rel_path=rel_path,
            path=path,
            size_bytes=int(row["size_bytes"] or 0),
            mtime=float(row["mtime"] or 0.0),
            status=str(row["status"] or ""),
            sha256=file_sha256(path),
        ))
    if missing:
        raise FileNotFoundError(
            "catalog 登记了但盘上不存在的输入文件（拒绝把残缺输入当完整输入）: "
            + ", ".join(missing))
    return {
        "volume_id": volume_id,
        "dataset_id": dataset_id,
        "volume_root": str(volume_root),
        "volume_status": str(volume["status"] or ""),
        "catalog_imported": True,
        "files": files,
    }


def prepare_manifest(config: dict[str, Any], run_id: str,
                     files: list[InputFile], *, force: bool = False) -> tuple[Path, dict[str, Any]]:
    """建立/复用运行清单；同 run-id 的配置或输入指纹变化直接报错。"""
    target = run_dir(config, run_id) / "manifest.json"
    fingerprint = input_fingerprint([file.as_record() for file in files])
    if target.exists() and not force:
        manifest = load_json(target)
        if manifest.get("config_hash") != config_hash(_clean(config)) or \
                manifest.get("input_fingerprint") != fingerprint:
            raise ValueError("已有运行清单与当前配置或输入不一致；换 --run-id 或显式 --force")
        return target, manifest
    manifest = new_manifest(
        project_root=ROOT,
        config=_clean(config),
        input_fingerprint_value=fingerprint,
        run_id=run_id,
        packages=DEFAULT_PACKAGES,
    )
    manifest.update({
        "experiment": "cloud_water_strict",
        "status": "running",
        "input_files": [file.as_record() for file in files],
    })
    atomic_write_json(target, manifest)
    return target, manifest


def record_artifact(manifest_path: Path, path: Path,
                    manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """登记产物 sha256+大小；返回更新后的清单（可选传入省一次读盘）。"""
    current = manifest if manifest is not None else load_json(manifest_path)
    rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    artifacts = [item for item in current.get("artifacts", []) if item.get("path") != rel]
    artifacts.append({"path": rel, "sha256": file_sha256(path),
                      "size_bytes": path.stat().st_size})
    return update_manifest(manifest_path, artifacts=artifacts)


def finalize_manifest(manifest_path: Path, status: str, **extra: Any) -> dict[str, Any]:
    """写最终状态与附加信息；``status`` 只能是清单允许的状态字符串。"""
    return update_manifest(manifest_path, status=status, finished_at=utc_now(), **extra)


__all__ = [
    "DEFAULT_PACKAGES",
    "ROOT",
    "InputFile",
    "atomic_write_json",
    "atomic_write_text",
    "catalog_inputs",
    "finalize_manifest",
    "load_config",
    "path_from_config",
    "prepare_manifest",
    "record_artifact",
    "run_dir",
    "utc_now",
]
