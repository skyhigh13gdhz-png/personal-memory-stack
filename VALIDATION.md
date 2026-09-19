# 当前服务器验收记录

日期：2026-09-19  
服务器：`106.53.204.254`  
部署形态：Hindsight、Gateway、MCP、Cloudflare Tunnel 同机

## 组件状态

```text
Xray            active  127.0.0.1:10808 / 10809
Hindsight       active  127.0.0.1:8888（由防火墙限制公网）
Memory Gateway  active  127.0.0.1:8787
Memory MCP      active  127.0.0.1:8000/mcp
cloudflared     active  memory.skyhighmonica.fyi → 127.0.0.1:8000
```

## 本机链路验收

```text
Gateway Retain / Recall / Reflect  PASS
MCP Retain                         6249.2 ms
MCP Recall                          239.0 ms
MCP Reflect                       13627.5 ms
```

## 公网链路验收

```text
https://memory.skyhighmonica.fyi/mcp  HTTP 406（普通 GET 的预期协议响应）
Cloudflare → MCP Retain               8874.3 ms
Cloudflare → MCP Recall               1249.7 ms
Cloudflare → MCP Reflect             17592.6 ms
```

三项公网 MCP 工具均真实调用成功。Tunnel token 仅保存在服务器 root-only 文件和 cloudflared systemd 配置中，不进入本地编排目录。

## 本轮修改过的现有仓库

```text
memory-server-infra  de09f12 / c486ac7 / eafcb33
memory-gateway       3edc1a5 / 8845682
memory-mcp           未修改
```
