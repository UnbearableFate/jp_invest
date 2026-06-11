# Codex 远程连接 Miyabi 操作记录

日期：2026-06-11  
本机：macOS Codex App 客户端  
远程主机别名：`miyabi-g`  
远程账号：`x10041@miyabi-g.jcahpc.jp`

本文档总结如何从当前 Codex 客户端连接到 Miyabi SSH 主机，如何处理带密码的 SSH 私钥和 authenticator/OTP 登录，如何检查连接状态，以及工作结束后如何断开连接。

## 1. SSH 配置

Codex App 会从 `~/.ssh/config` 中读取明确的 SSH 主机别名。我们添加或确认了如下配置：

```sshconfig
Host miyabi-g miyabi-g.jcahpc.jp
  HostName miyabi-g.jcahpc.jp
  User x10041
  IdentityFile /Users/unbearablefate/.ssh/id_rsa_tsukuba
  IdentitiesOnly yes
  AddKeysToAgent yes
  UseKeychain yes
  ControlMaster auto
  ControlPersist 8h
  ControlPath /Users/unbearablefate/.ssh/controlmasters/%C
```

关键点：

- `Host miyabi-g` 为 Codex App 提供一个短的、明确的主机别名。
- `IdentityFile` 指向筑波/Miyabi 使用的私钥。
- `AddKeysToAgent yes` 和 `UseKeychain yes` 让 macOS 缓存私钥密码。
- `ControlMaster auto` 启用 SSH 连接复用。
- `ControlPersist 8h` 让已认证的 SSH 主连接在空闲后最多保留 8 小时。
- `ControlPath` 指定 SSH 控制套接字的保存位置。

首次使用前创建控制套接字目录：

```bash
mkdir -p ~/.ssh/controlmasters
chmod 700 ~/.ssh/controlmasters
```

## 2. 私钥密码与 Authenticator

当前 SSH 私钥本身设置了密码，登录 Miyabi 还需要 authenticator/OTP。不要移除私钥密码，也不要绕过 MFA。

推荐流程：

```bash
ssh-add --apple-use-keychain ~/.ssh/id_rsa_tsukuba
ssh -MNf miyabi-g
```

作用说明：

- `ssh-add --apple-use-keychain` 会把私钥密码保存到 macOS Keychain/ssh-agent。
- `ssh -MNf miyabi-g` 会建立一个后台 SSH 主连接。
- 这一步服务器会要求输入 authenticator/OTP，正常输入即可。
- 后续 SSH 连接，包括 Codex App 的远程操作，可以复用这条已经认证过的主连接。

这不是绕过 MFA，而是先手动完成一次 MFA，然后在主连接存活期间复用这条已认证连接。

## 3. 检查 SSH 连接

检查 SSH 主连接是否还活着：

```bash
ssh -O check miyabi-g
```

成功时通常输出：

```text
Master running (pid=...)
```

如果主连接已经断开，重新建立：

```bash
ssh -MNf miyabi-g
```

也可以合并成一条检查并重连的命令：

```bash
ssh -O check miyabi-g || ssh -MNf miyabi-g
```

简单远程命令测试：

```bash
ssh miyabi-g 'hostname; whoami; date'
```

## 4. 检查远端 Codex

Codex App 的 SSH 远程项目要求远端登录 shell 能在 `PATH` 中找到 `codex` 命令。

检查远端 Codex：

```bash
ssh miyabi-g 'command -v codex; codex --version'
```

2026-06-11 实际检查结果：

```text
/home/x10041/.local/bin/codex
codex-cli 0.137.0
```

## 5. 在 Codex App 中添加 Miyabi

普通 SSH 可用后，在 Codex App 中配置：

1. 打开 `Settings > Connections`。
2. 添加或启用 SSH 主机。
3. 选择 `miyabi-g` 或 `miyabi-g.jcahpc.jp`。
4. 选择远程项目目录。

之后 Codex 会在 Miyabi 的远程文件系统和 shell 上运行远程项目线程。

官方参考：

- https://developers.openai.com/codex/remote-connections

## 6. 简单系统状态命令

我们使用如下只读命令检查远端状态：

```bash
ssh miyabi-g 'sh -s' <<'REMOTE_STATUS'
set +e
printf 'whoami: '; whoami
printf 'hostname: '; hostname
printf 'date: '; date
printf 'pwd: '; pwd
printf '\nuname:\n'; uname -a
printf '\nuptime:\n'; uptime
printf '\nmemory:\n'; (free -h || vmstat -s | head -n 12) 2>/dev/null
printf '\ndisk home:\n'; df -h "$HOME" 2>/dev/null || df -h .
printf '\ncodex:\n'; command -v codex && codex --version || printf 'codex not found in PATH\n'
REMOTE_STATUS
```

2026-06-11 实际结果摘要：

```text
whoami: x10041
hostname: miyabi-g3
date: Thu Jun 11 12:29:47 PM JST 2026
pwd: /home/x10041
kernel: Linux 5.14.0-427.13.1.el9_4.aarch64
arch: aarch64
uptime: up 3 days, 2:42
users: 41
load average: 4.91, 5.00, 5.15
memory: 234Gi total, 121Gi used, 54Gi free, 112Gi available
swap: 31Gi total, 677Mi used
home disk: 50G total, 3.9G used, 47G available, 8% used
codex: /home/x10041/.local/bin/codex
codex version: codex-cli 0.137.0
```

## 7. PBS 与 qstat

Miyabi 登录环境中可用的 PBS 命令：

```text
qsub  -> /opt/pbs/bin/qsub
qstat -> /usr/local/bin/qstat
qdel  -> /usr/local/bin/qdel
```

执行：

```bash
ssh miyabi-g 'qstat'
```

2026-06-11 实际输出：

```text
Miyabi scheduled stop time: 2026/06/24(Wed) 09:00:00 (Remain: 12days 20:27:07)

JOB_ID            JOB_NAME   STATUS    PROJECT    QUEUE           START_DATE       ELAPSE        TOKEN NODE MIG
2139919           ad1st.sh   RUNNING   xg24i002   small-g         06/11 11:54:56   00:36:18        9.7   16   -
```

## 8. 日常维护

使用 Codex 远程连接前：

```bash
ssh -O check miyabi-g || ssh -MNf miyabi-g
ssh miyabi-g 'hostname; command -v codex; codex --version'
```

如果 SSH 主连接还活着，Codex App 通常可以复用它。如果已经过期或网络断开，重新执行：

```bash
ssh -MNf miyabi-g
```

此时可能需要再次输入 authenticator/OTP。

`ControlPersist 8h` 并不保证连接一定精确存活 8 小时。集群策略、网络、登录节点状态或本机休眠都可能提前断开连接。

## 9. 工作结束后断开连接

关闭 SSH 主连接：

```bash
ssh -O exit miyabi-g
```

检查是否已经断开：

```bash
ssh -O check miyabi-g
```

如果提示控制套接字不存在或检查失败，说明主连接已经关闭。

更保守的替代命令：

```bash
ssh -O stop miyabi-g
```

区别：

```text
ssh -O exit miyabi-g   # 关闭当前 SSH 主连接
ssh -O stop miyabi-g   # 停止接受新的复用连接，但保留已有会话直到结束
ssh -O check miyabi-g  # 检查主连接是否还活着
```

推荐的结束流程：

1. 在 Codex App 中停止或完成活跃的远程任务。
2. 关闭相关远程线程，或确认没有命令正在运行。
3. 执行 `ssh -O exit miyabi-g`。
4. 用 `ssh -O check miyabi-g` 确认连接已经断开。

## 10. 安全注意事项

- 不要把私钥、authenticator code 或 `~/.codex/auth.json` 粘贴到聊天中。
- 如果远端 Codex 使用复制或缓存的认证文件，`~/.codex/auth.json` 应当像密码一样保护。
- 不要把 Codex app-server transport 直接暴露到公网。
- 使用 SSH、VPN 或可信 mesh network，不要开公网监听。
- 保持 `~/.ssh/id_rsa_tsukuba` 权限受限，通常应为 `600`。

---

# Codex Remote Connection to Miyabi

Date: 2026-06-11  
Local machine: macOS Codex App client  
Remote host alias: `miyabi-g`  
Remote account: `x10041@miyabi-g.jcahpc.jp`

This document summarizes how we configured the current Codex client to connect to the Miyabi SSH host, how to handle a passphrase-protected SSH key plus authenticator/OTP login, how to check the connection, and how to disconnect after work.

## 1. SSH Config

Codex App discovers SSH hosts from concrete aliases in `~/.ssh/config`. We added or confirmed the following host entry:

```sshconfig
Host miyabi-g miyabi-g.jcahpc.jp
  HostName miyabi-g.jcahpc.jp
  User x10041
  IdentityFile /Users/unbearablefate/.ssh/id_rsa_tsukuba
  IdentitiesOnly yes
  AddKeysToAgent yes
  UseKeychain yes
  ControlMaster auto
  ControlPersist 8h
  ControlPath /Users/unbearablefate/.ssh/controlmasters/%C
```

Key points:

- `Host miyabi-g` gives Codex App a short, concrete alias to discover.
- `IdentityFile` points to the Tsukuba/Miyabi private key.
- `AddKeysToAgent yes` and `UseKeychain yes` let macOS cache the private-key passphrase.
- `ControlMaster auto` enables SSH multiplexing.
- `ControlPersist 8h` keeps the authenticated master connection alive for up to 8 hours after it becomes idle.
- `ControlPath` stores the SSH control socket in a stable directory.

Create the control socket directory once:

```bash
mkdir -p ~/.ssh/controlmasters
chmod 700 ~/.ssh/controlmasters
```

## 2. Private-Key Passphrase and Authenticator

The SSH private key has a passphrase, and the Miyabi login also requires authenticator/OTP. Do not remove the key passphrase and do not bypass MFA.

Recommended workflow:

```bash
ssh-add --apple-use-keychain ~/.ssh/id_rsa_tsukuba
ssh -MNf miyabi-g
```

What this does:

- `ssh-add --apple-use-keychain` stores the private-key passphrase in macOS Keychain/ssh-agent.
- `ssh -MNf miyabi-g` opens a background SSH master connection.
- During this step, enter the authenticator/OTP when the server asks for it.
- Later SSH connections, including Codex App remote operations, can reuse the authenticated master connection.

This does not bypass MFA. It only means you complete MFA once, then reuse the same authenticated SSH master connection while it remains alive.

## 3. Check SSH Connection

Check whether the SSH master connection is alive:

```bash
ssh -O check miyabi-g
```

Expected successful output:

```text
Master running (pid=...)
```

If it is not alive, reopen it:

```bash
ssh -MNf miyabi-g
```

Combined check-and-reconnect command:

```bash
ssh -O check miyabi-g || ssh -MNf miyabi-g
```

Basic remote command test:

```bash
ssh miyabi-g 'hostname; whoami; date'
```

## 4. Check Remote Codex

Codex App remote SSH projects require the remote login shell to find the `codex` command in `PATH`.

Check remote Codex:

```bash
ssh miyabi-g 'command -v codex; codex --version'
```

Observed result on 2026-06-11:

```text
/home/x10041/.local/bin/codex
codex-cli 0.137.0
```

## 5. Add Miyabi in Codex App

After ordinary SSH works, configure Codex App:

1. Open `Settings > Connections`.
2. Add or enable an SSH host.
3. Choose `miyabi-g` or `miyabi-g.jcahpc.jp`.
4. Select the remote project directory.

Codex will then run remote project threads against Miyabi's filesystem and shell.

Official reference:

- https://developers.openai.com/codex/remote-connections

## 6. Simple System Status Commands

We used the following read-only command to inspect remote status:

```bash
ssh miyabi-g 'sh -s' <<'REMOTE_STATUS'
set +e
printf 'whoami: '; whoami
printf 'hostname: '; hostname
printf 'date: '; date
printf 'pwd: '; pwd
printf '\nuname:\n'; uname -a
printf '\nuptime:\n'; uptime
printf '\nmemory:\n'; (free -h || vmstat -s | head -n 12) 2>/dev/null
printf '\ndisk home:\n'; df -h "$HOME" 2>/dev/null || df -h .
printf '\ncodex:\n'; command -v codex && codex --version || printf 'codex not found in PATH\n'
REMOTE_STATUS
```

Observed result on 2026-06-11:

```text
whoami: x10041
hostname: miyabi-g3
date: Thu Jun 11 12:29:47 PM JST 2026
pwd: /home/x10041
kernel: Linux 5.14.0-427.13.1.el9_4.aarch64
arch: aarch64
uptime: up 3 days, 2:42
users: 41
load average: 4.91, 5.00, 5.15
memory: 234Gi total, 121Gi used, 54Gi free, 112Gi available
swap: 31Gi total, 677Mi used
home disk: 50G total, 3.9G used, 47G available, 8% used
codex: /home/x10041/.local/bin/codex
codex version: codex-cli 0.137.0
```

## 7. PBS and qstat

The Miyabi login environment has PBS commands available:

```text
qsub  -> /opt/pbs/bin/qsub
qstat -> /usr/local/bin/qstat
qdel  -> /usr/local/bin/qdel
```

Run:

```bash
ssh miyabi-g 'qstat'
```

Observed result on 2026-06-11:

```text
Miyabi scheduled stop time: 2026/06/24(Wed) 09:00:00 (Remain: 12days 20:27:07)

JOB_ID            JOB_NAME   STATUS    PROJECT    QUEUE           START_DATE       ELAPSE        TOKEN NODE MIG
2139919           ad1st.sh   RUNNING   xg24i002   small-g         06/11 11:54:56   00:36:18        9.7   16   -
```

## 8. Daily Maintenance

Before using Codex remote connection:

```bash
ssh -O check miyabi-g || ssh -MNf miyabi-g
ssh miyabi-g 'hostname; command -v codex; codex --version'
```

If the SSH master is alive, Codex App should normally be able to reuse it. If it has expired or the network dropped, rerun:

```bash
ssh -MNf miyabi-g
```

You may need to enter the authenticator/OTP again.

`ControlPersist 8h` does not guarantee the connection will always survive for exactly 8 hours. The cluster, network, login node, or local sleep state can still terminate it earlier.

## 9. Disconnect After Work

To close the SSH master connection:

```bash
ssh -O exit miyabi-g
```

Check whether it has disconnected:

```bash
ssh -O check miyabi-g
```

If it reports that the control socket is missing or the check failed, the master connection is already closed.

Alternative, more conservative command:

```bash
ssh -O stop miyabi-g
```

Difference:

```text
ssh -O exit miyabi-g   # close the current SSH master connection
ssh -O stop miyabi-g   # stop accepting new multiplexed sessions, keep existing sessions until they finish
ssh -O check miyabi-g  # check whether the master connection is alive
```

Recommended shutdown sequence:

1. Stop or finish active Codex remote work in Codex App.
2. Close related remote threads or ensure no command is running.
3. Run `ssh -O exit miyabi-g`.
4. Confirm with `ssh -O check miyabi-g`.

## 10. Security Notes

- Do not paste private keys, authenticator codes, or `~/.codex/auth.json` into chat.
- Treat `~/.codex/auth.json` like a password if remote Codex authentication is copied or cached.
- Do not expose Codex app-server transports directly on public networks.
- Use SSH, VPN, or a trusted mesh network rather than public listeners.
- Keep `~/.ssh/id_rsa_tsukuba` permission restricted, usually `600`.
