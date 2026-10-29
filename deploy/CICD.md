# CI/CD 方案：GitHub Actions → 阿里云

> 一次 `git push`，自动跑测试 → 构建镜像 → 推阿里云镜像仓库 → SSH 到服务器重启容器 → 健康检查失败自动回滚。

---

## 一、整体架构

```
开发者 git push main
        │
        ▼
┌──────────────────────────────────────────────┐
│ GitHub Actions（ubuntu-latest, 免费额度）    │
│                                              │
│  ① test    ruff check + pytest (24 用例)     │
│  ② build   docker build (linux/amd64)        │
│            └─▶ push 阿里云 ACR: <sha> + latest│
│  ③ deploy  scp 部署脚本 + ssh 执行            │
└───────────────────┬──────────────────────────┘
                    │ SSH（密钥认证）
                    ▼
┌──────────────────────────────────────────────┐
│ 阿里云 ECS                                   │
│  /verifly/activity-export/remote-deploy.sh               │
│     docker pull <sha>                        │
│     docker run（只读挂附件 + 审计目录）       │
│     curl /healthz  × 30 次                   │
│       成功 → 记录版本，结束                   │
│       失败 → 自动回滚到上一版                 │
└──────────────────────────────────────────────┘
```

**为什么在 CI 构建镜像，而不是在服务器构建？**

| 方案 | 优点 | 缺点 |
|---|---|---|
| **CI 构建推送（推荐）** | 服务器不用装构建环境；镜像有版本号可回滚；构建慢不占服务器 CPU | 需要镜像仓库 |
| 服务器自己 build | 省镜像仓库 | 每次部署占满服务器 CPU，构建失败服务已停 |

服务器只有 1~2 核，`docker build` 会把线上报名服务拖垮，所以选 CI 构建。

---

## 二、你需要准备的东西（按顺序）

### 1. GitHub 仓库

```bash
cd ~/Documents/mvp/verifly/verifly-activity/export-service
git remote add origin https://github.com/verifly-team/activity-collecetion-admin.git
git push -u origin main
```

### 2. 阿里云容器镜像服务 ACR（个人版免费）

1. 登录 [阿里云容器镜像服务控制台](https://cr.console.aliyun.com)
2. 选 **个人实例** → 创建命名空间 `arceus`（如果已有就跳过）
3. 创建仓库 `activity-66-export`，类型选**私有**
4. 记下：
   - 登录地址：`crpi-quxtxo1i28qk1e0c.cn-guangzhou.personal.cr.aliyuncs.com`
   - 用户名：一般是阿里云账号全名
   - 密码：**固定密码**在「访问凭证」里设置（不是登录密码）

### 3. 服务器准备

```bash
# ① 装 Docker（如果没装）
curl -fsSL https://get.docker.com | sh

# ② 建部署用户（不要用 root 跑 CI）
useradd -m -s /bin/bash deploy
usermod -aG docker deploy

# ③ 目录
mkdir -p /verifly/activity/{uploads,audit,export}
chown -R 10001:10001 /verifly/activity/uploads
chmod 700 /verifly/activity-export

# ④ 配置文件（内容见 deploy/RUNBOOK.md 第 2.4 节）
# 从仓库拷一份模板过去，改两个值即可
cp deploy/export.env.example /verifly/activity-export/export.env
vi /verifly/activity-export/export.env && chmod 600 /verifly/activity-export/export.env

# ⑤ 把 CI 的公钥装进 deploy 用户（密钥在本机生成，见下方「SSH 密钥怎么来」）
#    这一步在服务器上执行：
mkdir -p /home/deploy/.ssh && chmod 700 /home/deploy/.ssh
echo '<本机 id_deploy.pub 的内容>' >> /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
```

#### SSH 密钥怎么来

**推荐：在本机生成，把公钥装到服务器，私钥只放 GitHub Secrets。**
私钥永远不落在服务器上。

```bash
# ① 本机（Mac / 你的电脑）生成，专门给 CI 用，不要复用个人密钥
ssh-keygen -t ed25519 -N "" -C "github-actions@verifly" -f ~/.ssh/id_deploy_gh

# ② 把公钥装到服务器
ssh-copy-id -i ~/.ssh/id_deploy_gh.pub deploy@<服务器IP>
#    或者手动：cat ~/.ssh/id_deploy_gh.pub 后粘贴进服务器 authorized_keys

# ③ 先验证能连上，再去配 GitHub
ssh -i ~/.ssh/id_deploy_gh deploy@<服务器IP> 'docker ps && echo OK'

# ④ 复制私钥全文 → GitHub Secrets 的 SSH_PRIVATE_KEY
#    macOS：
pbcopy < ~/.ssh/id_deploy_gh
#    Linux：
xclip -sel clip < ~/.ssh/id_deploy_gh
#    Windows：记事本打开 %USERPROFILE%\.ssh\id_deploy_gh，Ctrl+A 全选复制
```

**粘贴注意事项（踩坑重灾区）：**

| 要点 | 说明 |
|---|---|
| 必须包含首尾两行 | `-----BEGIN OPENSSH PRIVATE KEY-----` 和 `-----END OPENSSH PRIVATE KEY-----` |
| 不要加引号 | 粘 raw 文本，不要 `"..."` |
| 结尾要有换行 | 少了最后一行换行，SSH 会报 `invalid format` |
| 别用 `cat -A` 复制 | 会带 `$` 等不可见字符 |

**可选加固**：在服务器 `authorized_keys` 里给这个 key 加前缀，
禁掉端口转发等非必要能力：

```
restrict ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... github-actions@verifly
```

**应急方案**：如果手上没有方便操作的电脑，也可以在服务器上生成再删私钥：

```bash
sudo -u deploy ssh-keygen -t ed25519 -N "" -f /home/deploy/.ssh/id_deploy
cat /home/deploy/.ssh/id_deploy.pub >> /home/deploy/.ssh/authorized_keys
cat /home/deploy/.ssh/id_deploy          # 复制内容到 GitHub Secrets
shred -u /home/deploy/.ssh/id_deploy     # 复制完立刻删掉
```

### 4. GitHub Secrets（仓库 → Settings → Secrets and variables → Actions）

| Secret 名 | 值 | 从哪来 |
|---|---|---|
| `ACR_REGISTRY` | `crpi-quxtxo1i28qk1e0c.cn-guangzhou.personal.cr.aliyuncs.com` | ACR 控制台 |
| `ACR_NAMESPACE` | `arceus` | ACR 命名空间 |
| `ACR_REPO` | `activity-66-export` | ACR 仓库名 |
| `ACR_USERNAME` | 阿里云账号全名 | ACR 访问凭证 |
| `ACR_PASSWORD` | 固定密码 | ACR 访问凭证 |
| `SSH_HOST` | 服务器公网 IP | — |
| `SSH_USER` | `deploy` | — |
| `SSH_PORT` | `22`（可选） | — |
| `SSH_PRIVATE_KEY` | 上面 `id_deploy` 私钥**全文** | 服务器 |

> ⚠️ **`EXPORT_TOKEN` 不要放进 GitHub**。它只存在于服务器 `/verifly/activity-export/export.env`，
> CI 只负责发镜像，不碰任何业务密钥。

### 5. GitHub Environment（可选但建议）

Settings → Environments → New environment → `production` → 勾 **Required reviewers**。

这样部署前需要人工点确认，防止误推直接上生产。

### 6. 安全组

阿里云 ECS 安全组放行 `8010`（或只放行公司 IP，更安全）。

---

## 三、触发方式

| 场景 | 操作 | 结果 |
|---|---|---|
| 日常发布 | `git push origin main` | 自动测试→构建→部署 |
| 跳过测试 | Actions 页面手动 Run，勾 `skip_tests` | 直接构建部署 |
| 只改文档 | 改 `docs/`、`*.md` | **不触发**（workflow 里已配 paths-ignore） |

---

## 四、部署流程细节

`deploy/remote-deploy.sh` 每次由 CI 上传到服务器 `/verifly/activity-export/remote-deploy.sh`，
保证**服务器脚本永远和仓库一致**，不会出现"改了脚本忘了同步"。

它做的事：

1. 读 `/verifly/activity-export/.last-image` 记下当前版本（回滚用）
2. `docker pull <新镜像>` —— **拉取失败直接退出，线上不动**
3. `docker rm -f` + `docker run` 新容器
4. 轮询 `curl /healthz`，最多等 60 秒
5. 成功 → 记录新版本号
6. 失败 → **自动回滚到上一版**并报警
7. 全过程写 `/verifly/activity-export/deploy.log`

镜像标签用 **git commit 短 SHA**（如 `a1b2c3d`），而不是 `latest`，
这样任何一版都能精确回滚。

---

## 五、验证清单

部署完在服务器上跑：

```bash
curl -s localhost:8010/healthz                 # {"ok":true}
curl -s -o /dev/null -w "%{http_code}\n" localhost:8010/docs   # 404
docker ps --filter name=verifly-export         # Up (healthy)
cat /verifly/activity-export/.last-image                   # 当前版本 tag
tail -20 /verifly/activity-export/deploy.log               # 部署记录
```

浏览器打开 `http://<IP>:8010/?token=<EXPORT_TOKEN>`，导出一次，
然后在「审计日志」页确认有记录。

---

## 六、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| Actions 构建失败 `denied` | ACR 用户名/密码错 | 重新设置固定密码 |
| 部署步骤 SSH 超时 | 安全组没放行 22 / 密钥不对 | 手动 `ssh -i` 试一次 |
| 部署后 502 | 容器起来但连不上 MySQL | `docker logs verifly-export`，查 `DATABASE_URL` |
| 自动回滚了 | 新版本健康检查失败 | 看 `/verifly/activity-export/deploy.log` 里的容器日志 |
| 想手动回滚 | — | `./remote-deploy.sh <上一版完整镜像地址>` |

---

## 七、成本

| 项 | 费用 |
|---|---|
| GitHub Actions（私有仓库） | 每月 2000 分钟免费；本项目单次约 2 分钟 |
| 阿里云 ACR 个人版 | 免费（3 个仓库、500MB 存储起） |
| 流量 | 镜像约 120MB，每月几次可忽略 |
