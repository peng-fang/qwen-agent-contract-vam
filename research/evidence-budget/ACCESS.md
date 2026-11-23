# 协作者能访问网页，为什么连接器仍然 404？

核验日期：2026-11-14。目标仓库 `peng-fang/qwen-agent-contract-vam`。

## 本次实际核验

| 通路 | 账号 / 权限 | 结果 |
|---|---|---|
| 当前 GitHub 连接器 | 已核对为 `os-till-go` | `get_repo` 返回 404 |
| 当前连接器的安装列表 | 可访问的安装账户不包含 `peng-fang` | 不能据此断定所有者完全没装 App，只能确认当前连接没有显示这条安装访问路径 |
| 本机 Git Credential Manager 保存的凭据 → GitHub REST | `/user` 确认为 `os-till-go`；仓库 `pull=true, push=true, admin=false` | 仓库元数据与已有 issues 读取成功 |
| 本地 Git 克隆 | origin 指向目标私有仓库；现有 research 分支基于 `88c7bb5` | 源码可读，后续可沿本机 Git/API 工作 |

结论：用户身份并未整体失去仓库权限；**当前连接器凭据的仓库访问范围与本机 Git 凭据不同**。这已足够解释“网页可见、Agent 的某个连接器 404”为什么可以同时发生。连接器精确缺哪一项安装/授权，仍需所有者和连接用户核对，不能只凭 404 一口断定。

## 两层权限要分别成立

1. **个人权限**：当前登录用户被邀请为协作者，并已接受邀请。
2. **所用程序的权限**：当前 GitHub App、OAuth token、PAT 或 SSH 身份也必须能访问该仓库。不同 Agent/客户端可能使用不同通路。

GitHub 为隐藏私有资源的存在，会在认证不足时返回 404。GitHub App 还需要安装到资源所属账户，并获得目标仓库访问；“我的账户下 All repositories”不会自动覆盖别人拥有的所有私有仓库。见 [REST API 认证排错](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api#404-not-found-for-an-existing-resource)、[GitHub App 的安装与授权区别](https://docs.github.com/en/apps/using-github-apps/installing-a-github-app-from-a-third-party#difference-between-installation-and-authorization)。

## 希望继续使用连接器时

- 由仓库所有者在 GitHub **Settings → Applications → Installed GitHub Apps** 核对与当前客户端对应的同一款 App。若已安装，检查 Configure 中是否包含本仓库；只授权需要的仓库即可。
- 协作者核对连接器登录账号、是否接受更新的 App 权限，并刷新仓库列表/重新建立该连接。成功标准是同一个连接器能读取本仓库 README 和 issue，而不是只看到“已连接 GitHub”。
- 若所有者已经授权仍失败，继续核对 App 是否相同、协作者自己的授权、组织策略（组织仓库时）与凭据有效性；不应直接将仓库改公开。
- 当前账号没有该仓库管理权，本次没有更改任何安装、授权或仓库可见性。修复连接器不妨碍当前本机 Git/API 工作。

其他课程项目可用同样的对照方法排查，但不能把本次结论直接当作其具体根因。细粒度 PAT 还有外部协作者等使用限制，应依 [官方 token 文档](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) 检查；本次无需创建或共享新 token。

## fork 已经确认

GitHub REST 元数据：`private=true, fork=false`，无 `parent/source`。它不是 GitHub 标记的 fork。

但当前上游 Qwen-Agent main `31a4d36d123688581a9e9744427272b33ce940e0` 是本项目祖先；本项目在其后有 4 个提交。`qwen_agent/`、`tests/`、`setup.py` 与该上游版本无差异。故代码派生关系明确；仅凭这些事实不能区分作者是 clone 后推到新仓库、导入还是其他保留历史的方式。
