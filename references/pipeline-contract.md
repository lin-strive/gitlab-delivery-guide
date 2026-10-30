# 流水线与报告约定

依据实际仓库生成可运行实现，不预设技术栈、平台、框架或机器。

## 项目文件与参数

优先复用已有路径；缺少约定时可用 `ci/acceptance/project.json` 保存参数，`ci/acceptance/bootstrap-result.json` 保存进度与结果。其余包括实际 CI 入口/include、构建和发布脚本、备份/健康检查/恢复、测试与清理适配器、项目运行说明。

模板中的 null 和空集合表示未知，deployment.enabled 初始为 false，不直接当作可运行配置。已有格式保留并适配，不为采用 Skill 重写正常 CI。

build.applications 每项记录工作目录、工具链、命令及产物；credentials 只存变量名、用途、scope、protected/file 类型，不存值。事实来源记录 user/repository/runtime、位置和必要的时间；授权声明仍须对照真实用户请求。

部署配置中的 health_checks、测试配置中的 required_checks 是稳定检查名称的列表，实际探测命令由项目脚本实现；报告中的同名字段为检查结果数组。acceptance.node_kind 为 vm，除非用户明确选择 runner；模式为 visible-browser、headless-browser、api 或 native-desktop。不同模式不代表可跳过用户指定的 VM。

## 阶段

1. **预检**：配置、链路、节点、会话与框架关键能力；首次先不部署。必要时先用小型产物检查传递能力。
2. **构建**：按锁文件执行构建和项目测试，分别记录通过、失败、跳过；产物绑定项目 ID、应用完整提交 ID、流水线和部署 ID，附文件摘要或不可变镜像摘要。
3. **部署**：接收同一流水线产物，再验身份与摘要，备份、替换并逐项检查服务。失败停止成功路径，恢复后重新检查健康；数据库迁移可逆性独立评估。
4. **VM 验收**：核对交接文件、真实节点、测试前后的应用身份，执行实际业务断言。
5. **报告/清理**：成功和失败均回传；启动阶段未生成报告也须失败，不能留 pending。清理失败让作业与总体结果失败。

不用移动分支或 latest 产物替代已绑定产物，不在部署端悄悄重编译。清单覆盖实际文件，发现新增、删除、篡改或不允许的链接时拒绝部署。不 eval 未审阅外部输入，秘密不进入 YAML、镜像、发布包或报告。

## 全周期环境锁

只锁 deploy job 无法防止另一部署覆盖验收环境。按 GitLab 版本采用“父 trigger 持有 resource_group，等待部署/验收/报告子流水线结束”，核对等待策略及取消行为；子作业不再请求父级同一锁。

Runner 并发不能替代环境锁；项目级 resource_group 不能隔离多个项目共用环境，这时使用共同控制入口或跨项目锁。替代锁应有持有者、租期/超时、异常恢复和跨节点效力，不能只用本机临时文件。桌面会话也需串行化。

仅验收及人工重试同样协调环境，核对真实当前版本和测试前后身份，不能改写旧失败记录冒充成功。

## 业务与报告

首轮缺少业务上下文时可从明确标注的只读冒烟开始，但应验证实际业务行为，不只 HTTP 200 或窗口打开。网页通常同时检查 UI 与业务接口；API、原生桌面和设备按真实能力适配。物理动作与真实外部系统写入单独明确范围。

测试必须在用户选择的节点执行；无头/API 测试也不因方便而偷偷移到其他机器。用户明确选择无 VM 模式时另行记录。

写用例使用本次唯一标识，先查不存在再创建；修改/删除前精确查询并核对标识和 ID，finally 清理并记录遗留。不批量清空业务数据。截图遮罩敏感区域，只上传文件白名单，不上传整个未脱敏错误上下文或浏览器配置。

### 标准部署摘要

- project_id、application_sha、pipeline_id、deployment_id、environment
- status：healthy 或 failed
- 非空 health_checks：每项 name、status，通过为 passed
- 非空 artifact_digests：产物名称/URI 对应 SHA-256 或镜像摘要
- 交接另含实际入口、vm_id、hostname、范围；备份与恢复结果按事实补充

### 标准验收摘要

- 相同的五项部署身份，另含 test_script_sha
- vm_id、hostname、mode；可见模式 headed 为 true
- status：passed 或 failed；scope；非空 checks，每项 name、status
- cleanup：passed、failed 或 not-required-readonly；写用例不能使用只读清理状态

完整提交 ID按仓库对象格式记录。仅验收旧部署时应用与测试脚本提交可以不同，分别绑定来源，不互相冒充。已有格式可生成标准摘要，保留原始报告及来源。

接入记录使用 [模板](../assets/bootstrap-result.template.json)。prepared 是文件准备，validated 是必要检查通过；verified 必须实际部署和 VM 功能验收、报告、清理都成功。等待或失败时保留已完成阶段和下一步。

### 一致性辅助检查

```text
python <skill-dir>/scripts/check_result.py --project <project.json> --deployment <deployment.json> --acceptance <acceptance.json> --test-script-sha <actual-test-checkout-sha>
```

工具只检查传入的标准摘要，不证明报告真实，也不检查远端 CI 状态；Agent 仍须从实际作业和环境取得证据，不能手填 passed 让它通过。

## 收口

检查父子必要作业、实际节点、版本、断言、跳过项与清理。旧镜像恢复不代表数据库或功能恢复，未经检查不如此报告。交付触发方法、实际 CI 链接、报告、恢复入口和未覆盖范围；证据不足保留部分完成状态。
