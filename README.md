# Tc_Engine_Web_Mcp

LangChain Agent + TomCat Web MCP 服务。复用 `TomCat_Engine_Skills` 固定提交 `18edbfe28b81da28cc931507ac2b766d5ce6fbc0` 的工具 schema 与 `tomcat-editor` Skill，通过现有 .NET 后端驱动浏览器内真实 WASM 编辑器。

```text
网页 AI 助手 → .NET /v1/editor-sessions/{id}/agent
             → Python LangChain create_agent
             → langchain-mcp-adapters / Streamable HTTP
             → WebEditorClient → .NET 会话命令队列
             → 浏览器 HTTP 长轮询 → MessageChannel → tomcat.web.v1 → WASM
```

这是在线编辑 MVP：浏览器必须保持打开；每次提交是独立 Agent 请求，没有跨请求聊天记忆。模型只拿到工具参数和结果，不接收 Cookie、服务密钥或编辑器委托令牌。场景修改经过引擎事务，Web 任务流程在开始前、正常结束后自动保存完整项目检查点。

## 启动

需要 Python 3.11+、uv、相邻的前端和 .NET 10 后端。安装依赖：

```powershell
uv sync --locked --extra test
```

`uv.lock` 固定完整依赖。当前验证组合为 LangChain 1.2.18、langchain-mcp-adapters 0.2.2 和 MCP SDK 1.26.0；使用该 SDK 的 Streamable HTTP 协议实现，不宣称支持所有新版 MCP 扩展。

Python 服务进程配置：

```powershell
$env:TOMCAT_AGENT_SECRET = '<至少32字符的随机服务密钥，与后端一致>'
$env:TOMCAT_BACKEND_URL = 'http://127.0.0.1:5080'
$env:TOMCAT_MCP_URL = 'http://127.0.0.1:5090/mcp/'
$env:TOMCAT_MODEL = '<支持工具调用的模型名称>'
$env:TOMCAT_MODEL_API_KEY = '<模型服务密钥>'
# 使用自定义 OpenAI 兼容服务时配置；应包含服务要求的 /v1 等路径。
# $env:TOMCAT_MODEL_BASE_URL = 'https://your-provider.example/v1'
uv run --locked tomcat-web-mcp
```

模型通过 LangChain `init_chat_model(..., model_provider="openai")` 接入，支持 OpenAI 兼容的工具调用 API；其他原生 provider 需要增加相应 LangChain 集成。密钥只放环境变量，不提交到仓库。未设置 TOMCAT_MODEL 时健康接口会显示 `modelConfigured: false`，不能运行真实模型。

后端进程额外配置：

```powershell
$env:Agent__Url = 'http://127.0.0.1:5090'
$env:Agent__Secret = '<与 TOMCAT_AGENT_SECRET 相同>'
$env:ASPNETCORE_ENVIRONMENT = 'Development'
dotnet run --project TomCat.Api --no-launch-profile -- --urls http://127.0.0.1:5080
```

启动前端后，打开编辑器 → 云端登录并关联项目 → AI 助手 → 输入需求 → 执行。工具调用进度会显示在面板中。停止任务会撤销会话凭证，已完成或已开始执行的引擎修改不会自动回滚。

## 兼容矩阵

共享 Skills 定义 72 个工具，本服务通过明确的允许列表开放其中已实现的 15 个，并新增 Web 专用同步查询工具，共 16 个。上游新增工具不会自动公开；新增映射必须同时更新前端实现和契约测试：

| 工具 | Web 映射 / 限制 |
| --- | --- |
| editor_get_status | 实际引擎状态 + 已认证的项目/会话/引擎版本 |
| scene_get_tree | scene.snapshot 的分页实体列表 |
| entity_get | scene.snapshot 中的实体及组件属性 |
| component_get_schema | 当前引擎返回的 schemas |
| project_get_sync_status | 区分当前内容未同步、冲突、同步受阻、Redis 已同步待落库和当前内容已落库；保存过程中返回 SAVE_IN_PROGRESS，可稍后重新查询 |
| entity_create | 随机非零 uint64 字符串 ID，检查当前场景重名 ID，scene.transact |
| entity_delete / entity_reparent | scene.transact；引擎校验结构 |
| component_add / component_remove / component_set | scene.transact；引擎校验组件和属性 |
| editor_play / editor_pause / editor_stop | preview.control |
| history_undo / history_redo | 原生历史事务，可能包含人工编辑 |
| scene_save | 未开放：桌面已有路径保存与 Web 完整项目保存语义不同 |
| console_get_entries | 未开放：Web 尚无对应诊断接口 |
| editor_step | 未开放：尚未证明 Web Step 与桌面固定 1/60 秒契约一致 |

工具名称和输入字段复用；返回数据是 Web 结构，例如 `entity.id`、`schemas`、`scene_version`。`scene_version` 是不可解析的字符串，包含场景 Handle 与 revision；它不同于云端修订 ETag，也不是桌面协议版本。Skills 仅加载发现与编辑验证章节，并用 Web 约束覆盖桌面路径、Save As 和 Console 指令。其他 Skill 暂未加入 Agent，因为尚无相应执行能力。新版原生 `project_create`、`runtime_start`、`build_player`、存档与资产等工具没有浏览器映射，不会公开。

## 会话、授权与重试

### 任务检查点与同步状态

Web 界面在启动 Agent 前、正常响应后分别捕获完整项目，走已有条件保存接口 `/revisions` 立即落库；Redis 模式也不等待周期落库。每个检查点的修订清单包含 `aiCheckpoint: { runId, phase: "start" | "end", sceneVersion }`，历史列表显示 AI 开始/结束和任务编号，可沿用历史恢复功能创建独立副本。它是项目恢复点，不是 LangGraph 执行状态或可断点续跑的任务。

开始检查点失败或保存期间场景变化时不启动 Agent。Agent 失败、取消、页面退出时不会自动回滚，也不伪造结束检查点。正常响应后的检查点失败会明确提示“AI 已执行，但结束检查点未确认保存”；开始检查点保留。运行预览必须先停止，才能保存 authoring 场景。检查点可能包含同时发生的人工编辑，不承诺只包含 AI 修改。

`project_get_sync_status` 通过浏览器比较真实完整项目内容与最近成功同步快照，再检查云端 ETag 和 persisted。`cloudPersisted` 只描述云端版本，只有 `currentContentPersisted` 才确认当前编辑内容已落库。查询期间发生修改会返回未确认状态，不会用旧云端版本冒充当前内容。刚恢复但本次会话尚未校验同步内容时保守报告未确认。

- 浏览器用已有 Cookie 创建会话，后端核对云端项目所有权。模型不能指定用户或切换项目。
- 每次 Agent 请求创建独立会话；浏览器长轮询每次最长 20 秒，凭证只在后端与 Python 间传递。
- MCP 是内部、按编辑器会话授权的端点。它还不是可向任意外部客户端公开的 OAuth MCP 服务。
- 命令 requestId、参数和结果保留在后端内存中，每会话最多 512 条，不淘汰旧 ID 后重新执行。相同 ID 和相同参数返回旧结果；未知重试 ID 或变化参数拒绝。
- 超时返回 OUTCOME_UNKNOWN，不能推断回滚。Agent 被要求停止继续写入并说明不确定性。不能用新 ID 盲目重复操作。
- 写操作应携带读取时的 scene_version。浏览器在调用引擎前检查，引擎事务再次检查 baseRevision；冲突不自动覆盖。
- 后端重启、页面退出、点击停止或任务取消会使旧会话失效。长期闲置会话在后续注册时清理；硬有效期两小时。
- 最多 4 个会话/账号，256 个会话/后端，Python 最多 4 个并发 Agent。单请求最长 180 秒，LangChain recursion_limit=24，模型请求禁止自动重试。

## 部署边界

后端与 Python 首版均运行单副本。后端会话队列保存在内存中；持久任务、跨进程队列、无人值守引擎 Worker 尚未实现。

Python 默认仅监听 127.0.0.1。分容器部署可设置 `TOMCAT_HOST=0.0.0.0`、`PORT`，并正确配置三个服务地址；Python 和后端 `/internal/*` 应只允许私网访问，跨不可信网络必须使用 TLS。浏览器只访问同源 `/v1/*`，已有 Vite / Netlify 代理规则无需新增 WebSocket 配置。代理需允许 20 秒长轮询和最长约 190 秒的 Agent 请求；有较短固定超时的托管代理应改用独立任务 API 后再部署。

## 验证

### Railway 部署

仓库包含多阶段 `Dockerfile` 和 `railway.json`：使用 Python 3.12、锁定的 uv 与依赖，以非 root 用户运行，`/health` 为健康检查，保持单副本。发布前执行 `python -m tomcat_web_mcp.deployment_check`，验证到后端的私网 HTTP、MCP 健康和凭证拒绝行为；此检查不调用模型或写入项目。此服务不存储项目文件，不需要额外 Volume。

在现有后端所属的 Railway 项目、production 环境中创建独立服务并关联本仓库 main 分支。配置：

| 变量 | 值 |
| --- | --- |
| `PORT` | `8080` |
| `TOMCAT_HOST` | `0.0.0.0`（当前 Railway 环境支持私网 IPv4） |
| `TOMCAT_BACKEND_URL` | `http://tcenginewebbackend.railway.internal:8080` |
| `TOMCAT_MCP_URL` | `http://127.0.0.1:8080/mcp/` |
| `TOMCAT_AGENT_SECRET` | Railway 变量中生成并保存的至少 32 字符随机密钥 |

当前部署仅启用私网 MCP；不生成公网域名。内部地址为 `http://tcenginewebmcp.railway.internal:8080/mcp/`，调用仍须携带后端签发的编辑器会话 Bearer 凭证，服务密钥不能代替会话凭证。

未设置模型时 `/health` 返回 `modelConfigured: false`，MCP 工具仍然存在，但 AI Agent 请求返回明确的 503。后续启用网页 AI 助手时再配置 `TOMCAT_MODEL`、`TOMCAT_MODEL_API_KEY`、可选的 `TOMCAT_MODEL_BASE_URL`，并在后端设置 `Agent__Url=http://tcenginewebmcp.railway.internal:8080`、`Agent__Secret` 为相同服务密钥。密钥不要写入仓库。

网页 AI 请求最长 180 秒，而 Netlify 代理重写限制为 26 秒。正式启用前应先将网页 Agent 调用改为异步任务提交及状态查询，避免长请求中断。当前部署不启用模型或更改后端 Agent 配置。

```powershell
uv run --locked --extra test pytest -q
# 后端目录
dotnet build TomCat.Api -c Release
node --test tests/*.test.mjs
# 前端目录
npm run build
npm test
node tests/agent-browser.mjs
```

浏览器验收需要已构建的真实 WASM、Chrome 和本仓库 `.venv`。`tests/agent_fixture.py` 只用于测试：通过确定性模型运行真实 LangChain 图和真实 HTTP MCP，再经后端、网页和 WASM 完成组件查询、实体创建、读回、撤销和再次验证；不会调用收费模型，也不能作为真实模型能力验收。真实模型端到端验收需要另行配置模型服务。
