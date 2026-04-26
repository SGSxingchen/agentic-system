"""管线（Pipeline）管理路由

端点:
- GET    /api/pipelines/templates     — 获取管线模板列表
- POST   /api/pipelines               — 创建管线模板
- PUT    /api/pipelines/{name}        — 更新管线模板
- DELETE /api/pipelines/{name}        — 删除管线模板
- POST   /api/pipelines/execute       — 执行管线
"""
from typing import Any, Dict

from fastapi import APIRouter

from ..schemas import (
    APIResponse,
    PipelineExecuteRequest,
    PipelineCreateRequest,
    PipelineUpdateRequest,
)
from ..dependencies import get_pipeline
from core.config import load_single_yaml, save_yaml_config

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])

_PIPELINES_YAML = "pipelines.yaml"


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
                "timeout": s.get("timeout"),
            }
            for s in steps
        ],
    }


def _load_pipelines_from_yaml() -> Dict[str, Any]:
    data = load_single_yaml(_PIPELINES_YAML)
    return data.get("pipelines", {}) or {}


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
        # fallback: 直接从 YAML 文件读取
        for name, tpl in _load_pipelines_from_yaml().items():
            templates.append(_format_template(name, tpl))

    return APIResponse(status="ok", data=templates)


# ─── CRUD 端点 ────────────────────────────────────────────


@router.post("", response_model=APIResponse)
async def create_pipeline(req: PipelineCreateRequest):
    """创建新管线模板，写入 YAML"""
    data = load_single_yaml(_PIPELINES_YAML)
    pipelines = data.get("pipelines", {}) or {}

    if req.name in pipelines:
        return APIResponse(status="error", message=f"管线 '{req.name}' 已存在")

    new_pipeline: Dict[str, Any] = {
        "description": req.description,
        "mode": req.mode,
        "steps": [s.model_dump(exclude_none=True) for s in req.steps],
    }
    pipelines[req.name] = new_pipeline
    data["pipelines"] = pipelines

    save_yaml_config(_PIPELINES_YAML, data)
    _clear_cache()

    pipeline = get_pipeline()
    if pipeline:
        pipeline.load_templates(dict(pipelines))

    return APIResponse(
        status="ok",
        message=f"管线 '{req.name}' 已创建",
        data=_format_template(req.name, new_pipeline),
    )


@router.put("/{name}", response_model=APIResponse)
async def update_pipeline(name: str, req: PipelineUpdateRequest):
    """更新管线模板，写入 YAML"""
    data = load_single_yaml(_PIPELINES_YAML)
    pipelines = data.get("pipelines", {}) or {}

    if name not in pipelines:
        return APIResponse(status="error", message=f"管线 '{name}' 不存在")

    target = pipelines[name]

    if req.description is not None:
        target["description"] = req.description
    if req.mode is not None:
        target["mode"] = req.mode
    if req.steps is not None:
        target["steps"] = [s.model_dump(exclude_none=True) for s in req.steps]

    pipelines[name] = target
    data["pipelines"] = pipelines

    save_yaml_config(_PIPELINES_YAML, data)
    _clear_cache()

    pipeline = get_pipeline()
    if pipeline:
        pipeline.load_templates(dict(pipelines))

    return APIResponse(
        status="ok",
        message=f"管线 '{name}' 已更新",
        data=_format_template(name, target),
    )


@router.delete("/{name}", response_model=APIResponse)
async def delete_pipeline(name: str):
    """删除管线模板，写入 YAML"""
    data = load_single_yaml(_PIPELINES_YAML)
    pipelines = data.get("pipelines", {}) or {}

    if name not in pipelines:
        return APIResponse(status="error", message=f"管线 '{name}' 不存在")

    del pipelines[name]
    data["pipelines"] = pipelines

    save_yaml_config(_PIPELINES_YAML, data)
    _clear_cache()

    pipeline = get_pipeline()
    if pipeline:
        pipeline.load_templates(dict(pipelines))

    return APIResponse(status="ok", message=f"管线 '{name}' 已删除")


# ─── 执行端点 ─────────────────────────────────────────────


@router.post("/execute", response_model=APIResponse)
async def execute_pipeline(req: PipelineExecuteRequest):
    """执行管线

    通过 Pipeline 同步执行完整流水线并返回结果。
    """
    requirement = req.requirement or req.input or ""
    if not requirement:
        return APIResponse(status="error", message="缺少 requirement 或 input")

    template_name = req.template_name or req.pipeline_type
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
