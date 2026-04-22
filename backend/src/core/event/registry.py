"""扳机注册表 - 管理扳机的注册、查询与配置加载

TriggerRegistry 维护所有已注册的扳机，
支持按事件类型查询、启用/禁用，以及从字典列表或 YAML 文件批量加载。
"""
from typing import Dict, List, Optional

from .trigger import Trigger


class TriggerRegistry:
    """扳机注册表

    职责:
    - 注册 / 注销扳机
    - 按事件类型查询匹配的扳机（按优先级排序）
    - 启用 / 禁用扳机
    - 从配置字典或 YAML 文件批量加载
    """

    def __init__(self) -> None:
        self._triggers: Dict[str, Trigger] = {}

    # ─── 注册与注销 ─────────────────────────────────────

    def register(self, trigger: Trigger) -> None:
        """注册扳机（同 id 覆盖）"""
        self._triggers[trigger.id] = trigger

    def unregister(self, trigger_id: str) -> None:
        """注销扳机，不存在时忽略"""
        self._triggers.pop(trigger_id, None)

    # ─── 查询 ─────────────────────────────────────────────

    def get(self, trigger_id: str) -> Optional[Trigger]:
        """按 id 获取扳机"""
        return self._triggers.get(trigger_id)

    def get_triggers_for_event(self, event_type: str) -> List[Trigger]:
        """按事件类型获取已启用的扳机，按优先级升序排序（越小越先）"""
        matched = [
            t for t in self._triggers.values()
            if t.event_type == event_type and t.enabled
        ]
        matched.sort(key=lambda t: t.priority)
        return matched

    def list_all(self) -> List[Trigger]:
        """列出所有已注册扳机"""
        return list(self._triggers.values())

    # ─── 启用 / 禁用 ────────────────────────────────────

    def enable(self, trigger_id: str) -> bool:
        """启用扳机，成功返回 True，不存在返回 False"""
        trigger = self._triggers.get(trigger_id)
        if trigger is None:
            return False
        trigger.enabled = True
        return True

    def disable(self, trigger_id: str) -> bool:
        """禁用扳机，成功返回 True，不存在返回 False"""
        trigger = self._triggers.get(trigger_id)
        if trigger is None:
            return False
        trigger.enabled = False
        return True

    # ─── 配置加载 ────────────────────────────────────────

    def load_from_config(self, config: List[Dict]) -> int:
        """从字典列表加载扳机

        Args:
            config: 扳机配置列表，每项至少含 id, event_type, agent_name

        Returns:
            成功加载的扳机数量
        """
        loaded = 0
        for item in config:
            try:
                trigger = Trigger(
                    id=item["id"],
                    event_type=item["event_type"],
                    agent_name=item["agent_name"],
                    condition=item.get("condition"),
                    priority=item.get("priority", 0),
                    async_mode=item.get("async_mode", True),
                    enabled=item.get("enabled", True),
                )
                self.register(trigger)
                loaded += 1
            except (KeyError, TypeError):
                continue
        return loaded

    def load_from_yaml(self, path: str) -> int:
        """从 YAML 文件加载扳机配置

        YAML 文件应包含顶层 triggers 列表:
            triggers:
              - id: t1
                event_type: code_generated
                agent_name: reviewer
                ...

        Args:
            path: YAML 文件路径

        Returns:
            成功加载的扳机数量
        """
        import yaml

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            return 0

        # 支持顶层为列表或含 triggers 键的字典
        if isinstance(data, list):
            triggers_config = data
        elif isinstance(data, dict) and "triggers" in data:
            triggers_config = data["triggers"]
        else:
            return 0

        return self.load_from_config(triggers_config)

    # ─── 辅助 ─────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._triggers)

    def __contains__(self, trigger_id: str) -> bool:
        return trigger_id in self._triggers
