"""外景许可业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.store import store

MODULE = "permit"
REQUIRED_FIELDS = ["许可编号", "许可类型", "申请地点"]
STATUS_ORDER = ["待申请", "已受理", "已批准", "已驳回", "已过期"]
TERMINAL_STATUSES = ["已批准", "已驳回", "已过期"]
STATUS_FIELD = "许可状态"
# 审批链路：动作 -> (允许的来源状态, 目标状态)。已批准/已驳回/已过期是终态，
# 不在任何动作的来源状态里，撤回（驳回）后不能再次批准。
ACTION_RULES = {
    "提交申请": (["待申请"], "已受理"),
    "确认批准": (["已受理"], "已批准"),
    "驳回申请": (["待申请", "已受理"], "已驳回"),
}
NEGATIVE_ACTIONS = ["驳回申请"]
EXPIRING_DAYS = 30


class PermitService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        permit_type: str | None = None,
        location: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for row in rows:
            self._sync_status_field(row)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("许可编号", ""))]
        if permit_type:
            rows = [row for row in rows if permit_type in str(row.get("许可类型", ""))]
        if location:
            rows = [row for row in rows if location in str(row.get("申请地点", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            self._sync_status_field(entry)
        return entry

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry[STATUS_FIELD] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["history"] = [self._trace("登记许可", "", STATUS_ORDER[0])]
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"拍摄许可 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于外景许可可执行范围"
        sources, target = ACTION_RULES[action]
        current = str(entry.get("status") or "")
        if current not in sources:
            return None, (
                f"拍摄许可当前为「{current}」，不能执行「{action}」；"
                f"仅「{'、'.join(sources)}」状态可执行该动作"
            )
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry[STATUS_FIELD] = target
        entry["pending"] = target not in TERMINAL_STATUSES
        if action in NEGATIVE_ACTIONS:
            # 驳回留下的异常标记只置位、不清除，历史许可的异常记录不被后续动作覆盖
            entry["abnormal"] = True
        entry.setdefault("history", []).append(self._trace(action, current, target))
        return entry, f"拍摄许可已{action}"

    def summarize(self) -> list[dict[str, Any]]:
        """页首概览卡：按当前库存实时统计，不再用前端的占位零值。"""
        rows = store.rows(MODULE)
        for row in rows:
            self._sync_status_field(row)
        today = date.today()
        deadline = today + timedelta(days=EXPIRING_DAYS)
        expiring = 0
        for row in rows:
            if row.get("status") != "已批准":
                continue
            try:
                expiry = date.fromisoformat(str(row.get("有效期至") or ""))
            except ValueError:
                # 有效期至缺失或不是日期：材料不全，无法判断临期，跳过不计
                continue
            if today <= expiry <= deadline:
                expiring += 1
        return [
            {"label": "待申请许可", "value": sum(1 for row in rows if row.get("status") == "待申请")},
            {"label": "已批准许可", "value": sum(1 for row in rows if row.get("status") == "已批准")},
            {"label": "即将过期许可", "value": expiring},
        ]

    @staticmethod
    def _sync_status_field(row: dict[str, Any]) -> None:
        """列表列「许可状态」与流转状态 status 同源；种子里的占位文本在读取时归一。"""
        status = str(row.get("status") or "")
        if status and row.get(STATUS_FIELD) != status:
            row[STATUS_FIELD] = status

    @staticmethod
    def _trace(action: str, source: str, target: str) -> dict[str, Any]:
        return {
            "action": action,
            "from": source,
            "to": target,
            "at": datetime.now().isoformat(timespec="seconds"),
        }
