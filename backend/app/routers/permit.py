"""外景许可接口：维护拍摄许可，覆盖提交申请、确认批准、驳回申请等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.permit import PermitService

router = APIRouter(prefix="/api/permit", tags=["外景许可"])

service = PermitService()

LIST_FIELDS = ["许可编号", "许可类型", "申请地点", "受理单位", "申请日期", "有效期至", "许可费用", "许可状态"]
STATUSES = ["待申请", "已受理", "已批准", "已驳回", "已过期"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按许可编号检索"),
    status: str | None = Query(default=None, description="待申请、已受理、已批准、已驳回、已过期"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按许可编号与状态过滤外景许可列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出外景许可清单：返回当前过滤条件下的全量数据。

    必须声明在 ``/{entry_id}`` 之前，否则 ``export`` 会被当成许可 id 解析而报 422。
    """
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "permit", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条拍摄许可明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"拍摄许可 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条拍摄许可，缺字段或编号冲突时说明原因而不是静默丢弃、覆盖历史许可。"""
    entry, missing, conflict = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if conflict:
        return ActionResult(ok=False, message=conflict)
    return ActionResult(ok=True, message="拍摄许可已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条拍摄许可执行提交申请、确认批准、驳回申请、撤回申请；不允许的动作会被拦下并说明原因。"""
    action = str((payload.values or {}).get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
