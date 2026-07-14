from __future__ import annotations

import csv
import secrets
import string
from pathlib import Path
from typing import Iterable

from src.models import (
    PARAMETER_COLUMNS,
    STANDARD_PARAMETER_DEFINITIONS,
    VLAN_COLUMN,
    ParameterGenerationTemplate,
    SampleParameterRecord,
)


def load_parameter_records(path: Path) -> list[SampleParameterRecord]:
    rows = _read_rows(path)
    if not rows:
        raise ValueError("参数表为空。")
    header = [str(value).strip() for value in rows[0]]
    if not _indices_for(header, VLAN_COLUMN):
        raise ValueError("参数表缺少必填列 VLAN。")
    records: list[SampleParameterRecord] = []
    for row_number, raw_row in enumerate(rows[1:], start=2):
        row = ["" if value is None else str(value).strip() for value in raw_row]
        if not any(row):
            continue
        vlan = _cell_for(header, row, VLAN_COLUMN)
        values = {
            definition.column: _cell_for(header, row, definition.column, definition.legacy_columns)
            for definition in STANDARD_PARAMETER_DEFINITIONS
        }
        records.append(SampleParameterRecord(vlan=vlan, values=values, source_row=row_number))
    return records


def save_parameter_records_xlsx(path: Path, records: Iterable[SampleParameterRecord]) -> None:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("导出 .xlsx 需要安装 openpyxl。") from exc
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "样机参数"
    headers = (VLAN_COLUMN, *PARAMETER_COLUMNS)
    sheet.append(headers)
    for record in records:
        sheet.append([record.vlan, *(record.values.get(column, "") for column in PARAMETER_COLUMNS)])
    sheet.freeze_panes = "A2"
    for column in sheet.columns:
        letter = column[0].column_letter
        sheet.column_dimensions[letter].width = min(max(max(len(str(cell.value or "")) for cell in column) + 2, 12), 30)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()


def generate_parameter_records(vlans: Iterable[str], template: ParameterGenerationTemplate) -> list[SampleParameterRecord]:
    suffix_length = int(template.suffix_length)
    if not 1 <= suffix_length <= 32:
        raise ValueError("随机后缀长度必须在 1 到 32 之间。")
    normalized_vlans = [str(vlan).strip() for vlan in vlans if str(vlan).strip()]
    if not normalized_vlans:
        raise ValueError("没有可生成的 VLAN。")
    if len({item.lower() for item in normalized_vlans}) != len(normalized_vlans):
        raise ValueError("已勾选通道存在重复 VLAN，无法生成参数表。")
    seen_mac: set[str] = set()
    seen_values: dict[str, set[str]] = {"SN": set(), "GPON SN": set(), "2.4G SSID": set(), "5G SSID": set()}
    records: list[SampleParameterRecord] = []
    for index, vlan in enumerate(normalized_vlans, start=2):
        values = {column: str(template.fixed_values.get(column, "")).strip() for column in PARAMETER_COLUMNS}
        values["SN"] = _unique_prefixed_value(template.sn_prefix, suffix_length, seen_values["SN"])
        values["GPON SN"] = _unique_prefixed_value(template.xpon_prefix, suffix_length, seen_values["GPON SN"])
        values["2.4G SSID"] = _unique_prefixed_value(template.ssid_24_prefix, suffix_length, seen_values["2.4G SSID"])
        values["5G SSID"] = _unique_prefixed_value(template.ssid_5_prefix, suffix_length, seen_values["5G SSID"])
        values["MAC"] = _unique_local_mac(seen_mac)
        records.append(SampleParameterRecord(vlan=vlan, values=values, source_row=index))
    return records


def _unique_prefixed_value(prefix: str, length: int, seen: set[str]) -> str:
    clean_prefix = (prefix or "").strip()
    if not clean_prefix:
        raise ValueError("SN、XPON SN 和 SSID 前缀均不能为空。")
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(1000):
        value = clean_prefix + "".join(secrets.choice(alphabet) for _ in range(length))
        if value not in seen:
            seen.add(value)
            return value
    raise RuntimeError("随机参数生成碰撞次数过多，请重新生成。")


def _unique_local_mac(seen: set[str]) -> str:
    for _ in range(1000):
        raw = bytearray(secrets.token_bytes(6))
        raw[0] = (raw[0] & 0xFE) | 0x02  # 本地管理 + 单播
        value = ":".join(f"{item:02X}" for item in raw)
        if value not in seen:
            seen.add(value)
            return value
    raise RuntimeError("随机 MAC 生成碰撞次数过多，请重新生成。")


def _read_rows(path: Path) -> list[list[object]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        try:
            import openpyxl
        except ImportError as exc:
            raise RuntimeError("读取 Excel 参数表需要安装 openpyxl。") from exc
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            return [list(row) for row in workbook.active.iter_rows(values_only=True)]
        finally:
            workbook.close()
    if suffix == ".xls":
        try:
            import xlrd
        except ImportError as exc:
            raise RuntimeError("读取 .xls 参数表需要安装 xlrd。") from exc
        workbook = xlrd.open_workbook(path)
        sheet = workbook.sheet_by_index(0)
        return [sheet.row_values(index) for index in range(sheet.nrows)]
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            return [list(row) for row in csv.reader(stream)]
    except UnicodeDecodeError:
        with path.open("r", encoding="gbk", newline="") as stream:
            return [list(row) for row in csv.reader(stream)]


def _cell_for(header: list[str], row: list[str], column: str, aliases: tuple[str, ...] = ()) -> str:
    for candidate in (column, *aliases):
        indices = _indices_for(header, candidate)
        if indices:
            index = indices[0]
            return row[index].strip() if index < len(row) else ""
    return ""


def _indices_for(header: list[str], target: str) -> list[int]:
    normalized = target.strip().casefold()
    return [index for index, value in enumerate(header) if value.strip().casefold() == normalized]
