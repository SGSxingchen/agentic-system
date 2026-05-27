"""ServerConfig + access_password 配置加载测试 (A11 — Task 14)。"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.config import SystemConfig, load_system_config


class TestServerConfig:
    def test_server_default_no_access_password(self, tmp_path):
        """A11: 默认 ServerConfig.access_password 为空（不开启门禁）。"""

        config_path = tmp_path / "missing.yaml"
        cfg = load_system_config(config_path)
        assert cfg.server.access_password == ""
        assert cfg.server.failed_login_max_attempts == 5
        assert cfg.server.failed_login_lockout_seconds == 60

    def test_server_access_password_loaded_from_yaml(self, tmp_path):
        """A11: yaml 中 server.access_password 能被读出。"""

        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "server": {
                        "host": "127.0.0.1",
                        "port": 8001,
                        "access_password": "secret123",
                        "failed_login_max_attempts": 7,
                        "failed_login_lockout_seconds": 120,
                    }
                }
            )
        )

        cfg = load_system_config(config_path)
        assert cfg.server.access_password == "secret123"
        assert cfg.server.failed_login_max_attempts == 7
        assert cfg.server.failed_login_lockout_seconds == 120

    def test_server_config_attached_to_system_config(self):
        """A11: SystemConfig 默认带 server 子模型。"""

        cfg = SystemConfig()
        assert cfg.server is not None
        assert cfg.server.access_password == ""
        # 默认 host/port 与 system.yaml 一致
        assert cfg.server.host == "127.0.0.1"
        assert cfg.server.port == 8001
