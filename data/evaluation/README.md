# Task 10 评测材料

这是结构与评测框架，不是实验结果。版本 `task10-v1`；当前 **164 条 security planned 案例、4 条 diagnosis draft、54 条 analytics planned 向量**，全部 synthetic，verified 为 0，真实教师标注为 0。教学实验未执行，未调用真实/付费模型，未使用真实学生资料。

YAML 文件采用 JSON 语法（JSON 是 YAML 的可解析子集），便于稳定 diff 和现有 PyYAML 验证。案例不能仅因本地编译验证改为 verified；真实教师身份和 review_record 须按协议在独立受控库核验。`cases.schema.json` 拒绝未知字段、非法 split、缺教师记录的 verified、缺审核 evidence、重复 ID 和明显身份字段；`evaluate.py` 仅实现当前 schema 使用的关键词，不是通用 JSON Schema 引擎，新增 schema 关键词须同步实现并补失败测试。身份扫描是辅助检查，不能替代人工去标识化审核。

|文件|用途|
|---|---|
|cases.schema.json|单案例结构与 verified 条件|
|security_cases.yaml|12 类非空、不同操作的计划攻击；execution_tier/test_reference 是执行线索，不是执行证明|
|diagnosis_cases.yaml|4 条合成仓颉样例：3 条编译失败、1 条完整分支控制；概念判断仍是草案|
|analytics_vectors.yaml|9 种过滤组合 × 6 场景的手算预期，不复制 Task 8 实现|
|evaluate.py|结构、唯一性、来源与 SHA-256 检查；默认输出 not_executed，不生成分数|
|recompute.py|未来真实观察的 8 项比例计数及 Wilson 区间；没有默认观察文件，不生成虚构结果|

在项目根目录用已安装依赖的 Python 运行：

```text
python data/evaluation/evaluate.py
cd backend
python -m pytest tests/security/test_evaluation_datasets.py tests/security/test_small_sample_contract.py tests/security/test_recompute.py -q
```

`recompute.py` 未来输入格式见 protocol：顶层仅 experiment_status、dataset_sha256（diagnosis 文件实际 SHA-256）、system_commit（40 位 Git hash）、observations。metric 使用 root_accuracy / autonomous_repair / recurrence / transfer_accuracy / answer_leakage / attack_success / deletion_recovery / teacher_agreement，group 使用 general_llm / compiler_only / knowbound。outcome=true 表示该指标事件发生（例如攻击成功、答案泄露是坏事件）；false 表示事件未发生；null 表示缺失。已分配准确/修复/迁移任务的缺失计入分母且不成功，未执行安全探针不计执行分母并单独计 missing，复发另输出缺失全视为复发的边界。证据需可审核，caller 的布尔值仍须由教师/隔离执行/安全观察正确评分。该工具不核实教师身份，不计算 κ 或聚类 bootstrap。

## Gate 装配

Task 8 合入后，将每个向量 facts 全部装入真实测试数据库，用 filters 调用真实 Router/SQL，并调用 `backend/tests/security/analytics_assertions.py` 的 assert_analytics。`subject_key` 必须一致映射到去标识化测试用户；`excluded_by` 只是反例元数据，装配时剥离该字段，**不得据其预过滤 facts**。每个有效过滤条件都有同课程额外第 5 名学生反例，start 之前/end 之后一秒；忽略任意该过滤条件会改变结果。重复 subject、异课程与不足 5 人 group 都要保持原始事实参与被测聚合。

浏览器投影场景在 Task 9 合入后执行 `npx playwright test --config playwright.gate.config.ts`，配置 URL 用 WAVE3_UI_URL，默认 127.0.0.1:5199，channel=msedge。7 个场景不 skip/xfail，当前仅收集与类型检查。它们使用 UI contract fixtures，不能替代真实 backend 权限与 Task 8 SQL；组合 Gate 还须实连 API 验证。

请求 E2E 独立运行 `npx playwright test`，仅启动 loopback 8197 的 synthetic/mock 服务器，停用 DATABASE_URL，使用真实 API 授权。共享 Playwright 默认配置与 Task 9 的配置存在合并冲突，Gate 应保留独立 request/browser projects，不能覆盖丢失其一。

容器检查要求显式 TASK10_RUNNER_IMAGE（本次本地 `knowbound-cj-runner-sandbox:1.2.0`），缺少时明确环境 skip。不可信代码只在 network=none、read-only、非 root、cap-drop、no-new-privileges、资源限额的隔离容器中编译/运行。现有数据库集成分别要求专用 TASK6_POSTGRES_URL / TASK7_POSTGRES_URL，不得用 SQLite 代替 PostgreSQL。

已复现的权限、登出、模型源码与删除问题见 ADR 0006；用户授权后已修复，含JWT等价编码、迟到写入与来源删除并发回归。当前验证见 `docs/experiments/task10-repair-handoff.md`；框架阶段的历史失败证据保留在 `docs/experiments/task10-handoff.md`。Task 8/9 组合、真实向量/外部缓存擦除和教学实验仍未执行，不能据此宣称 Gate 或教学成效通过。
