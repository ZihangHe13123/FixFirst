# 第十一轮公开机制用例独立只读复核

复核时间：2026-10-01T11:12:08.052414+00:00

结论：当前审阅范围内未发现阻塞问题。复核对象是未提交工作树生产改动和既有 5 个公开机制任务的保存记录；本次没有运行 FixFirst、测试或新用例，也没有使用已取消的私有独立任务。

## 原始证据与结果

| 公开任务 | 基准 | 当前保存的候选结果 | 观测与边界 |
|---|---|---|---|
| positional-only | blocked，无精确修改 | 第二轮 achieved | 同一真实失败的 python_binding；完整首步改为既有表达式的位置传参 |
| healthy | achieved | achieved，无修改步骤 | 健康通过不计修复收益 |
| own-store-method | blocked，无操作观测 | blocked，非空 instance 观测 | 没有把 fetch 猜成 read，没有执行修改 |
| regex-arity | blocked，无操作观测 | blocked，非空 python_binding 观测 | 明确缺少 string，但 no_value_preserving_recipe，没有补造字符串 |
| opaque-business-check | blocked | blocked，unsupported_exception | 泛化检查建议，没有业务值或依赖修改 |

候选初始 4 个失败任务中 3 个有 observed_operation，基准为 0。三条候选操作的 symbol_record_ref 与 symbol_statement_ref 均实际解析到同一 executed run 的 exception/failure；stage、nodeid 和 issue/environment 一致。位置专用参数记录保留调用别名 adapt、实际函数名 normalise、定义位置、参数布局、keyword 名和粗类型。未读取参数运行值作为修复输入。

位置专用参数用例的唯一执行修改是 app.py:4 的 `return adapt(value=value)` → `return adapt(value)`。原表达式、调用对象和测试保留。保存的第二轮 pytest_run 为 exit_code=0、verified_pass=true、coverage_complete=true、scope=tests:project、1 passed，随后 goal=achieved；并非只根据工具退出或建议存在推断通过。

逐文件重新计算 SHA256：冻结的 5 份公开原测试、5 份基准原测试、5 份候选原测试全部与 public-manifest.json 相同；所有其它冻结文件也相同，唯一差异为候选 positional-only/app.py 的上述修复。每个保存会话的 structured_evidence/bounded_actions 均为 false。

## 源码审阅

- observed_operations.context 只接受 issue 关联的 executed run，要求同 environment、唯一 run、唯一 exception，并将有效原记录与 legacy evidence 对齐；语句需来自同次同 stage/nodeid 的 failure 或同次输出，歧义时保留拒绝状态。
- positional_only_edit 仅接受零位置参数、唯一关键字、第一位置专用槽、其余参数均非必需，重新计算迁移后的绑定必须无错误；AST 仅允许一个直接调用和 Name/Constant 原实参。改动复用同一 AST 表达式，不插入业务值、不猜成员或别名。
- run_with_contract 先运行 derive/diagnose 的确定规则；已有非 code_defect 确定诊断或任何确定 remedy 均阻止新契约。最终从观察事实及获准契约重新推理，避免继承先前的启发式结论；P_BINDING 的精确文本只在 eligible_positional_only 状态生成。migration_advice 的具体建议也先于 binding refine。
- binding collector 从最内层实际 CALL 解析受限实参/可调用对象；展开、未知对象、有效绑定后函数体错误等保留拒绝。内置范围是经过 builtins 身份验证的静态 text signature，不把此范围写成任意扩展模块支持。
- 默认模型文件与基准源码副本字节相同；本次没有训练或模型替换。

## 解释限制

这只证明 5 个已公开机制用例及当前代码路径的局部链条。三个保守失败仍然失败；位置专用参数是公开构造用例，不能写成新增独立真实项目泛化。既有规则冲突及其它歧义分支在本次属于静态审阅，本次没有新增其产品运行。宿主回归由根任务执行，本报告不把它声称为独立重跑。

候选尚未提交；保存记录没有固定候选 SHA。本报告按下面的当前文件摘要标记静态审阅版本。若随后生产代码变化，需区分本报告覆盖的字节；既有记录只证明其保存时的执行。

## 审阅快照摘要

```json
{
  "sha256": {
    "src/fixfirst/binding_advice.py": "8c35e8b9cafd4541189de3283904d4f9707a8344351f87340223359cf1b61059",
    "src/fixfirst/reasoning.py": "c85c15c982f52d78a9ce25e6d1ad125e68d24330d40330796654d6db7e6683f5",
    "src/fixfirst/observed_operations.py": "c9740ec67579c56f1f66a2d78d317f3970e278a8f380391f4274de3d86893e55",
    "src/fixfirst/_runtime_evidence.py": "e0ab47d5aeed0550049854cc734ee9bf88fbe9ab741e30453d6c6bcde36f3019",
    "src/fixfirst/symbol_context.py": "43386b554b894ccfd0f98ea442cab2f4a85c6b1add20fac7ef78f4c629120e50",
    "src/fixfirst/evidence.py": "f9875ef137ac393c89d34331a8a67f340e0c10ea8b3399ff8c925b728432335e",
    "src/fixfirst/knowledge/rules.toml": "483001d6852a65623a4e971b758135c207a67481517817de0e94df65223c082d"
  },
  "default_model_sha256": "4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3",
  "baseline_model_sha256": "4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3",
  "default_model_equal": true,
  "baseline_results_sha256": "f3ca250d2d2f6092960b7f155177918a7194c32b3c032f37cd8cfa53e611b9de",
  "candidate_results_sha256": "7c6d545660f0a6a303650c266b759c593781e042d4806841dbefe325ceb08c5e",
  "public_manifest_sha256": "4bae46460f5dfc0ecf78bd6b9a095e4333c59fbce7946fa7fd7f58080d2cd788"
}
```
