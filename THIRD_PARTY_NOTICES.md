# 第三方组件声明 (Third-Party Notices)

本仓库 `skills/` 目录下预置的 Skills（SKILL.md）来自两个上游项目：
[anthropics/skills](https://github.com/anthropics/skills) 与
[obra/superpowers](https://github.com/obra/superpowers)。它们仅作为**能力库演示预设**
被引入，供前端「能力与扩展 → Skills」浏览与装配。Skills 只作为参考指导注入运行时上下文，
不授予新工具权限、不执行代码。

每个 SKILL.md 保留其原始 YAML frontmatter（含 `name` / `description` / `license`）。
若需查看完整许可证条款，请参阅各 skill 在上游仓库中的 `LICENSE.txt`。

## 预置清单

| Skill | 来源 URL | 许可 | 说明 |
|-------|----------|------|------|
| `pdf` | https://github.com/anthropics/skills/blob/main/skills/pdf/SKILL.md | **Proprietary（源代码可见，非开源）** | frontmatter 标注 `license: Proprietary. LICENSE.txt has complete terms`。仅作演示预设，使用需遵循上游许可。 |
| `docx` | https://github.com/anthropics/skills/blob/main/skills/docx/SKILL.md | **Proprietary（源代码可见，非开源）** | frontmatter 标注 `license: Proprietary. LICENSE.txt has complete terms`。仅作演示预设，使用需遵循上游许可。 |
| `mcp-builder` | https://github.com/anthropics/skills/blob/main/skills/mcp-builder/SKILL.md | **Apache-2.0** | 上游 `skills/mcp-builder/LICENSE.txt` 为 Apache License 2.0。 |
| `webapp-testing` | https://github.com/anthropics/skills/blob/main/skills/webapp-testing/SKILL.md | **Apache-2.0** | 上游 `skills/webapp-testing/LICENSE.txt` 为 Apache License 2.0。 |
| `skill-creator` | https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md | **Apache-2.0** | anthropics/skills 示例技能。 |
| `frontend-design` | https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md | **Apache-2.0** | anthropics/skills 示例技能。 |
| `test-driven-development` | https://github.com/obra/superpowers/blob/main/skills/test-driven-development/SKILL.md | **MIT** | obra/superpowers，© 2025 Jesse Vincent。工程纪律类指导。 |
| `systematic-debugging` | https://github.com/obra/superpowers/blob/main/skills/systematic-debugging/SKILL.md | **MIT** | obra/superpowers，© 2025 Jesse Vincent。 |
| `writing-plans` | https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md | **MIT** | obra/superpowers，© 2025 Jesse Vincent。 |
| `requesting-code-review` | https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/SKILL.md | **MIT** | obra/superpowers，© 2025 Jesse Vincent。 |
| `receiving-code-review` | https://github.com/obra/superpowers/blob/main/skills/receiving-code-review/SKILL.md | **MIT** | obra/superpowers，© 2025 Jesse Vincent。 |
| `verification-before-completion` | https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md | **MIT** | obra/superpowers，© 2025 Jesse Vincent。 |

## 原始 SKILL.md 原文链接（raw）

- pdf: https://raw.githubusercontent.com/anthropics/skills/main/skills/pdf/SKILL.md
- docx: https://raw.githubusercontent.com/anthropics/skills/main/skills/docx/SKILL.md
- mcp-builder: https://raw.githubusercontent.com/anthropics/skills/main/skills/mcp-builder/SKILL.md
- webapp-testing: https://raw.githubusercontent.com/anthropics/skills/main/skills/webapp-testing/SKILL.md

> 注意：`pdf` 与 `docx` 为**源代码可见但非开源**（Proprietary）内容，仅作毕设系统的能力库
> 演示预设保留 attribution；如需在其它场景使用，请先确认上游许可证条款。
> `mcp-builder` / `webapp-testing` / `skill-creator` / `frontend-design` 为 Apache-2.0；
> superpowers 来源的 6 个工程纪律 skill 为 MIT（© 2025 Jesse Vincent），均可在遵循对应许可前提下使用。
