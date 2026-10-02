# Wave 1 课程知识教师审核清单

本清单用于《仓颉语言设计》课程教师审核 Wave 1 种子。它不是审核结果，也不授权 Agent 将记录标记为 `approved`。

## 当前证据

- 工具链：`cjc 1.2.0 (cjnative)`、`cjpm 1.2.0`。
- `python -m app.knowledge.seed check`：48 个概念、29 个误区、72 条边，先修图无环，77 条记录均为 `pending_review`。
- `python -m app.knowledge.seed verify-snippets`：27 个带可执行实验的误区片段全部符合预期。
- `get-timeout-cancels-task` 和 `main-exit-waits-background` 当前只有知识库来源，必须保持待审，除非教师补充可复现实验或以课程材料作出明确判断。

审核时必须同时检查记录的摘要、来源、触发证据、解释和提示阶梯。误区只有在误区本身、根概念、全部关联概念以及全部 `explains_error` 来源概念均获批准后，才能成为生产诊断证据。

## 概念清单

每一项的完整摘要和来源位于 `data/course_seed/cangjie_concepts.yaml`。

| 决定 | 稳定 ID | 标题 | 审核人/说明 |
|---|---|---|---|
| 待审 | `cj.basics.let-var-binding` | let 与 var 绑定 | |
| 待审 | `cj.basics.integer-explicit-conversion` | 整数类型的显式转换 | |
| 待审 | `cj.basics.integer-overflow-check` | 整数溢出检查 | |
| 待审 | `cj.basics.if-bool-condition` | if 条件必须为 Bool | |
| 待审 | `cj.basics.if-expression-value` | if 作为表达式取值 | |
| 待审 | `cj.basics.for-in-range` | for-in 与 Range | |
| 待审 | `cj.basics.for-in-binding-immutable` | for-in 循环变量不可变 | |
| 待审 | `cj.collections.array-bounds` | 数组下标边界 | |
| 待审 | `cj.function.declaration` | 函数声明与返回值 | |
| 待审 | `cj.function.named-parameters` | 命名参数 | |
| 待审 | `cj.function.lambda-syntax` | Lambda 表达式语法 | |
| 待审 | `cj.function.closure-capture` | 闭包捕获 | |
| 待审 | `cj.function.closure-mutable-capture-escape` | 捕获 var 的闭包不能逃逸 | |
| 待审 | `cj.type.struct-value-semantics` | struct 值语义 | |
| 待审 | `cj.type.class-reference-semantics` | class 引用语义 | |
| 待审 | `cj.type.struct-mut-function` | struct 的 mut 函数 | |
| 待审 | `cj.type.let-struct-immutability` | let 绑定的 struct 实例不可修改 | |
| 待审 | `cj.type.class-open-inheritance` | open 与类继承 | |
| 待审 | `cj.type.override-open-member` | 只有 open 成员可被 override | |
| 待审 | `cj.collections.array-shared-buffer` | Array 赋值共享元素存储 | |
| 待审 | `cj.interface.declaration` | 接口声明与实现 | |
| 待审 | `cj.interface.abstract-member-implementation` | 实现接口须实现全部抽象成员 | |
| 待审 | `cj.extend.direct-extension` | 直接扩展 | |
| 待审 | `cj.extend.interface-extension` | 接口扩展 | |
| 待审 | `cj.extend.no-stored-members` | 扩展不能添加存储成员 | |
| 待审 | `cj.generic.type-parameters` | 泛型类型参数 | |
| 待审 | `cj.generic.where-constraint` | where 约束赋予能力 | |
| 待审 | `cj.generic.where-clause-position` | where 子句的位置 | |
| 待审 | `cj.enum.declaration-constructors` | enum 声明与构造器 | |
| 待审 | `cj.enum.no-default-equality` | enum 默认不支持 == | |
| 待审 | `cj.pattern-match.match-expression` | match 表达式 | |
| 待审 | `cj.pattern-match.exhaustiveness` | match 穷举性 | |
| 待审 | `cj.pattern-match.wildcard` | 通配符兜底分支 | |
| 待审 | `cj.option.option-type` | Option<T> 类型 | |
| 待审 | `cj.option.pattern-unwrap` | 用 match 解构 Option | |
| 待审 | `cj.option.coalescing` | ?? 合并运算符 | |
| 待审 | `cj.option.get-or-throw` | getOrThrow 的失败语义 | |
| 待审 | `cj.exception.try-catch-finally` | try/catch/finally | |
| 待审 | `cj.concurrency.spawn` | spawn 创建仓颉线程 | |
| 待审 | `cj.concurrency.future-get` | Future.get 阻塞取结果 | |
| 待审 | `cj.concurrency.get-placement-parallelism` | get 的位置决定并发度 | |
| 待审 | `cj.concurrency.future-exception-propagation` | 任务异常经 get 传播 | |
| 待审 | `cj.concurrency.future-get-timeout` | get(timeout) 与任务取消 | |
| 待审 | `cj.concurrency.main-exit-background` | 主线程退出与后台任务 | |
| 待审 | `cj.package.package-declaration-path` | 包声明与目录路径 | |
| 待审 | `cj.package.import` | import 与重命名导入 | |
| 待审 | `cj.tools.cjc-single-file` | cjc 编译单文件 | |
| 待审 | `cj.tools.cjpm-project-build` | cjpm 项目构建 | |

## 误区清单

“实验”列给出当前主要复现证据；完整触发模式、解释、提示阶梯、来源和关联概念位于 `data/course_seed/cangjie_misconceptions.yaml`。

| 决定 | 稳定 ID | 标题 | 根概念 | 主要证据 | 审核人/说明 |
|---|---|---|---|---|---|
| 待审 | `cj.misconception.struct-copied-as-reference` | 把 struct 当作引用类型 | `cj.type.struct-value-semantics` | `exp:struct_vs_class_copy` | |
| 待审 | `cj.misconception.array-assignment-deep-copy` | 误以为 Array 赋值会复制全部元素 | `cj.collections.array-shared-buffer` | `exp:array_assign_shares_buffer` | |
| 待审 | `cj.misconception.let-struct-field-mutation` | 修改 let 绑定的 struct 实例字段 | `cj.type.let-struct-immutability` | `exp:struct_let_field_assign` | |
| 待审 | `cj.misconception.struct-method-missing-mut` | struct 成员函数修改字段却未声明 mut | `cj.type.struct-mut-function` | `exp:struct_method_without_mut` | |
| 待审 | `cj.misconception.class-inherit-without-open` | 继承未声明 open 的类 | `cj.type.class-open-inheritance` | `exp:class_not_open_inherit` | |
| 待审 | `cj.misconception.override-non-open-member` | 重写未声明 open 的成员函数 | `cj.type.override-open-member` | `exp:override_non_open_func` | |
| 待审 | `cj.misconception.match-non-exhaustive` | match 分支未穷举且没有兜底 | `cj.pattern-match.exhaustiveness` | `exp:match_non_exhaustive` | |
| 待审 | `cj.misconception.enum-default-equality` | 认为枚举默认支持 == | `cj.enum.no-default-equality` | `exp:enum_eq_not_default` | |
| 待审 | `cj.misconception.option-as-null` | 把 Option<T> 当作普通空值直接使用 | `cj.option.option-type` | `exp:option_arith_without_unwrap` | |
| 待审 | `cj.misconception.none-assigned-to-plain-type` | 把 None 赋给非 Option 类型 | `cj.option.option-type` | `exp:option_none_to_plain_type` | |
| 待审 | `cj.misconception.getorthrow-none-unchecked` | 未检查就对 Option 调用 getOrThrow | `cj.option.get-or-throw` | `exp:option_getOrThrow_none` | |
| 待审 | `cj.misconception.direct-extension-implies-interface` | 混淆直接扩展与接口扩展 | `cj.extend.interface-extension` | `exp:direct_extension_not_subtype` | |
| 待审 | `cj.misconception.extension-adds-stored-field` | 试图在扩展中添加成员变量 | `cj.extend.no-stored-members` | `exp:extension_no_stored_field` | |
| 待审 | `cj.misconception.interface-member-not-implemented` | 声明实现接口但遗漏抽象成员 | `cj.interface.abstract-member-implementation` | `exp:interface_member_missing` | |
| 待审 | `cj.misconception.generic-operator-without-constraint` | 对未约束的泛型参数使用运算符 | `cj.generic.where-constraint` | `exp:generic_missing_where` | |
| 待审 | `cj.misconception.where-inside-angle-brackets` | 把 where 约束写进尖括号 | `cj.generic.where-clause-position` | `exp:generic_where_inside_angle` | |
| 待审 | `cj.misconception.spawn-get-immediately-serializes` | spawn 后立即 get，把并发写成串行 | `cj.concurrency.get-placement-parallelism` | `exp:spawn_get_placement` | |
| 待审 | `cj.misconception.future-exception-ignored` | 认为子任务异常不会影响 get 的调用方 | `cj.concurrency.future-exception-propagation` | `exp:future_get_rethrows` | |
| 待审 | `cj.misconception.for-in-variable-reassign` | 修改 for-in 中的不可变循环变量 | `cj.basics.for-in-binding-immutable` | `exp:for_in_var_immutable` | |
| 待审 | `cj.misconception.let-reassign` | 对 let 绑定重新赋值 | `cj.basics.let-var-binding` | `exp:let_reassign` | |
| 待审 | `cj.misconception.if-non-bool-condition` | 用非 Bool 值作 if 条件 | `cj.basics.if-bool-condition` | `exp:if_condition_not_bool` | |
| 待审 | `cj.misconception.implicit-integer-widening` | 期望整数类型自动拓宽 | `cj.basics.integer-explicit-conversion` | `exp:implicit_int_widening` | |
| 待审 | `cj.misconception.integer-overflow-wraps` | 以为整数溢出会静默回绕 | `cj.basics.integer-overflow-check` | `exp:int_overflow_runtime` | |
| 待审 | `cj.misconception.if-without-else-as-value` | 把无 else 的 if 当作有值表达式 | `cj.basics.if-expression-value` | `exp:if_without_else_as_value` | |
| 待审 | `cj.misconception.closure-escaping-mutable-capture` | 返回捕获了 var 的闭包 | `cj.function.closure-mutable-capture-escape` | `exp:closure_var_escape` | |
| 待审 | `cj.misconception.named-param-positional-call` | 按位置传递命名参数 | `cj.function.named-parameters` | `exp:named_param_positional_call` | |
| 待审 | `cj.misconception.package-name-path-mismatch` | 包声明与目录路径不一致 | `cj.package.package-declaration-path` | `exp:cjpm_pkg_mismatch` | |
| 待审 | `cj.misconception.get-timeout-cancels-task` | 以为 get(timeout) 超时会取消任务 | `cj.concurrency.future-get-timeout` | 知识库摘要，尚无实验 | |
| 待审 | `cj.misconception.main-exit-waits-background` | 以为主线程会自动等待所有后台任务 | `cj.concurrency.main-exit-background` | 知识库摘要，尚无实验 | |

## 审核操作

1. 使用教师账号登录，身份只能来自 bearer token。
2. 调用 `GET /teacher/courses/{course_id}/concepts` 和 `GET /teacher/courses/{course_id}/misconceptions` 获取当前记录。
3. 先审核误区所依赖的全部概念，再审核误区。
4. 通过对应 `/review` 端点提交 `approved` 或 `rejected`，并填写审核说明。
5. 修改已批准内容后必须重新审核；服务会自动将其重置为 `pending_review`。
6. 重新运行种子检查和 approved-evidence 测试，记录实际审核人、时间和批准范围。

教师没有明确确认的条目必须继续保持 `pending_review`。
