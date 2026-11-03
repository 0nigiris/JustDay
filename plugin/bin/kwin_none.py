"""Пустой MCP-сервер «kwin» для машин, где kwin-mcp не стоит (X11, Plasma 5, без прав на установку).

Без него обёртка в plugin/.mcp.json падала при каждом старте: «exec …/kwin-mcp/bin/python: not found», и
`justday doctor` показывал mcp ✘ из-за того, чего на X11 и быть не должно. Здесь сервер честно отвечает
на рукопожатие и говорит, что инструментов нет; окнами на X11 управляют `justday click/keys` (xdotool).
"""
import json
import sys

for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:   # уведомления без ответа
        continue
    if method == "initialize":
        result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2024-11-05"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "kwin-none", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": []}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}), flush=True)
