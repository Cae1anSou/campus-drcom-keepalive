# campus-drcom-keepalive

浙江财经大学东方学院 Dr.COM 校园网自动连接与保活工具。

这是一个 Rust 写的单文件命令行程序。它会检查当前设备是否已经通过校园网认证；如果掉线，会自动调用 Dr.COM 登录接口重新认证。适合放在服务器、实验室主机、NAS、树莓派等需要长期在线的设备上。

## 功能

- 自动检查 Dr.COM 在线状态
- 掉线后自动重新登录
- 网关自动探测和失败回退
- 缓存最近一次可用网关
- 支持按源 IP 或网卡绑定请求，便于有线和 Wi-Fi 分别认证
- 支持普通校园用户、电信、联通等账号后缀
- 支持 macOS、Linux、Windows
- Linux 上可配合 systemd 长期运行

## 下载安装

普通使用者建议直接下载 Releases 里的预编译产物，不需要安装 Rust。

在 GitHub Releases 中选择对应平台：

| 系统 | 文件 |
| --- | --- |
| Linux x86_64 | `campus-drcom-keepalive-x86_64-unknown-linux-gnu.tar.gz` |
| macOS Apple Silicon | `campus-drcom-keepalive-aarch64-apple-darwin.tar.gz` |
| macOS Intel | `campus-drcom-keepalive-x86_64-apple-darwin.tar.gz` |
| Windows x86_64 | `campus-drcom-keepalive-x86_64-pc-windows-msvc.zip` |

Linux/macOS 解压后可以这样安装：

```bash
tar -xzf campus-drcom-keepalive-<target>.tar.gz
chmod +x campus-drcom-keepalive
sudo install -m 755 campus-drcom-keepalive /usr/local/bin/campus-drcom-keepalive
```

Windows 解压 zip 后，在 PowerShell 中运行：

```powershell
.\campus-drcom-keepalive.exe --help
```

## 配置

创建 `.env`：

```dotenv
CAMPUS_USERNAME=<你的学号或账号>
CAMPUS_PASSWORD=<你的密码>
CAMPUS_SERVICE=
CAMPUS_INTERVAL=60
CAMPUS_TIMEOUT=10
CAMPUS_BASE_URL=http://10.1.60.100
CAMPUS_PROBE_URL=http://example.com/
CAMPUS_GATEWAY_CACHE_FILE=.campus_gateway_cache
CAMPUS_SOURCE_IP=
CAMPUS_INTERFACE=
```

运营商后缀：

| 类型 | `CAMPUS_SERVICE` |
| --- | --- |
| 校园用户 | 留空 |
| 校园电信 | `@dx` |
| 校园联通 | `@lt` |

## 使用

运行一次检测：

```bash
campus-drcom-keepalive --once
```

长期运行：

```bash
campus-drcom-keepalive
```

指定配置文件：

```bash
campus-drcom-keepalive --env-file /etc/campus-keepalive.env
```

绑定到指定源地址：

```bash
campus-drcom-keepalive --source-ip 10.3.20.57 --once
```

绑定到指定网卡：

```bash
campus-drcom-keepalive --interface enp7s0 --once
campus-drcom-keepalive --interface wlp0s20f3 --once
```

`--source-ip` 是跨平台主路径；`--interface` 会从系统网卡列表中解析 IPv4 地址，适用于 macOS、Linux、Windows。

如果校园网网关变化，默认会自动探测。只想使用指定网关时：

```bash
campus-drcom-keepalive --no-auto-discover-gateway
```

## systemd 部署

把真实账号密码放在 `/etc/campus-keepalive.env`：

```dotenv
CAMPUS_USERNAME=<你的学号或账号>
CAMPUS_PASSWORD=<你的密码>
CAMPUS_SERVICE=
CAMPUS_INTERVAL=60
CAMPUS_TIMEOUT=10
```

安装二进制和服务文件：

```bash
sudo install -m 755 campus-drcom-keepalive /usr/local/bin/campus-drcom-keepalive
sudo cp deploy/campus-keepalive.service.example /etc/systemd/system/campus-keepalive.service
sudo install -d -m 755 /var/lib/campus-keepalive
sudo systemctl daemon-reload
sudo systemctl enable --now campus-keepalive.service
sudo journalctl -u campus-keepalive.service -f
```

如果要分别保活有线和 Wi-Fi，使用模板服务：

```bash
sudo cp deploy/campus-keepalive@.service.example /etc/systemd/system/campus-keepalive@.service
sudo systemctl daemon-reload
sudo systemctl enable --now campus-keepalive@enp7s0.service
sudo systemctl enable --now campus-keepalive@wlp0s20f3.service
sudo journalctl -u 'campus-keepalive@*.service' -f
```

模板服务会读取 `/etc/campus-keepalive.env`，并额外读取 `/etc/campus-keepalive-<网卡名>.env` 作为覆盖配置。

例如：

```dotenv
# /etc/campus-keepalive-enp7s0.env
CAMPUS_BASE_URL=http://10.99.253.230
```

```dotenv
# /etc/campus-keepalive-wlp0s20f3.env
CAMPUS_BASE_URL=http://10.1.60.100
```

## 工作原理

当前 Dr.COM Web 认证接口：

| 用途 | 接口 |
| --- | --- |
| 查询在线状态 | `GET <网关>/drcom/chkstatus` |
| 登录认证 | `GET <网关>/drcom/login` |

接口返回 JSONP，例如：

```text
dr1002({"result":1,"uid":"..."});
```

登录参数与前端页面保持一致：

```text
DDDDD=<账号>
upass=<密码>
0MKKey=123456
R1=
R2=
R3=
R6=0
para=
v6ip=
terminal_type=1
```

程序不会主动注销，也不会在已经在线时重复登录。运行流程：

1. 先尝试 `CAMPUS_BASE_URL` 的 `/drcom/chkstatus` 和 `/drcom/login`。
2. 如果失败，读取网关缓存并重试。
3. 如果仍失败，访问 `CAMPUS_PROBE_URL` 自动探测当前网关并重试。
4. 成功后缓存可用网关。
5. 按 `CAMPUS_INTERVAL` 继续下一轮检测。

## 开发

需要 Rust 工具链。

```bash
cargo test
cargo clippy --all-targets -- -D warnings
cargo build --release
```

跨平台检查：

```bash
rustup target add x86_64-unknown-linux-gnu x86_64-pc-windows-msvc
cargo check --target x86_64-unknown-linux-gnu
cargo check --target x86_64-pc-windows-msvc
```

本地运行：

```bash
cargo run -- --once
```

## 发布

打 tag 后 GitHub Actions 会自动构建 release 产物：

```bash
git tag v0.1.0
git push origin v0.1.0
```

产物会上传到对应 GitHub Release。

## 常见问题

### `Error code: 203 Bad request(2)`

断网后状态接口有时返回 HTML 错误页，而不是 JSONP：

```text
<html><body>
Error code: 203 Bad request(2)
</body></html>
```

这通常表示当前设备已经不在认证在线状态。程序会把这种状态查询异常当成离线，然后继续尝试登录。

如果登录接口也持续返回 203，请检查：

- 当前设备仍连接在校园网内
- `.env` 中账号和密码正确
- `CAMPUS_SERVICE` 是否需要填写 `@dx` 或 `@lt`
- `CAMPUS_BASE_URL` 是否适用于当前接入网络

## 安全说明

- 不要把真实密码提交到 GitHub。
- `.env` 已被 `.gitignore` 忽略，公开仓库只保留 `.env.example`。
- 该工具只面向你自己有权使用的校园网账号和设备。
- 程序只做状态检测和掉线重连，不尝试绕过、攻击或破坏认证系统。

## 适用范围

这个仓库目前针对浙江财经大学东方学院 Dr.COM 网关整理和测试。其他学校即使也使用 Dr.COM，接口路径和参数也可能不同。
