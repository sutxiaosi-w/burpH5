# burph5 backend

FastAPI + CLI + MCP + local HTTP proxy backend for burph5.

这个后端既可以给前端页面用，也可以给脚本和其他本地工具调用。

## Run

```powershell
cd backend
python -m pip install -e .[dev]
python -m burph5.cli serve
```

## CLI

```powershell
python -m burph5.cli replay --raw-file req.txt
python -m burph5.cli history list
python -m burph5.cli proxy start --capture-https
python -m burph5.cli proxy ca ensure
python -m burph5.cli proxy ca install
python -m burph5.cli proxy ca reset
```

## 发包

### 1. 保存原始数据包

把请求保存成当前目录下的 `req.txt`，格式就是完整原始 HTTP：

```http
GET http://localhost/vul/rce/rce_ping.php HTTP/1.1
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7
Cookie: PHPSESSID=6ji8hu74ec2hphv88d5aqf646g
Referer: http://localhost/
Upgrade-Insecure-Requests: 1
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0
sec-ch-ua: "Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "Windows"
```

### 2. 用 CLI 发包

```powershell
python -m burph5.cli replay --raw-file .\req.txt
```

如果请求行为相对路径形式，补默认协议：

```powershell
python -m burph5.cli replay --raw-file .\req.txt --default-scheme http
```

### 3. 用 HTTP API 发包

```powershell
$raw = Get-Content -Raw .\req.txt
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/api/replay `
  -ContentType 'application/json' `
  -Body (@{
    raw_request = $raw
    source = 'api'
    persist = $true
    default_scheme = 'http'
  } | ConvertTo-Json -Depth 10)
```

## MCP

```powershell
python -m burph5.mcp_server
```

常用工具：

- `replay_request`
- `parse_raw_request`
- `list_history`
- `get_history_item`
- `save_collection`
- `run_collection`

`replay_request` 示例参数：

```json
{
  "raw_request": "GET http://localhost/vul/rce/rce_ping.php HTTP/1.1\r\nAccept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7\r\nCookie: PHPSESSID=6ji8hu74ec2hphv88d5aqf646g\r\nReferer: http://localhost/\r\nUpgrade-Insecure-Requests: 1\r\nUser-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0\r\nsec-ch-ua: \"Chromium\";v=\"146\", \"Not-A.Brand\";v=\"24\", \"Microsoft Edge\";v=\"146\"\r\nsec-ch-ua-mobile: ?0\r\nsec-ch-ua-platform: \"Windows\"\r\n\r\n",
  "default_scheme": "http"
}
```

## Tests

```powershell
pytest -q
```

## 常见输出字段

- `raw_request`
- `raw_response`
- `history_id`

如果 `raw_response` 过大，建议把完整响应单独保存到目标站点的 `取证材料` 目录。
