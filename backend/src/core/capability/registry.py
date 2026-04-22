"""能力注册表 - 管理能力的注册、发现与执行

支持:
- register_native — 手动注册 Python 能力实例
- discover_plugins — 扫描目录自动发现并注册 CapabilityBase 子类
- execute — 执行已注册的能力
"""
import importlib
import inspect
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import CapabilityBase, CapabilitySchema

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """能力注册表

    Usage::

        registry = CapabilityRegistry()
        registry.discover_plugins(["capabilities/"])  # 自动发现
        registry.register_native(SomeCapability())    # 手动注册
        result = await registry.execute("code_parser", code="def foo(): pass")
    """

    def __init__(self) -> None:
        self._capabilities: Dict[str, CapabilityBase] = {}

    # ─── 注册 ─────────────────────────────────────────────

    def register_native(self, capability: CapabilityBase) -> None:
        """注册原生 Python 能力实例"""
        self._capabilities[capability.name] = capability

    def unregister(self, name: str) -> bool:
        """注销能力"""
        if name in self._capabilities:
            del self._capabilities[name]
            return True
        return False

    # ─── 插件自动发现 ─────────────────────────────────────

    def discover_plugins(self, plugin_dirs: List[str]) -> int:
        """扫描目录，自动发现并注册所有 CapabilityBase 子类

        约定:
        - 每个 .py 文件中可以有一个或多个 CapabilityBase 子类
        - 类必须不是抽象类（即实现了所有抽象方法）
        - 自动实例化（无参构造）并注册
        - __init__.py 和以 _ 开头的文件会被跳过

        Args:
            plugin_dirs: 要扫描的目录路径列表（相对于 sys.path 可解析的路径）

        Returns:
            成功注册的能力数量
        """
        loaded = 0
        for dir_path_str in plugin_dirs:
            dir_path = Path(dir_path_str).resolve()
            if not dir_path.is_dir():
                logger.warning("插件目录不存在: %s", dir_path)
                continue

            # 确保父目录在 sys.path 中，以便 importlib 能解析模块
            parent = str(dir_path.parent)
            if parent not in sys.path:
                sys.path.insert(0, parent)

            for py_file in sorted(dir_path.rglob("*.py")):
                if py_file.name.startswith("_"):
                    continue

                # 计算模块路径: capabilities/builtin/code_parser.py → capabilities.builtin.code_parser
                relative = py_file.relative_to(dir_path.parent)
                module_name = str(relative).replace("/", ".").replace("\\", ".")[:-3]

                try:
                    module = importlib.import_module(module_name)
                except Exception as exc:
                    logger.warning("加载模块 %s 失败: %s", module_name, exc)
                    continue

                # 查找模块中所有 CapabilityBase 的非抽象子类
                for attr_name, cls in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(cls, CapabilityBase)
                        and cls is not CapabilityBase
                        and not inspect.isabstract(cls)
                        and cls.__module__ == module.__name__  # 只注册本模块定义的类
                    ):
                        try:
                            instance = cls()
                            self.register_native(instance)
                            loaded += 1
                            logger.info(
                                "自动发现能力: %s (from %s)",
                                instance.name,
                                module_name,
                            )
                        except Exception as exc:
                            logger.warning(
                                "实例化能力 %s.%s 失败: %s",
                                module_name,
                                attr_name,
                                exc,
                            )

        logger.info("插件发现完成: 共注册 %d 个能力", loaded)
        return loaded

    # ─── 执行 ─────────────────────────────────────────────

    async def execute(self, name: str, **kwargs: Any) -> Any:
        """执行指定能力

        Args:
            name: 能力名称
            **kwargs: 能力参数

        Returns:
            能力执行结果

        Raises:
            KeyError: 能力不存在
            ValueError: 输入参数验证失败
        """
        capability = self._capabilities.get(name)
        if capability is None:
            raise KeyError(f"Capability '{name}' not registered")

        if not capability.validate_input(**kwargs):
            raise ValueError(
                f"Invalid input for capability '{name}'. "
                f"Expected: {capability.get_schema().parameters}"
            )

        return await capability.execute(**kwargs)

    # ─── 查询 ─────────────────────────────────────────────

    def get(self, name: str) -> Optional[CapabilityBase]:
        """根据名称获取能力实例"""
        return self._capabilities.get(name)

    def list_all(self) -> List[CapabilitySchema]:
        """列出所有已注册能力的 Schema"""
        return [cap.get_schema() for cap in self._capabilities.values()]

    def list_names(self) -> List[str]:
        """列出所有已注册能力的名称"""
        return list(self._capabilities.keys())

    def __len__(self) -> int:
        return len(self._capabilities)

    def __contains__(self, name: str) -> bool:
        return name in self._capabilities
