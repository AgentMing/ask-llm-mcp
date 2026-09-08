# ask-llm-mcp

**给你的编码 agent 配一个便宜的 LLM 小弟。**

`ask-llm-mcp` 是一个极简的 [MCP](https://modelcontextprotocol.io) server，
只提供*纯粹*的文本进 / 文本出 LLM 调用。没有 agent 运行时、没有工具、没有上下文注入——
你发一段 prompt，它回一段文本。

动机很直白：你的主 agent（Claude / Codex / CodeBuddy 等）跑在很贵的模型上。
但总结文件、分类 issue、写 commit message、抽取 JSON 这些杂活，根本用不上贵模型。
把这些子任务丢给 `ask_llm`，把好模型留给真正需要推理的地方。

> [!WARNING]
> **非官方项目。** 本项目调用的是 Devin / Windsurf 客户端使用的未公开、逆向得到的
> 内部 API，与 Cognition、Windsurf、Codeium 无任何关联，也不受其支持。
> 使用时需要你自己的 Devin 订阅，并使用你自己的凭据。该协议随时可能变更或失效。
> 请自行承担风险，并确保你的使用方式符合所订阅服务的条款。

---

## 目录

- [为什么](#为什么)
- [特性](#特性)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [客户端配置](#客户端配置)
- [工具说明](#工具说明)
- [配置项](#配置项)
- [工作原理](#工作原理)
- [故障排查](#故障排查)
- [项目结构](#项目结构)
- [参与贡献](#参与贡献)
- [许可证](#许可证)

[English](README.md) | 中文 | [安装指南](INSTALL.md)

---

## 为什么

直接跑 `devin -p "<prompt>"` 会启动一个完整的 agent runner：加载系统提示词、
注册工具，然后可能花上几分钟最后决定"我不想回答这个一行的问题"。
对"给这行日志分个类"这种需求，这个形态是错的。

`ask-llm-mcp` 通过 Connect-RPC 直接调用后端的 `GetChatMessage` 接口：
一次 HTTP 请求，一段文本回复，结束。

设计的另一半是**把答案挡在你的上下文窗口之外**。`ask_llm` 不把 LLM 的文本内联返回，
而是返回一个文件路径。你的 agent 只在真的需要时才去读文件，也可以直接忽略、
`grep`、或者原样转发，不必为同样的 token 付两次钱。

## 特性

- **三个工具**：`ask_llm`、`list_models`、`list_sessions`。
- **可选模型并带价格**：每次调用都能挑便宜模型，也能运行时查询有哪些模型。
- **多轮对话**：通过 `session_id` 续接。
- **结果落盘**：`result_file`（答案）+ `log_file`（耗时、报错、prompt 预览），
  目录可配置。
- **不依赖 MCP SDK**：stdio 上的 JSON-RPC 是手写的，运行期唯一依赖是 `requests`。
- **两种 stdio 传输**：换行分隔的 JSON 与 `Content-Length` 分帧，逐消息自动识别。
- **离线测试**：protobuf / 分帧的往返测试，不需要任何凭据。

## 环境要求

| 要求 | 说明 |
| --- | --- |
| Python | 3.11 及以上（用到 `tomllib`） |
| `requests` | pip 或安装脚本会自动装上 |
| `devin` CLI | 必须**已安装并登录**——server 会读它的凭据文件 |
| Devin 订阅 | API 是用*你自己的*账号调用的 |

server 从 `~/.local/share/devin/credentials.toml`（由 `devin auth login` /
`devin login` 写入）读取 API key。密钥不会通过 MCP 参数或环境变量传递。

`list_models` 和 `list_sessions` 还会调用 `devin` CLI
（`devin models list --format json`、`devin list --format json`）；`ask_llm` 不需要。

## 快速开始

```bash
# 1. 拉代码
git clone https://github.com/agentming/ask-llm-mcp.git
cd ask-llm-mcp

# 2. 安装（创建独立 venv 并生成 console script）
./install.sh

# 3. 自检 —— 应输出三个工具的定义
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | ask-llm-mcp

# 4. 带真实凭据自检
python3 devin_api.py "用一句话打个招呼。"
```

`./install.sh --help` 查看全部选项（`--dev`、`--uninstall`、`--prefix DIR`）。

### 其它安装方式

```bash
# pipx —— 不用自己管 venv
pipx install git+https://github.com/agentming/ask-llm-mcp.git

# 普通 pip
pip install git+https://github.com/agentming/ask-llm-mcp.git

# 完全不安装，直接跑仓库里的文件
python3 /path/to/ask-llm-mcp/server.py
```

装好之后去 MCP 客户端里注册，见下节。

## 客户端配置

### Claude Code / Codex CLI

```bash
claude mcp add ask-llm -- /absolute/path/to/ask-llm-mcp
# 或者不安装，直接跑脚本：
claude mcp add ask-llm -- python3 /absolute/path/to/ask-llm-mcp/server.py
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）或
`%APPDATA%\Claude\claude_desktop_config.json`（Windows）：

```json
{
  "mcpServers": {
    "ask-llm": {
      "command": "/absolute/path/to/ask-llm-mcp",
      "env": {
        "DEVIN_MODEL": "swe-1-7"
      }
    }
  }
}
```

### CodeBuddy Code 及其它 JSON 配置型客户端

`.codebuddy/mcp.json` 或 `~/.codebuddy/mcp.json`：

```json
{
  "mcpServers": {
    "ask-llm": {
      "command": "python3",
      "args": ["/absolute/path/to/ask-llm-mcp/server.py"]
    }
  }
}
```

更多可直接复制的写法见 [`examples/`](examples/)。

> 请使用**绝对路径**。MCP 客户端启动 server 时的工作目录是不确定的。

## 工具说明

### `ask_llm`

纯粹的文本进 / 文本出调用。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `prompt` | string | *必填* | 要发送的 prompt 文本。 |
| `model` | string | `swe-1-7` | 模型 uid 或别名；续接会话时会被忽略。用 `list_models` 查询可用值。 |
| `session_id` | string | — | 续接多轮对话；省略则开启新会话。 |
| `system_prompt` | string | `You are a helpful assistant.` | 可选覆盖。 |

返回的是**结构化数据，而不是答案文本**：

```json
{
  "status": "ok",
  "session_id": "0f9c...",
  "result_file": "/home/you/.local/share/ask-llm/results/20260908_113000_ab12cd34.txt",
  "log_file": "/home/you/.local/share/ask-llm/logs/20260908_113000_ab12cd34.json",
  "error": null,
  "call_id": "20260908_113000_ab12cd34"
}
```

读 `result_file` 拿到答案。如果模型输出了推理过程，会前置并用 `---` 分隔。
失败时 `status` 为 `"error"`，`error` 带错误信息，`result_file` 内容为 `[ERROR] …`。

多轮示例——把返回的 `session_id` 再传回去即可：

```
第一轮：ask_llm(prompt="我的函数返回了 None，代码是：...")
        -> session_id = "0f9c..."
第二轮：ask_llm(prompt="那给出修复方案。", session_id="0f9c...")
```

### `list_models`

列出模型族，含每 1M token 的价格、上下文窗口和成本档位。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `query` | string | 大小写不敏感的过滤，匹配模型族名、uid、标签或成本档位（如 `swe`、`cheap`、`opus`）。 |

```
## SWE (aliases: swe)
  swe-1-7  —  SWE-1.7  [200K ctx, cheap, $0.25/$0.03/$1.00]
```

### `list_sessions`

列出最近的 Devin 会话，用来找回 `session_id`。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | integer | `20` | 最多返回多少条。 |
| `workdir` | string | `all` | 按工作目录过滤；`all` 或 `""` 表示不过滤。 |

## 配置项

全部通过环境变量配置（写在 MCP 客户端的 `env` 里）。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DEVIN_MODEL` | `swe-1-7` | 未指定 `model` 时使用的默认模型。 |
| `DEVIN_TIMEOUT` | `300` | 等待 API 响应的秒数。 |
| `ASK_LLM_DATA_DIR` | `~/.local/share/ask-llm` | `results/` 与 `logs/` 的写入位置。 |

结果文件不会自动清理，`$ASK_LLM_DATA_DIR/results` 长大了需要自己删。

## 工作原理

```
MCP 客户端 ──stdin(JSON-RPC)──► server.py ──► devin_api.py ──HTTPS──► server.codeium.com
                                     │                                  (Connect-RPC)
                                     └──► $ASK_LLM_DATA_DIR/{results,logs}/
```

- `devin_api.py` 手工拼装 protobuf 请求（`GetChatMessageRequest`），并封装成
  单个未压缩的 Connect-RPC 帧。响应以 gzip 分帧流式返回，其中的
  `delta_text` / `delta_thinking` 字段被拼接成最终答案。
- `server.py` 只实现了 MCP 协议里够用的部分：`initialize`、`tools/list`、
  `tools/call`。stdin 同时支持换行分隔 JSON 和 `Content-Length` 分帧。

请求里的字段号是抓包校准出来的，而不是来自公开的 schema，因此是最容易因上游
变更而失效的地方。如果调用开始报 HTTP 错误，优先查这里。

## 故障排查

| 现象 | 原因 / 处理 |
| --- | --- |
| `Credentials file not found: ~/.local/share/devin/credentials.toml` | `devin` CLI 没装或没登录过，先跑 `devin login`。 |
| `No windsurf_api_key found in credentials.toml` | 文件存在但缺 key，重新登录。 |
| `HTTP 401` / `HTTP 403` | 密钥过期或被吊销，用 `devin` CLI 重新登录。 |
| `HTTP 500: an internal error occurred` | 请求体被拒，最常见是 `model` uid 不受支持。跑 `list_models` 用准确的 uid。 |
| 结果文件是空的 | 模型没返回文本。看 `log_file` 里的 `elapsed_seconds` 和 prompt 预览。 |
| `devin models list failed` | MCP 客户端环境里 `devin` 不在 `PATH` 上，改用绝对路径或在客户端配置里补 `PATH`。 |
| 客户端里看不到工具 | 检查 `server.py` 的绝对路径，然后跑上面那条 `echo … \| python3 server.py` 自检。 |
| server 卡住 | 调大 `DEVIN_TIMEOUT`；也可能是模型本身就慢，看日志里的耗时。 |

每次调用的日志都在 `$ASK_LLM_DATA_DIR/logs/*.json`，含时间戳、模型、耗时秒数、
prompt 长度/预览以及错误信息。

## 项目结构

```
server.py       MCP JSON-RPC server 与三个工具的实现
devin_api.py    面向后端的 Connect-RPC / protobuf 客户端（不含 MCP 逻辑）
tests/          针对 wire 层工具的离线测试
examples/       各类 MCP 客户端配置片段
install.sh      独立 venv 安装脚本
```

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。简而言之：改动保持小、不要写会打真实
API 的测试、不要提交任何凭据。

## 许可证

[MIT](LICENSE) © agentming
