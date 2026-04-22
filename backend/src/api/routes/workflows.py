"""工作流/管线管理路由

端点:
- GET    /api/workflows/templates     — 获取管线模板列表
- POST   /api/workflows               — 创建管线模板
- PUT    /api/workflows/{name}        — 更新管线模板
- DELETE /api/workflows/{name}        — 删除管线模板
- POST   /api/workflows/execute       — 执行管线
"""
from typing import Any, Dict

from fastapi import APIRouter

from ..schemas import (
    APIResponse,
    WorkflowExecuteRequest,
    WorkflowCreateRequest,
    WorkflowUpdateRequest,
)
from ..dependencies import get_pipeline
from core.config import load_single_yaml, save_yaml_config

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


# ─── 辅助函数 ─────────────────────────────────────────────


def _clear_cache():
    from ..main import clear_yaml_cache
    clear_yaml_cache()


def _format_template(name: str, tpl: Dict[str, Any]) -> Dict[str, Any]:
    """将 YAML 模板格式化为前端需要的格式"""
    steps = tpl.get("steps", [])
    return {
        "name": name,
        "description": tpl.get("description", ""),
        "mode": tpl.get("mode", "sequential"),
        "steps": [
            {
                "name": s.get("name", ""),
                "agent": s.get("agent", s.get("capability", "")),
                "capability": s.get("capability", s.get("agent", "")),
                "input": s.get("input"),
                "output_key": s.get("output_key"),
                "condition": s.get("condition"),
                "max_iterations": s.get("max_iterations", s.get("max_retries", 1)),
            }
            for s in steps
        ],
    }


# ─── 读取端点 ─────────────────────────────────────────────


@router.get("/templates", response_model=APIResponse)
async def get_templates():
    """获取管线模板列表"""
    pipeline = get_pipeline()
    templates = []

    if pipeline:
        yaml_templates = pipeline.list_templates()
        for name, tpl in yaml_templates.items():
            templates.append(_format_template(name, tpl))

    if not templates:
        # 从 YAML 文件直接读取作为 fallback
        for yaml_name in ["pipelines.yaml", "workflows.yaml"]:
            data = load_single_yaml(yaml_name)
            workflows = data.get("pipelines", data.get("workflows", {}))
            if workflows:
                for name, tpl in workflows.items():
                    templates.append(_format_template(name, tpl))
                break

    return APIResponse(status="ok", data=templates)


# ─── CRUD 端点 ────────────────────────────────────────────


@router.post("", response_model=APIResponse)
async def create_workflow(req: WorkflowCreateRequest):
    """创建新管线模板，写入 YAML"""
    data = load_single_yaml("workflows.yaml")
    workflows = data.get("pipelines", data.get("workflows", {}))

    if req.name in workflows:
        return APIResponse(status="error", message=f"管线 '{req.name}' 已存在")

    new_wf: Dict[str, Any] = {
        "description": req.description,
        "mode": req.mode,
        "steps": [s.model_dump(exclude_none=True) for s in req.steps],
    }
    workflows[req.name] = new_wf
    data["workflows"] = workflows

    save_yaml_config("workflows.yaml", data)
    _clear_cache()

    # 更新 Pipeline 运行时模板
    pipeline = get_pipeline()
    if pipeline:
        pipeline.load_templates(dict(workflows))

    return APIResponse(
        status="ok",
        message=f"管线 '{req.name}' 已创建",
        data=_format_template(req.name, new_wf),
    )


@router.put("/{name}", response_model=APIResponse)
async def update_workflow(name: str, req: WorkflowUpdateRequest):
    """更新管线模板，写入 YAML"""
    data = load_single_yaml("workflows.yaml")
    workflows = data.get("pipelines", data.get("workflows", {}))

    if name not in workflows:
        return APIResponse(status="error", message=f"管线 '{name}' 不存在")

    target = workflows[name]

    if req.description is not None:
        target["description"] = req.description
    if req.mode is not None:
        target["mode"] = req.mode
    if req.steps is not None:
        target["steps"] = [s.model_dump(exclude_none=True) for s in req.steps]

    workflows[name] = target
    data["workflows"] = workflows

    save_yaml_config("workflows.yaml", data)
    _clear_cache()

    pipeline = get_pipeline()
    if pipeline:
        pipeline.load_templates(dict(workflows))

    return APIResponse(
        status="ok",
        message=f"管线 '{name}' 已更新",
        data=_format_template(name, target),
    )


@router.delete("/{name}", response_model=APIResponse)
async def delete_workflow(name: str):
    """删除管线模板，写入 YAML"""
    data = load_single_yaml("workflows.yaml")
    workflows = data.get("pipelines", data.get("workflows", {}))

    if name not in workflows:
        return APIResponse(status="error", message=f"管线 '{name}' 不存在")

    del workflows[name]
    data["workflows"] = workflows

    save_yaml_config("workflows.yaml", data)
    _clear_cache()

    pipeline = get_pipeline()
    if pipeline:
        pipeline.load_templates(dict(workflows))

    return APIResponse(status="ok", message=f"管线 '{name}' 已删除")


# ─── 执行端点 ─────────────────────────────────────────────


@router.post("/execute", response_model=APIResponse)
async def execute_workflow(req: WorkflowExecuteRequest):
    """执行管线

    通过 Pipeline 同步执行完整流水线并返回结果。
    """
    requirement = req.requirement or req.input or ""
    if not requirement:
        return APIResponse(status="error", message="缺少 requirement 或 input")

    template_name = req.template_name or req.workflow_type
    pipeline = get_pipeline()

    if not pipeline:
        return APIResponse(status="error", message="Pipeline 未初始化")

    config = pipeline.get_template(template_name)
    if not config:
        return APIResponse(status="error", message=f"未找到管线模板: {template_name}")

    try:
        result = await pipeline.execute(
            config,
            initial_context={
                "user_requirement": requirement,
                "requirement": requirement,
                "message": requirement,
            },
        )

        return APIResponse(
            status="ok",
            message=f"管线 '{template_name}' 执行完成",
            data={
                "status": result.status.value,
                "context": result.context,
                "step_results": [
                    {
                        "step_name": sr.step_name,
                        "status": sr.status.value,
                        "output": sr.output,
                        "error": sr.error,
                        "duration_ms": sr.duration_ms,
                    }
                    for sr in result.step_results
                ],
                "duration_ms": result.duration_ms,
            },
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return APIResponse(status="error", message=f"管线执行失败: {str(e)}")
