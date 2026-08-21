# PPT Agent Studio

> 面向 PowerPoint 的智能翻译应用

PPT Agent Studio 是一个面向 PowerPoint 的状态化文档翻译 Agent。它把 `.ppt` / `.pptx` 拆成带稳定标识的翻译单元，让大模型负责语义转换，再由确定性程序完成协议校验、失败单元修复、OOXML 写回和产物发布。

当前应用专注于 PPT 翻译主流程，提供从上传、模型翻译、质量检查到可编辑文件下载的一体化体验。

## 主要功能

- 上传 `.ppt` / `.pptx`，选择源语言、目标语言、模型和页码范围。
- 生成仅译文或双语版本，并尽量保留文本框、段落和可编辑版式。
- 可选识别图片文字，并将 OCR 结果纳入 PPT 处理流程。
- 展示排队、处理中、成功、失败等任务状态，完成后下载译文。
- 使用 Qwen 或 DeepSeek Provider；真实翻译需要自行配置对应服务。

应用使用真实模型 Provider 完成翻译，并通过持久化任务账本跟踪任务状态；页面仅保留 PPT 翻译所需的功能入口。

## 快速启动

环境要求：

- Python 3.11
- Qwen 或 DeepSeek 的有效 API 配置
- LibreOffice（仅旧 `.ppt` 转换、渲染和版式验收需要）
- MySQL 8（多进程或长期运行部署建议使用；`--demo` 本地一体化模式默认使用 SQLite）

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.demo.example .env
```

编辑 `.env`，至少填写一个模型 Provider，并将 `DEMO_ACCESS_PASSWORD` 替换为不少于 12 个字符的随机强密码，然后启动：

```powershell
python run.py --demo
```

访问 `http://127.0.0.1:5000`，使用 `.env` 中配置的账号登录。`--demo` 是本地一体化运行模式，会同时启动 Web 和内嵌 Worker；它还会在未显式配置时启用 V2 编排、翻译记忆、结构/语义质量门和可编辑写回策略。显式环境变量仍可覆盖这些默认值。该模式不适合作为多进程生产部署方式。

本地一体化模式的任务状态仍写入关系数据库账本，默认数据库是系统临时目录中的 `ppt-agent-studio/demo.sqlite3`，无需先安装 MySQL。如需使用 MySQL，请按下文配置后使用常规入口 `python run.py`。

详细配置、使用流程和故障排查见 [部署与使用指南](DEMO.md)。

## 核心工作流

```text
PPT 上传
  → 不可变源文件与任务账本
  → PPTX/OOXML 解析
  → 稳定 Translation Unit
  → Qwen / DeepSeek 结构化生成
  → 结构契约与语义质量门
  → 失败单元定向修复（最多一次）
  → OOXML 精确写回与版式适配
  → 哈希校验、原子发布、下载
```

这套设计的重点不是让模型自由规划，而是为不确定的模型输出建立可靠边界：

- **状态可恢复**：Web 与 Worker 通过持久化任务账本协作，使用 lease、版本号和显式状态转换处理取消、重试与进程中断；本地一体化模式使用 SQLite，常规部署可使用 MySQL。
- **输出可校验**：版本化 JSON 协议固定 unit/segment ID、顺序和数量，并校验保留标记、精确术语及明显源语言残留。
- **修复有边界**：只把失败单元送回 Provider 修复一次；仍不合格则失败关闭，不发布半成品。
- **副作用可控**：源文件不可变，每次执行使用独立 attempt 目录；候选产物通过哈希和包完整性检查后原子晋升。
- **成本可解释**：重复单元合并、可选翻译记忆和双层并发限制减少重复调用，同时保留输入与输出顺序。
- **过程可观测**：关联 ID、脱敏结构化日志，以及阶段、Provider、质量和缓存指标帮助定位失败位置。

底层实现说明见 [翻译架构](docs/TRANSLATION_ARCHITECTURE.md)，界面规范见 [DESIGN.md](DESIGN.md)。

## 配置概览

不要提交 `.env`。仓库只提供不含密钥的 [.env.demo.example](.env.demo.example)。

### 登录保护

```dotenv
DEMO_ACCESS_USERNAME=demo
DEMO_ACCESS_PASSWORD=
DEMO_LOGIN_MAX_ATTEMPTS=5
DEMO_LOGIN_LOCKOUT_SECONDS=300
```

`DEMO_ACCESS_USERNAME` 默认为 `demo`；示例中的密码故意留空，此时入口会拒绝登录。`DEMO_ACCESS_PASSWORD` 必须显式配置且至少 12 个字符。请使用密码管理器生成的唯一随机强密码，不要复用个人、数据库或 Provider 凭据。连续登录失败默认达到 5 次后锁定 300 秒，可通过后两个变量调整。登录会话与当前服务进程绑定，重启服务或轮换密码后需要重新登录。

应用内锁定按浏览器 Cookie/会话生效，不能替代网络层防护。如果将应用开放到公网，必须使用 TLS，并在反向代理或网关按来源 IP 配置限流，同时限制可访问来源。该轻量登录入口不应替代生产级身份认证系统。

### Qwen

```dotenv
QWEN_API_KEY=replace-with-your-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen3.7-plus
```

Qwen 通过 OpenAI-compatible 接口调用；PPTX 结构化请求使用 JSON Object 输出，并关闭思考模式以减少格式漂移。

### DeepSeek

```dotenv
DEEPSEEK_API_KEY=replace-with-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

两个 Provider 都使用公开的 OpenAI-compatible 配置。API Key 只应存在于本机 `.env` 或密钥管理服务中，不应写入源码、截图或提交记录。

### PPTX 质量门与可编辑写回

```dotenv
PPTX_SEMANTIC_QA_MODE=enforce
PPTX_XML_AUTOFIT_POLICY=editable
```

`enforce` 会在产物发布前拒绝术语、占位符或源文残留等可机检的语义问题；`editable` 会将必要的缩放固化到可编辑字体大小。需要回滚到旧的 PowerPoint `normAutofit` 行为时，可将后者改为 `legacy_norm`。

### MySQL

`python run.py --demo` 会忽略下面的 `DB_*` 配置并使用隔离的本地 SQLite。若要使用 MySQL 任务账本，配置以下变量后使用 `python run.py`（不带 `--demo`）：

```dotenv
DB_TYPE=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=ppt_agent_studio
DB_USER=ppt_agent
DB_PASSWORD=replace-with-your-password
```

如需单独执行非破坏式任务表迁移：

```powershell
python migrations/add_translation_jobs.py upgrade --database-url "mysql+pymysql://ppt_agent:password@127.0.0.1/ppt_agent_studio"
```

### LibreOffice

Windows 可把 `LIBREOFFICE_PATH` 指向 LibreOffice 安装根目录，例如：

```dotenv
LIBREOFFICE_PATH=C:\Program Files\LibreOffice
```

常见系统路径可自动发现；若只处理 `.pptx` 的结构化翻译，部分路径不会主动使用 LibreOffice，但旧 `.ppt` 转换和渲染验收仍依赖它。

## 质量与指标边界

仓库中的基准用于验证具体工程性质，不代表线上业务收益：

| 证据 | 可得出的结论 | 不能宣称的结论 |
| --- | --- | --- |
| 确定性重复文本夹具：100 个相同单元，记忆关闭时 100 次调用，开启时 1 次；输出哈希和顺序一致 | 完全重复输入可被安全合并，夹具内调用数下降 99% | 真实业务成本固定下降 99% |
| 本地无网络夹具：V2 p95 约 9.09 ms，旧路径约 32.75 ms | 在该机器和夹具上，编排开销更低 | 真实模型端到端延迟提升相同比例 |
| 35 页真实场景可由 PowerPoint 打开并导出；5 个受影响页面中 4 页视觉检查通过，1 页小型组合图例存在重叠 | 包完整性、可打开性和多数目标页版式得到场景验证 | 任意 PPT 均能 100% 保持版式 |

同样，结构与语义质量门能识别机器可判定的协议、术语和残留问题，但不等于消除所有幻觉，也不等于人工翻译质量评测。

## 验证

启动装配检查：

```powershell
python run.py --demo --check
```

运行自动化测试：

```powershell
python -m pytest -q
```

运行不依赖真实 Provider 的架构基准：

```powershell
python tools/qa/benchmark_translation_architecture.py --root . --output .omo/evidence/benchmark.json
```

对你有权使用的样例 PPT 做确定性验收：

```powershell
python tools/qa/run_translation_acceptance.py --root . --provider deterministic --ppt ".\path\to\your-authorized-deck.pptx" --libreoffice "C:\Program Files\LibreOffice\program\soffice.exe" --output ".\.omo\evidence\translation-acceptance" --semantic-qa-mode enforce --autofit-policy editable
```

验收工具会复制源文件后再处理，不应修改原始 PPT 文件。

## 隐私与使用边界

- 产品名称为 **PPT Agent Studio**。
- 仅上传自制、开源许可或已获授权的 PPT，不要上传任何机密或敏感材料。
- 配置文件、页面截图和日志中不得出现 API Key、账号、内网地址或本机用户目录。
- 公网部署前设置唯一随机强密码，并在反向代理启用 TLS 与基于来源 IP 的限流；应用内会话锁定不能单独抵御分布式或更换 Cookie 的尝试。
- 调用第三方模型时，PPT 文本会发送到所配置的服务；部署者需自行确认相应的数据处理条款。
- 正式公开发布前应独立完成许可证、安全与合规审查。

## 非目标

当前项目没有把自己描述成 ReAct、自主 Planning、多 Agent 协作、RAG、向量数据库或模型微调系统。它更准确的定位是：**固定工具链、持久化状态和有界反馈修复循环组成的文档 Agent 工作流**。
