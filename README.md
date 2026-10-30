# GitLab 自动交付向导

从 GitLab 项目地址开始，由 Agent 分步引导并实施自动构建、环境部署、指定虚拟机自动化测试和报告回传。

技能标识：`gitlab-delivery-guide`。这是通用接入标准，项目名称、服务器、技术栈和业务断言都从当前项目确定。

## 使用

1. 下载 [Skill 安装包](dist/gitlab-delivery-guide.zip)。
2. 解压，将 `gitlab-delivery-guide` 文件夹放入支持 Agent Skills 的客户端技能目录，并重新加载技能。
3. 向 Agent 输入：

```text
$gitlab-delivery-guide 帮我接入这个 GitLab 项目：<项目地址>
```

已有配置可以输入“继续配置”或指定失败的流水线；也可以仅验收已有部署。Agent 会复用已确认的信息，并逐步询问当前阶段缺项。

## 工作流程

1. 调查仓库、技术栈、构建和测试方式。
2. 确定部署分支、环境、发布方式与验收范围。
3. 接入构建/部署 Runner 和指定虚拟机的测试 Runner。
4. 检查网络、工具链、桌面会话、浏览器及测试框架。
5. 适配项目并生成 CI、部署、健康检查与测试实现。
6. 执行构建、产物校验、备份、部署、虚拟机测试与报告回传。
7. 核对真实版本、节点、测试及清理结果，保存接续记录。

Runner 是替 GitLab 实际执行构建、部署或测试任务的工作进程。日常流水线由 GitLab CI 和 Runner 执行；Agent 负责首次接入、维护、排错和核验。

## 仓库内容

| 路径 | 用途 |
| --- | --- |
| [SKILL.md](SKILL.md) | 技能入口、引导原则和完成标准 |
| [references/](references/) | 分步流程、环境检查、流水线与报告约定 |
| [assets/](assets/) | 项目配置与接续记录模板 |
| [scripts/gitlab_probe.py](scripts/gitlab_probe.py) | 只读解析 GitLab 地址并调查实例与项目 |
| [scripts/check_result.py](scripts/check_result.py) | 检查部署和验收报告的字段及版本一致性 |
| [agents/openai.yaml](agents/openai.yaml) | 客户端显示信息 |
| [dist/gitlab-delivery-guide.zip](dist/gitlab-delivery-guide.zip) | 可分发安装包 |

## 使用条件与边界

- 需要目标 GitLab 项目、部署环境和测试节点的相应访问权限；本技能不附带账号或凭据。
- 按项目实际情况选择技术栈、部署工具和测试框架，模板不会直接启用部署。
- 凭据使用本机凭据管理或受保护的 CI 变量，避免写入仓库或聊天。
- 测试实际覆盖范围以报告为准；浏览器测试通过不能证明真实外设或原生桌面功能通过。
- `check_result.py` 只校验输入报告的一致性；完整交付还要核验真实流水线、环境和测试证据。
- 包含通用引导、配置模板和辅助脚本；具体项目的部署与测试脚本由 Agent 调查后生成或适配。

## 离线检查

使用 Python 3，在仓库根目录执行：

```sh
python -m unittest discover -s scripts -p "test_*.py"
```

当前包含 18 项离线测试。它们验证辅助脚本的行为，不替代目标项目的实际部署和虚拟机验收。
