"""外景许可业务规则：状态流转、字段校验与筛选口径都收在这里。

审批链路（许可状态以英文键 ``status`` 为唯一事实源，列表/详情/概览都从它派生）：

    待申请 ──提交申请──▶ 已受理 ──确认批准──▶ 已批准（终态）
                          │  └──驳回申请──▶ 已驳回（终态）
                          └──撤回申请──▶ 待申请（申请方撤回，需重新提交）

    已过期（终态）：到期后由外部流程置位，不允许再审批。

历史许可沿用同一条记录，只允许按链路流转；任何动作都不会覆盖许可编号等材料字段。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "permit"
REQUIRED_FIELDS = ["许可编号", "许可类型", "申请地点"]
OPTIONAL_FIELDS = ["受理单位", "申请日期", "有效期至", "许可费用"]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
# 列表/详情对外展示的材料列；许可状态由 status 统一投影，不存自由文本。
DISPLAY_FIELDS = ["许可编号", "许可类型", "申请地点", "受理单位", "申请日期", "有效期至", "许可费用"]

STATUS_DRAFT = "待申请"
STATUS_ACCEPTED = "已受理"
STATUS_APPROVED = "已批准"
STATUS_REJECTED = "已驳回"
STATUS_EXPIRED = "已过期"
TERMINAL_STATUSES = {STATUS_APPROVED, STATUS_REJECTED, STATUS_EXPIRED}

# 动作 -> (目标状态, 允许的来源状态)；来源不匹配即视为材料状态冲突，动作不落地。
ACTION_RULES: dict[str, tuple[str, list[str]]] = {
    "提交申请": (STATUS_ACCEPTED, [STATUS_DRAFT]),
    "确认批准": (STATUS_APPROVED, [STATUS_ACCEPTED]),
    "驳回申请": (STATUS_REJECTED, [STATUS_ACCEPTED]),
    "撤回申请": (STATUS_DRAFT, [STATUS_ACCEPTED]),
}
NEGATIVE_ACTIONS = ["驳回申请"]


def _sync_flags(entry: dict[str, Any]) -> None:
    """根据状态重算看板标记：终态不再待处理，驳回属于异常；保证概览数量不丢、不虚增。"""
    status = entry.get("status")
    entry["pending"] = status not in TERMINAL_STATUSES
    entry["abnormal"] = status == STATUS_REJECTED


def _project(entry: dict[str, Any]) -> dict[str, Any]:
    """列表与详情共用同一份只读投影：许可状态始终取审批链路的 status。"""
    item: dict[str, Any] = {"id": entry.get("id")}
    for field in DISPLAY_FIELDS:
        item[field] = entry.get(field)
    item["许可状态"] = entry.get("status")
    item["status"] = entry.get("status")
    item["pending"] = entry.get("pending")
    item["abnormal"] = entry.get("abnormal")
    return item


class PermitService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("许可编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size]
        # 投影副本返回，视图层只读到统一口径，不会改写仓库里的历史材料。
        return [_project(row) for row in page_rows], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return _project(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str | None]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, None
        rows = store.rows(MODULE)
        permit_no = str(values.get("许可编号")).strip()
        # 许可编号是许可的身份；同号视为历史许可冲突，拦下并说明，而不是追加一条覆盖它。
        if any(str(row.get("许可编号", "")).strip() == permit_no for row in rows):
            return None, [], f"许可编号 {permit_no} 已存在，不能重复登记；如需调整请对历史许可执行流转动作"
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ALL_FIELDS:
            value = values.get(field)
            if value is not None and str(value).strip() != "":
                entry[field] = value
        entry["许可编号"] = permit_no
        entry["status"] = STATUS_DRAFT
        _sync_flags(entry)
        rows.append(entry)
        return entry, [], None

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"拍摄许可 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于外景许可可执行范围"
        target, allowed_from = ACTION_RULES[action]
        current = entry.get("status")
        if current not in allowed_from:
            # 材料状态冲突：明确告诉调用方当前处于什么状态、需要先回到哪一步。
            return None, f"拍摄许可当前为「{current}」，不能执行「{action}」（仅 {'、'.join(allowed_from)} 状态可执行）"
        entry["status"] = target
        _sync_flags(entry)
        return entry, f"拍摄许可已{action}"
