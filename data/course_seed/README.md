# 《仓颉语言设计》课程种子

本目录是 Task 4 的概念图谱与典型误区种子，供 Task 5（确定性误区映射）、Task 6（诊断证据）和 Task 8（误区统计维度）使用。

> 数据性质：这是课程知识种子，不是试点结果。种子不含任何学生数据、准确率或教学成效数字。

## 文件

| 文件 | 内容 |
| --- | --- |
| `cangjie_concepts.yaml` | `metadata`、`concepts`（概念节点）、`edges`（概念边） |
| `cangjie_misconceptions.yaml` | `metadata`、`misconceptions`（典型误区模式） |

当前规模：48 个概念、29 个误区、72 条边（prerequisite 47、confusable_with 11、used_by 4、explains_error 10），覆盖设计规格第 6 节的九类主题。所有种子记录初始为 `pending_review`，以 `python -m app.knowledge.seed check` 的输出为准。

## 字段约定

- **稳定 ID**：`cj.<领域>.<名称>`，小写字母、数字和连字符，例如 `cj.pattern-match.exhaustiveness`、`cj.misconception.match-non-exhaustive`。ID 一经发布不得改名，只能新增或标记 rejected。
- **topic**：`basics_control_flow`、`functions_lambdas_closures`、`class_struct_semantics`、`interface_extension`、`generics_where`、`enum_match`、`option_exceptions`、`concurrency_spawn_future`、`packages_build_tools`。
- **review_status**：`draft`、`pending_review`、`approved`、`rejected`。只有误区、根概念、全部关联概念和解释该误区的概念均为 `approved`，才会通过 approved-evidence 查询进入生产诊断。
- **边类型**：
  - `prerequisite`：source 是 target 的先修概念；**必须无环**。
  - `confusable_with`：易混淆概念，可以双向。
  - `used_by`：source 出现在 target 的典型用法中，可以成环。
  - `explains_error`：source 概念（根概念以外）可以解释 target 误区；source 必须是概念，target 必须是误区。
- **source**（每条记录必填）：`kind`、`references`（`kb:` 为 cangjie-coding 知识库节点，`exp:` 为下文实验）、`toolchain_version`、`verification_status`。
- **误区必填**：`trigger_evidence`（`compiler_diagnostic`/`runtime_exception` 的 `pattern` 是去除 ANSI 颜色后工具链输出中的子串；`weak` 表示同一文本被多种误区共享，需要结合代码模式）、`root_concept_id`、`explanation`、四级 `hint_ladder`（反思问题 → 概念提示 → 步骤提示 → 完整解析）、`review_status`、`source`、`verification`。

## 审核状态说明

Wave 1 Agent C 的工具链复现仅记录在来源和审核备注中，所有种子仍为 `pending_review`，不等于课程教师审批。试点前必须由《仓颉语言设计》教师通过教师知识管理 API 复核；教师修改任意内容会再次把状态重置为 `pending_review`。

教师审核时使用 `docs/wave1-knowledge-review-checklist.md` 逐项记录决定；未明确确认的记录不得批量改为 `approved`。

仅有知识库摘要、尚未在当前工具链复现的记录一律为 `pending_review`，不会作为诊断证据。

## 工具链与知识来源

- 验证工具链：`cjc 1.2.0 (cjnative)`、`cjpm 1.2.0`，target `x86_64-w64-mingw32`。
- 知识库：cangjie-coding 技能（基线 1.0.5）。知识库摘要仅用于定位主题；工具链复现以 1.2.0 实验为准，生产审批仍由课程教师完成。
- 1.2.0 与知识库表述有差异或需补充的点：
  - 常量下标越界在 cjc 1.2.0 编译期即报 `array index is out of bounds`；只有运行期才能确定的下标越界才抛 `IndexOutOfBoundsException`。
  - `Future.get()` 重新抛出任务异常并可被捕获，同时运行时会把该线程的异常栈打印到输出，进程退出码仍为 0。
  - `let s: String = None` 的诊断文本是 `generic type should be used with type argument`，不直接提及 None。

## 复现

在 `backend` 目录：

```powershell
python -m app.knowledge.seed check            # 一致性、prerequisite 无环与覆盖统计
python -m app.knowledge.seed verify-snippets  # 在 PATH 上的 cjc/cjpm 上重跑全部带预期结果的误区片段
```

`verify-snippets` 只在宿主机编译本仓库自带的种子片段，供维护者使用。学生或教师提交的代码不得经过它，必须走隔离执行器。`spawn-get-immediately-serializes` 是计时型实验，在高负载机器上可能需要重跑。

## 实验清单（`exp:` 引用）

每个实验都是单文件 `cjc main.cj -o main.exe` 编译后运行（cjpm 实验除外）。误区实验的源码就是对应误区的 `verification.snippet`。

| 实验 | 预期 | cjc/cjpm 1.2.0 观察 |
| --- | --- | --- |
| struct_vs_class_copy | 运行成功 | 输出 `1 2` |
| array_assign_shares_buffer / array_shared_one_line | 运行成功 | 输出 `9`、`2` / `9 2` |
| match_non_exhaustive | 编译失败 | `non-exhaustive patterns` |
| match_wildcard_ok | 运行成功 | 输出 `0` |
| option_arith_without_unwrap | 编译失败 | `invalid binary operator '+' on type 'Enum-Option<Int64>' and 'Int64'` |
| option_none_to_plain_type | 编译失败 | `generic type should be used with type argument` |
| option_coalesce_and_match_ok | 运行成功 | 输出 `0`、`none` |
| option_getOrThrow_none | 运行期失败 | `NoneValueException` |
| enum_eq_not_default | 编译失败 | `invalid binary operator '==' on type 'Enum-E' and 'Enum-E'` |
| enum_eq_overload_ok | 运行成功 | 输出 `true false` |
| for_in_var_immutable | 编译失败 | `cannot assign to immutable value` |
| range_half_open | 运行成功 | 输出 `012\|0123` |
| let_reassign | 编译失败 | `cannot assign to immutable value` |
| direct_extension_not_subtype | 编译失败 | `mismatched types` |
| interface_extension_ok | 运行成功 | 输出 `4` |
| extension_no_stored_field | 编译失败 | `unexpected variable declaration in extend body` |
| interface_member_missing | 编译失败 | `missing abstract modifier, otherwise abstract function or property should be implemented` |
| generic_missing_where | 编译失败 | `invalid binary operator '>' on type 'Generics-T' and 'Generics-T'` |
| generic_where_ok | 运行成功 | 输出 `2` |
| generic_where_inside_angle | 编译失败 | `unclosed delimiter: '<'` |
| spawn_get_placement | 运行成功 | `serial_ge_550=true parallel_lt_550=true` |
| future_get_rethrows | 运行成功 | `caught boom`，并打印线程异常栈 |
| struct_let_field_assign | 编译失败 | `cannot assign to immutable value` |
| struct_method_without_mut | 编译失败 | `instance member variable 'n' cannot be modified in immutable function` |
| closure_var_escape | 编译失败 | `lambda capturing mutable variables needs to be called directly` |
| lambda_capture_let_ref_ok | 运行成功 | 输出 `2` |
| named_param_positional_call | 编译失败 | `missing argument prefix 'a:' for named parameter` |
| named_param_ok | 运行成功 | 输出 `4` |
| if_condition_not_bool | 编译失败 | `mismatched types` |
| if_without_else_as_value | 编译失败 | `mismatched types` |
| implicit_int_widening | 编译失败 | `mismatched types` |
| int_overflow_runtime | 运行期失败 | `OverflowException: add` |
| class_not_open_inherit | 编译失败 | `super class 'A' is not inheritable` |
| override_non_open_func | 编译失败 | `cannot override function 'f'` |
| array_index_oob_constant | 编译失败 | `array index is out of bounds` |
| array_index_oob_runtime | 运行期失败 | `IndexOutOfBoundsException: The length of the array is 2, but the index is 2.` |
| try_finally_ok | 运行成功 | 输出 `caught`、`finally` |
| cjpm_ok | 构建运行成功 | `cjpm init --name demo --type=executable`、`cjpm build`、`cjpm run` 输出 `hello world` |
| cjpm_pkg_mismatch | 构建失败 | `the package name in ...\src\util is wrong, the right name should be 'demo.util'` |
