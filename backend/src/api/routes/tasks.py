"""任务管理路由

端点:
- POST   /api/tasks              — 提交新任务（通过 Pipeline 执行）
- GET    /api/tasks              — 列出所有任务
- GET    /api/tasks/{task_id}    — 获取任务详情
- DELETE /api/tasks/{task_id}    — 取消/删除任务
"""
import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from ..schemas import (
    APIResponse,
    TaskSubmitRequest,
    TaskResponse,
    TaskStatus,
)
from ..dependencies import get_pipeline, get_capability_registry

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# 内存任务存储
_tasks: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now().isoformat()


@router.post("", response_model=APIResponse)
async def submit_task(req: TaskSubmitRequest):
    """提交新任务

    创建任务记录，通过 Pipeline 异步执行 plan→code→review 流程。
    """
    task_id = str(uuid.uuid4())
    now = _now_iso()

    task_record = {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "requirement": req.requirement,
        "workflow": req.workflow,
        "plan": None,
        "code": None,
        "review": None,
        "output": None,
        "created_at": now,
        "updated_at": now,
    }
    _tasks[task_id] = task_record

    pipeline = get_pipeline()
    if pipeline:
        # 确定使用的管线模板
        template_name = req.workflow if req.workflow != "auto" else "code_generation_and_review"
        config = pipeline.get_template(template_name)

        if config:
            task_record["status"] = TaskStatus.PLANNING
            task_record["updated_at"] = _now_iso()
            # 异步执行管线
            asyncio.create_task(
                _run_task_pipeline(task_id, pipeline, config, req.requirement)
            )
        else:
            # 没有匹配的模板，尝试直接调用 planner
            cap_registry = get_capability_registry()
            if cap_registry and "planner" in cap_registry:
                task_record["status"] = TaskStatus.PLANNING
                task_record["updated_at"] = _now_iso()
                asyncio.create_task(
                    _run_single_agent_task(task_id, cap_registry, req.requirement)
                )
            else:
                print(f"[WARN] 无可用管线模板 '{template_name}'，任务保持 PENDING")
    else:
        print("[WARN] Pipeline 未初始化，任务保持 PENDING")

    return APIResponse(
        status="ok",
        message="任务已提交",
        data={"task_id": task_id, "status": task_record["status"].value},
    )


async def _run_task_pipeline(task_id, pipeline, config, requirement):
    """异步执行管线并更新任务状态"""
    try:
        from core.pipeline import PipelineStatus

        result = await pipeline.execute(
            config,
            initial_context={
                "user_requirement": requirement,
                "requirement": requirement,
                "message": requirement,
            },
        )

        task = _tasks.get(task_id)
        if task:
            if result.status == PipelineStatus.COMPLETED:
                task["status"] = TaskStatus.COMPLETED
                task["output"] = result.context
            else:
                task["status"] = TaskStatus.FAILED
                task["output"] = {"error": result.error}

            # 提取中间结果
            for sr in result.step_results:
                if sr.step_name == "plan" and sr.output:
                    task["plan"] = sr.output
                elif sr.step_name == "code" and sr.output:
                    task["code"] = sr.output
                elif sr.step_name == "review" and sr.output:
                    task["review"] = sr.output

            task["updated_at"] = _now_iso()

    except Exception as e:
        task = _tasks.get(task_id)
        if task:
            task["status"] = TaskStatus.FAILED
            task["output"] = {"error": str(e)}
            task["updated_at"] = _now_iso()
        print(f"[ERROR] 任务 {task_id} Pipeline 执行失败: {e}")


async def _run_single_agent_task(task_id, cap_registry, requirement):
    """直接调用 planner Agent"""
    try:
        result = await cap_registry.execute("planner", requirement=requirement)
        task = _tasks.get(task_id)
        if task:
            task["plan"] = result
            task["status"] = TaskStatus.COMPLETED
            task["output"] = result
            task["updated_at"] = _now_iso()
    except Exception as e:
        task = _tasks.get(task_id)
        if task:
            task["status"] = TaskStatus.FAILED
            task["output"] = {"error": str(e)}
            task["updated_at"] = _now_iso()


@router.get("", response_model=APIResponse)
async def list_tasks():
    """列出所有任务"""
    tasks_list = []
    for t in _tasks.values():
        tasks_list.append(
            {
                "task_id": t["task_id"],
                "status": t["status"].value if isinstance(t["status"], TaskStatus) else t["status"],
                "requirement": t["requirement"],
                "created_at": t["created_at"],
                "updated_at": t["updated_at"],
            }
        )
    return APIResponse(status="ok", data=tasks_list)


@router.get("/{task_id}", response_model=APIResponse)
async def get_task(task_id: str):
    """获取任务详情"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    task_copy = dict(task)
    if isinstance(task_copy["status"], TaskStatus):
        task_copy["status"] = task_copy["status"].value

    return APIResponse(status="ok", data=task_copy)


@router.delete("/{task_id}", response_model=APIResponse)
async def cancel_task(task_id: str):
    """取消/删除任务"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    del _tasks[task_id]
    return APIResponse(status="ok", message="任务已取消")


# ─── 内部函数 ─────────────────────────────────────────────


def update_task_status(task_id: str, status: TaskStatus, **kwargs) -> None:
    """更新任务状态（供外部调用）"""
    task = _tasks.get(task_id)
    if task:
        task["status"] = status
        task["updated_at"] = _now_iso()
        task.update(kwargs)


def get_task_store() -> dict[str, dict[str, Any]]:
    """获取任务存储"""
    return _tasks
