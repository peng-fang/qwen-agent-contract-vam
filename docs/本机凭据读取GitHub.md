# 本机凭据读取 GitHub（只读）

## 背景

Trae 的 GitHub 连接器在读取本私有仓库时返回 404（见 issue #7），无法用于 PR / issue 核查。
因此统一改为：**使用本机 Windows 凭据管理器中的 HTTPS 凭据，在内存中调用 GitHub REST API**。
不再尝试连接器。

## Token 来源

- 来源：本机 Git Credential Manager（GCM），目标 `https://github.com`
- 读取方式：`git credential fill`（由 GCM 从 Windows 凭据管理器取出），不落盘、不回显
- 已知身份：`os-till-go`；对本仓库权限为 `pull=true, push=true, admin=false`（issue #7 记录）
- 只使用 HTTPS token；不使用 SSH key，不读取浏览器 cookie

## 使用的接口（均为只读 GET）

| 用途 | 接口 |
| --- | --- |
| 仓库元数据 | `/repos/{owner}/{repo}` |
| 全部 PR（含已关闭） | `/repos/{owner}/{repo}/pulls?state=all&per_page=100` |
| PR review | `/repos/{owner}/{repo}/pulls/{number}/reviews` |
| PR 行内 review 评论 | `/repos/{owner}/{repo}/pulls/{number}/comments` |
| PR 会话评论 | `/repos/{owner}/{repo}/issues/{number}/comments` |
| issue 列表 | `/repos/{owner}/{repo}/issues?state=all&per_page=100` |
| issue 评论 | `/repos/{owner}/{repo}/issues/{number}/comments` |
| release | `/repos/{owner}/{repo}/releases` |
| tag 及其说明 | `/repos/{owner}/{repo}/tags`、`/repos/{owner}/{repo}/git/ref/tags/{tag}` |

请求头：`Authorization: Bearer <token>`、`Accept: application/vnd.github+json`、
`X-GitHub-Api-Version: 2022-11-28`。

## 操作方式（PowerShell，token 仅在内存）

```powershell
$env:GIT_TERMINAL_PROMPT = '0'
$cred  = ("protocol=https`nhost=github.com`n`n" | git credential fill 2>$null)
$token = ($cred | Where-Object { $_ -like 'password=*' } | Select-Object -First 1) -replace '^password=',''
$headers = @{
  Authorization        = "Bearer $token"
  Accept               = 'application/vnd.github+json'
  'X-GitHub-Api-Version' = '2022-11-28'
  'User-Agent'         = 'local-audit'
}
# ... 只读 Invoke-RestMethod ...
$token = $null; $cred = $null; $headers = $null
```

## 禁止事项

1. **不打印、不写文件、不回显** token、`Authorization` 头或 `git credential fill` 的完整输出；只允许输出布尔值或长度。
2. 不把 token 写入 `.env`、脚本、日志、截图、提交信息或聊天记录。
3. 不通过 API 执行写操作：不建/改 PR、不评论、不合并、不推送、不改 issue 状态、不改 tag/release。
4. 不尝试用连接器兜底；连接器 404 时直接走本机凭据。
5. 命令结束后清空 `$token`、`$cred`、`$headers` 等变量。
6. 私有资源在权限不足时 GitHub 可能返回 **404**（隐藏资源），不能据此断言资源不存在；
   返回 **403** 时记录具体接口与缺失权限（如 `repo` scope、rate limit），不猜测内容。

## 2026-11-17 核查结论

- 仓库可读：`peng-fang/qwen-agent-contract-vam`（private，默认分支 `main`）。
- PR 共 7 个（#8–#14，均已合并关闭），**reviews / 行内评论 / 会话评论均为 0**。
- issue 共 7 个（#1–#7，均 closed）；仅 #6 有 1 条评论（研究计划，与条款代码无关）。
- release 0 个；tag 8 个，均为 annotated tag。
- 没有针对条款抽取/匹配、evidence_id、复核、风险评分、版本对比、对照页、评测与留出集的
  PR 评论；相关要求以 issue #1、#2、#3、#5 正文形式存在，详见 `STATUS.md` 同名章节。
