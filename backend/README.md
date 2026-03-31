# burph5 backend

FastAPI + CLI + MCP + local HTTP proxy backend for burph5.

这个后端既可以给前端页面用，也可以给 `qclaw`、脚本和其他 Agent 用。

## Run

```powershell
cd D:\挖洞\burph5\backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .[dev]
.\.venv\Scripts\python -m burph5.cli serve
```

## CLI

```powershell
.\.venv\Scripts\python -m burph5.cli replay --raw-file req.txt
.\.venv\Scripts\python -m burph5.cli history list
.\.venv\Scripts\python -m burph5.cli proxy start
```

## qclaw 接入

推荐顺序：

1. `qclaw` 优先用自带 `browser` 工具发现真实接口
2. 如果 `qclaw browser` 拿不到网络请求，再补 `Chrome DevTools MCP`
3. `qclaw` 把请求送到 `http://127.0.0.1:8765/api/replay`
4. 需要时再调用 `burph5.mcp_server` 或 CLI

如果要输出漏洞报告，建议保留这些字段：

- `raw_request`
- `raw_response`
- `history_id`

如果 `raw_response` 过大，建议把完整响应单独保存到目标站点的 `取证材料` 目录。
