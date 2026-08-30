# 翻译架构设计与运维说明

## 1. 设计边界

本次优化保持以下产品契约不变：

- 不删除或重命名现有 HTTP 路由、响应字段、任务 ID、下载文件名和鉴权规则。
- PPT 继续支持选页、`translation_only`、`paragraph_up`、`paragraph_down`、OCR、词库和停翻词。
- PDF 继续输出双语 DOCX，不把本次架构改造扩展为 PDF 原位写回。
- UI 当前公开的模型仍为 Qwen 和 DeepSeek；不新增模型选项，也不做静默跨模型降级。
- 保留旧执行路径作为回滚能力，不引入 Celery、RQ 或其他消息代理。

## 2. 运行时架构

```text
Browser / API
      |
      v
Web role: app.py or run_async.py
      |
      +-- validate request / persist source / create translation_jobs row
      |
      v
MySQL translation_jobs ledger
      |
      v
Worker role: run_worker.py
      |
      +-- claim lease -> execute -> verify -> atomically promote artifact
      |
      +-- PPT XML pipeline / PDF document pipeline / annotation adapter
      |
      v
Download and existing history views
```

`create_app()` 只负责配置、扩展和蓝图装配，不启动任务线程、数据库监控或清理调度。运行资源由 `app/runtime.py` 按角色显式启动和逆序停止：

| 入口 | 角色 | 用途 |
| --- | --- | --- |
| `python run.py` | `all` | 开发环境，一个命令组合 Web 和内嵌 Worker |
| `python app.py` | `web` | WSGI Web，不执行后台任务 |
| `python run_async.py` | `web` | Uvicorn/Hypercorn Web，不执行后台任务 |
| `python run_worker.py` | `worker` | 生产 Worker、监控和调度资源 |

所有入口的 `--check` 只验证依赖、配置和角色装配，不监听端口，也不启动后台资源。

## 3. 持久化任务与产物

`translation_jobs` 是新增的非破坏式任务账本，覆盖 PPT 翻译、PDF 翻译和 PDF 注释。任务状态为：

```text
queued -> running -> succeeded
                  -> failed
                  -> interrupted
queued/running -> canceled
```

Worker 使用版本号和租约进行原子领取，旧 Worker 不能用过期版本覆盖新状态。原有接口需要的 `waiting`、`processing`、`completed` 等字段由统一投影器生成，因此外部响应契约不变。

产物规则：

1. 上传源文件复制到任务私有位置并记录 SHA-256，后续尝试不改源文件。
2. 每次执行写入独立 attempt 目录。
3. 只有校验完成的 attempt 才通过原子替换发布为最终产物。
4. 重复投递、Worker 崩溃或发布后的重复恢复不会重复覆盖有效产物，也不会重复登记 PDF 历史。
5. 损坏或哈希不匹配的 attempt 不可晋升。

自动恢复由 `TRANSLATION_AUTO_RECOVER` 控制，代码默认关闭。关闭时仍会把失联任务明确投影为 `interrupted`，避免永久显示处理中。

## 4. 翻译执行层

### 4.1 Provider Adapter

`app/translation/providers.py` 将 Qwen 和 DeepSeek 封装为同一请求/响应协议，支持纯文本与结构化输出。Provider 错误具有稳定错误类型，日志会脱敏，选择 DeepSeek 失败时不会再调用 Qwen。

PDF 的 `model` 参数现在沿请求、任务、解析/OCR、文档生成和 Provider 全链路传递。PPT 结构化 XML 翻译也通过同一 Provider 注册表调用。

### 4.2 Translation Unit

PPT 文本框和 PDF 文本块在调用模型前转换为稳定的 `TranslationUnit`，包含：

- 文档类型与稳定 ID；
- 源/目标语言和源文本；
- 页码、邻接上下文与布局约束；
- 占位符、受保护术语和词库约束。

该模型只统一文本级翻译协议，不替换现有 PPT XML 或 PDF/DOCX 文档模型，避免一次性重写整个格式引擎。

### 4.3 质量策略

| 模式 | 行为 |
| --- | --- |
| `off` | 保持旧行为，不启用结构质量判定 |
| `observe` | 记录缺失 ID、重复 ID、空译文、占位符、术语、目标文字和长度问题；返回内容不因检查而改变 |
| `enforce` | 只对无效单元重试一次，保留有效兄弟单元；第二次仍无效时进入原有降级结果，不进行第三次调用 |

无效结果不会写入翻译记忆。PPT 观察模式保持 Provider 原始结构化响应字节不变。

PPTX 结构化链路另有独立的 `PPTX_SEMANTIC_QA_MODE`。默认 `enforce`：英译中结果若仍包含源文中的高置信英文短语，或不满足精确词库映射，系统仍只定向修复失败单元一次，已通过的同批单元不会重译。若修复响应仍只有软质量问题、修复响应结构无效，或修复 Provider 最终超时/不可用，则保留该单元首个结构完整候选并记录降级，不再因这类局部质量问题终止整个文件。`blank_target` 使用源文本进行确定性兜底；`missing_target_boundary_space` 依次尝试安全重组和高置信边界插空；`target_mismatch` 在精确修复仍失败时先尝试只适用于纯文本流的安全聚合重分配，无法恢复则丢弃不一致译文并保留该单元源文本。`observe` 只记录问题并保留候选译文，`off` 跳过语义检查。三种模式以及上述兜底都不会接受 JSON/schema、unit/segment ID、顺序、数量、保留标记或写回完整性错误；首次响应若出现这些硬错误，修复仍无效时继续 fail-closed。

### 4.4 翻译记忆、去重和并发

翻译记忆键使用完整 SHA-256，输入覆盖源文本、语言、Provider、模型、Prompt/词库/停翻词/质量策略版本及上下文约束。相同完整键的单元在一次任务中只调用一次 Provider，再按原顺序展开。

并发同时受 `TASK_QUEUE_MAX_CONCURRENT` 和 `TRANSLATION_PROVIDER_MAX_CONCURRENT` 限制，实际值取两者较小值。当前应用默认使用进程内记忆；`RedisTranslationMemory` Adapter 已实现，但生产共享缓存接线仍需单独配置和容量策略。

## 5. PPT 版式稳定性

XML 写回默认使用 `PPTX_XML_AUTOFIT_POLICY=editable`。被修改文本体需要缩小时，系统先原子预检全部可见 run/field；只有每个实际字号都能从本地 run、field、段落默认或 `lstStyle` 安全解析，才把计算后的字号写入相应属性，并以 `a:noAutofit` 固定当前几何。这样可安全解析的文本体不再依赖非 100% `a:normAutofit` 隐式缩放，用户在 PowerPoint 中点击“增大字号”时不会先触发自动适配反向缩小。原有 100% `a:normAutofit` 保持不变，`a:spAutoFit` 在译文已经能容纳时也会保留。

若任一继承字号无法解析，整个文本体的字号与原 AutoFit XML 原样保留，不猜测 18pt，也不允许只烘焙一部分 run；日志记录不含文本的 `pptx_editable_autofit_skipped reason=unresolved_inherited_font_size`。已有行距压缩但缺少可用几何、无法安全物化时，同样原样保留并记录 `reason=unmaterialized_line_spacing_reduction`。因此 fallback 文本体可能继续包含非 100% `a:normAutofit`，这是显式安全降级而不是“全量清零”成功；验收 JSON 会报告两类 fallback，并令对应 `*_fallback_absent` 检查失败。

紧急回滚可设置 `PPTX_XML_AUTOFIT_POLICY=legacy_norm`，恢复“每个被修改文本体一个无冲突 `a:normAutofit`”的旧行为。该回滚只作用于新任务，历史文件不重写。

LibreOffice 转换通过 `app/translation/libreoffice.py` 隔离：每个任务使用独立用户配置目录和自有端口；超时只终止本任务创建的进程；完成后验证输出并清理进程及 profile，不再全局结束 `soffice`。

确定性验收会检查：源文件哈希、幻灯片数、选中/未选中页面、HEAD/TAIL 标记、文本字形边界、相邻元素交叠、最小字号、目标区域外像素变化和进程清理。

## 6. 可观测性与健康检查

每个任务绑定关联 ID、任务类型、attempt 和 Provider 字段。指标覆盖阶段耗时、Provider 耗时/失败、质量问题、缓存命中与任务状态计数。日志不得写入 API key、token、完整源文本或完整 Provider 响应。

`GET /api/translation/health` 要求登录：

- 普通用户只看到自己的状态计数；
- 管理员看到聚合计数；
- 响应不暴露任务 ID、路径、文本或密钥。

## 7. 配置、上线与回滚

代码默认值以兼容为先：

```dotenv
TRANSLATION_ARCH_MODE=legacy
TRANSLATION_QUALITY_MODE=off
TRANSLATION_MEMORY_ENABLED=0
TRANSLATION_AUTO_RECOVER=0
TASK_QUEUE_MAX_CONCURRENT=10
TRANSLATION_PROVIDER_MAX_CONCURRENT=10
TRANSLATION_PROVIDER_TIMEOUT_SECONDS=120
PPTX_SEMANTIC_QA_MODE=enforce
PPTX_XML_AUTOFIT_POLICY=editable
```

建议上线值：

```dotenv
TRANSLATION_ARCH_MODE=v2
TRANSLATION_QUALITY_MODE=observe
TRANSLATION_MEMORY_ENABLED=1
TRANSLATION_AUTO_RECOVER=0
TRANSLATION_PROVIDER_TIMEOUT_SECONDS=120
PPTX_SEMANTIC_QA_MODE=enforce
PPTX_XML_AUTOFIT_POLICY=editable
```

上线顺序：先迁移任务表，再部署一个 Worker 和 Web，开启 `v2/observe`，对比失败率、质量问题和产物验收，最后再决定是否启用全局质量 `enforce` 或自动恢复。PPTX 语义门与自动适配已分别默认 `enforce` 和 `editable`，每个任务启动时固定一次模式，任务过程中不会因环境变更而漂移。

回滚时恢复四个全局默认开关并重启 Web/Worker。若只回滚本次 PPTX 行为，分别使用 `PPTX_SEMANTIC_QA_MODE=observe`（或 `off`）与 `PPTX_XML_AUTOFIT_POLICY=legacy_norm`，再重启 Worker。数据库表和已发布产物保留，不执行 `DROP`、`ALTER` 或历史清理。旧路径是兼容回滚路径，不再承载新能力。

## 8. 当前完成情况与后续边界

| 能力 | 状态 |
| --- | --- |
| 运行角色拆分、无副作用应用工厂 | 已实现 |
| 持久化任务账本、统一状态投影、幂等产物 | 已实现 |
| Qwen/DeepSeek Adapter 与 PDF 模型全链路选择 | 已实现 |
| Translation Unit、观察/执行质量模式、单次定向重试 | 已实现 |
| 进程内翻译记忆、去重、批处理与并发上限 | 已实现 |
| Redis 翻译记忆 Adapter | 已实现；应用级共享缓存接线未启用 |
| PPT 自动适配与 LibreOffice 任务隔离 | 已实现 |
| 关联指标、脱敏日志、鉴权健康接口 | 已实现 |
| 自动恢复 | 已实现开关和恢复机制；默认关闭，需运行数据验证后启用 |
| PDF 原位写回 | 未实现，本次明确保持 DOCX 输出 |
| Broker/多机 Worker 调度 | 未实现，本次明确不引入 |
| GPT 模型的 UI 到执行闭环 | 未实现，本次不扩展公开模型集合 |
| 旧路径删除 | 未执行；需经过独立稳定运行周期后决策 |

## 9. 验证命令

```powershell
python -m pytest -q
python run.py --check
python app.py --check
python run_async.py --check
python run_worker.py --check
python tools/qa/benchmark_translation_architecture.py --root D:\project\FCIAI2.0 --output .omo\evidence\benchmark.json
```

真实 PPT 验收命令见项目 `README.md`。该命令使用确定性 Provider 和源文件副本，不调用真实模型，也不修改用户原文件。

## 10. PPTX 结构化翻译 V2

`.pptx` 默认使用 `PPTX_XML_ENGINE=structured_v2`。旧页面协议仍可通过
`PPTX_XML_ENGINE=legacy` 显式回滚，但两条 XML 写回路径都会执行命名空间保留、
ZIP/XML/关系目标检查和原子发布。

V2 链路如下：

```text
slide XML
  -> 物理 slide + shape id + text-body ordinal + paragraph ordinal 稳定 ID
  -> paragraph source_stream（text / line_break / protected_field）
  -> provider_contract_schema_version=2 JSON
  -> 严格校验 JSON/schema、unit/segment ID、顺序、数量、目标重建和保留标记来源
  -> blank_target 与不可安全恢复的重复 target_mismatch 使用源文本确定性兜底
  -> enforce 语义门检查源语言残留和精确词库，只定向修复失败单元
  -> 修复仍有软质量问题、结构无效或 Provider 不可用时，保留首个结构完整候选并记录降级
  -> 精确写回原 a:r/a:t
  -> editable AutoFit 原子预检；可安全解析时烘焙实际字号并设置 a:noAutofit
  -> 无法安全物化时原样保留该 body 并记录无内容 fallback warning
  -> 临时 PPTX 静态审计
  -> os.replace 原子发布
```

结构校验不受 `TRANSLATION_QUALITY_MODE` 或 `PPTX_SEMANTIC_QA_MODE` 影响。Provider 首次返回无法解析的 JSON、
缺失或未知 schema 字段、错序或不匹配的 unit/segment ID，或凭空新增 `[block]` / `[块]` 及其规范化变体时，
当前批次只重试一次；修复后仍无有效结果则任务失败，不写出部分文件，也不会切换模型或进入旧提示词。首次硬错误不会被修复响应中的 `target_mismatch` 降级掩盖。
`segment_count` 会先通过二分拆批隔离到单个
翻译单元，再用包含全部预期 segment ID 的精确响应骨架重试。若第二次仍只存在数量不一致，系统仅对不含
换行、字段或其他控制流的纯文本 run 段落启用本地恢复，而且要求返回 segments 的译文串联值与聚合
`target_text` 完全一致；恢复时完整译文锚定到原文最长的 run，其余原始 segment 补为空值，然后重新执行
结构与语义校验。控制流段落、聚合译文不一致、保留标记来源不合法、目标无法重建或写回不完整等错误仍然
fail-closed。`blank_target` 是可确定恢复项：系统将该单元源文本作为目标文本写入，再重新验证结构并记录降级。`target_mismatch` 仅在首次响应和精确修复都只发生聚合 `target_text` 与合法 segment 流不一致时进入兜底；纯文本流优先把完整聚合译文安全锚定到最长 run，含换行/字段等控制流或无法通过复检时则保留源文本及原控制流。修复 Provider 失败或返回不可解析 JSON 时也保留源文本。任何不一致的 Provider 候选都不会被直接写回。

结构通过后，`PPTX_SEMANTIC_QA_MODE=enforce` 才执行源语言残留与词库检查，并对失败单元发起一次定向修复。
如果修复候选仍有软质量错误，或修复响应本身未通过结构校验，系统丢弃修复候选、保留首个结构完整候选并记录
降级；不会用无效修复响应覆盖可写回内容。`missing_target_boundary_space` 依次尝试安全重组和高置信边界插空，
只有通过边界与结构复检才采用；仍无法形成可写回结果时保留该单元源文本并告警。`observe/off` 只改变语义门，
不会关闭硬完整性约束。

正文翻译 Provider 单次请求默认使用 `TRANSLATION_PROVIDER_TIMEOUT_SECONDS=120`；可选的 PPTX 领域识别保留独立的 60 秒上限，失败时回到“通用”领域。Qwen Adapter 禁用 SDK 内部重试，避免与应用重试相乘。PPTX 初始结构化批次发生 `provider_timeout` 时，多单元批次立即二分后分别重试；单单元批次最多调用两次。如果始终没有可用的结构完整候选，任务仍保持 fail-closed，不写出部分 PPTX。连接失败保持为 `provider_unavailable`，不会触发拆批。若超时或不可用发生在已有首个结构完整候选之后的定向质量修复阶段，则保留该首选候选并记录降级，而不是让整个文件失败。拆批和降级日志只记录 job ID、单元 ID、单元数、请求字符数、超时值与原因码，不记录源文或密钥。

运行时降级由独立开关控制：

```dotenv
PPTX_XML_ENGINE=structured_v2
PPTX_XML_RUNTIME_FALLBACK=0
PPTX_SEMANTIC_QA_MODE=enforce
PPTX_XML_AUTOFIT_POLICY=editable
TRANSLATION_PROVIDER_TIMEOUT_SECONDS=120
```

只有 ZIP、XML、写入、包完整性、重复 shape ID 和不支持的文本结构等类型化运行时
错误，才可在 `PPTX_XML_RUNTIME_FALLBACK=1` 时进入 UNO 兼容路径。初始 Provider 请求未产生结构完整候选，
以及首次 JSON/schema、unit/segment、保留标记和写回等硬完整性错误始终失败关闭；重复 `target_mismatch` 按前述确定性源文本兜底处理；定向质量修复阶段的
Provider 错误只触发前述候选保留，不会转入 UNO。

Qwen 默认模型由 `QWEN_MODEL` 控制，当前为 `qwen3.7-plus`。翻译请求显式关闭思考
模式；结构化 PPTX 请求使用 OpenAI 兼容接口的 JSON Object 输出模式，并不设置
`max_tokens`，避免截断 JSON。若初始响应未通过严格协议校验，系统执行一次契约重试；
再次出现硬完整性错误后结束任务；重复 `target_mismatch` 若无法安全恢复则保留该单元源文本。系统记录关联任务 ID、契约错误码和响应长度，不记录原始响应内容，也不会进入
旧版页面翻译流程。首个结构完整候选之后的软质量修复失败则按前述规则降级保留，不属于硬契约失败。

当前范围覆盖幻灯片正文和表格单元格中已有的 `txBody`。图表、SmartArt、备注、
母版、嵌入对象等非 slide XML 正文不翻译，但其 ZIP 成员保持原样。
