# campus-drcom-keepalive

浙江财经大学东方学院 Dr.COM 校园网自动连接与保活工具。

这是一个 Rust 写的单文件命令行程序。它会检查当前设备是否已经通过校园网认证；如果掉线，会自动调用 Dr.COM 登录接口重新认证。适合放在服务器、实验室主机、NAS、树莓派等需要长期在线的设备上。

普通使用者建议直接下载 Releases 里的预编译产物，不需要安装 Rust。

## 功能

- 自动检查 Dr.COM 在线状态
- 掉线后自动重新登录
- 网关自动探测和失败回退
- 缓存最近一次可用网关
- 支持按源 IP 或网卡绑定请求，便于有线和 Wi-Fi 分别认证
- 支持普通校园用户、电信、联通等账号后缀
- 支持 Linux、macOS、Windows
- Linux 上可配合 systemd 长期运行

## 配置项

账号和密码不需要编译进程序。程序支持三种配置方式：

| 方式 | 适用场景 |
| --- | --- |
| 命令行参数 | 临时测试，不建议长期放密码 |
| 环境变量 | 脚本、容器、系统服务 |
| `.env` 或 `--env-file` | 日常使用和 systemd 部署，推荐 |

配置读取优先级：

```text
命令行参数 > 环境变量 > 配置文件 > 默认值
```

`.env` 示例：

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

## Linux

### 1. 下载

在 Releases 下载：

```text
campus-drcom-keepalive-x86_64-unknown-linux-gnu.tar.gz
```

命令行下载示例：

```bash
curl -LO https://github.com/Cae1anSou/campus-drcom-keepalive/releases/latest/download/campus-drcom-keepalive-x86_64-unknown-linux-gnu.tar.gz
```

### 2. 解压和安装

```bash
tar -xzf campus-drcom-keepalive-x86_64-unknown-linux-gnu.tar.gz
chmod +x campus-drcom-keepalive
sudo install -m 755 campus-drcom-keepalive /usr/local/bin/campus-drcom-keepalive
```

确认可执行：

```bash
campus-drcom-keepalive --help
```

### 3. 配置

单次手动运行可以在当前目录使用 `.env`：

```bash
cp .env.example .env
vim .env
```

systemd 部署建议放到 `/etc/campus-keepalive.env`：

```bash
sudo install -m 600 .env.example /etc/campus-keepalive.env
sudoedit /etc/campus-keepalive.env
```

### 4. 运行

检测一次：

```bash
campus-drcom-keepalive --once
```

指定配置文件检测一次：

```bash
campus-drcom-keepalive --env-file /etc/campus-keepalive.env --once
```

长期前台运行：

```bash
campus-drcom-keepalive --env-file /etc/campus-keepalive.env
```

绑定有线网卡运行：

```bash
campus-drcom-keepalive --env-file /etc/campus-keepalive.env --interface enp7s0 --once
```

绑定 Wi-Fi 网卡运行：

```bash
campus-drcom-keepalive --env-file /etc/campus-keepalive.env --interface wlp0s20f3 --once
```

### 5. systemd 常驻

普通单实例：

```bash
sudo cp deploy/campus-keepalive.service.example /etc/systemd/system/campus-keepalive.service
sudo install -d -m 755 /var/lib/campus-keepalive
sudo systemctl daemon-reload
sudo systemctl enable --now campus-keepalive.service
sudo journalctl -u campus-keepalive.service -f
```

分别保活有线和 Wi-Fi：

```bash
sudo cp deploy/campus-keepalive@.service.example /etc/systemd/system/campus-keepalive@.service
sudo install -d -m 755 /var/lib/campus-keepalive
sudo systemctl daemon-reload
sudo systemctl enable --now campus-keepalive@enp7s0.service
sudo systemctl enable --now campus-keepalive@wlp0s20f3.service
sudo journalctl -u 'campus-keepalive@*.service' -f
```

模板服务会读取 `/etc/campus-keepalive.env`，并额外读取 `/etc/campus-keepalive-<网卡名>.env` 作为覆盖配置。

例如有线和 Wi-Fi 使用不同网关：

```dotenv
# /etc/campus-keepalive-enp7s0.env
CAMPUS_BASE_URL=http://10.99.253.230
```

```dotenv
# /etc/campus-keepalive-wlp0s20f3.env
CAMPUS_BASE_URL=http://10.1.60.100
```

## macOS

### 1. 选择下载文件

Apple Silicon 机型下载：

```text
campus-drcom-keepalive-aarch64-apple-darwin.tar.gz
```

Intel 机型下载：

```text
campus-drcom-keepalive-x86_64-apple-darwin.tar.gz
```

查看本机架构：

```bash
uname -m
```

`arm64` 对应 Apple Silicon，`x86_64` 对应 Intel。

### 2. 解压和安装

Apple Silicon 示例：

```bash
curl -LO https://github.com/Cae1anSou/campus-drcom-keepalive/releases/latest/download/campus-drcom-keepalive-aarch64-apple-darwin.tar.gz
tar -xzf campus-drcom-keepalive-aarch64-apple-darwin.tar.gz
chmod +x campus-drcom-keepalive
sudo install -m 755 campus-drcom-keepalive /usr/local/bin/campus-drcom-keepalive
```

Intel 示例：

```bash
curl -LO https://github.com/Cae1anSou/campus-drcom-keepalive/releases/latest/download/campus-drcom-keepalive-x86_64-apple-darwin.tar.gz
tar -xzf campus-drcom-keepalive-x86_64-apple-darwin.tar.gz
chmod +x campus-drcom-keepalive
sudo install -m 755 campus-drcom-keepalive /usr/local/bin/campus-drcom-keepalive
```

如果 macOS 提示来自未验证开发者，可以先移除隔离属性：

```bash
xattr -d com.apple.quarantine /usr/local/bin/campus-drcom-keepalive
```

确认可执行：

```bash
campus-drcom-keepalive --help
```

### 3. 配置

```bash
cp .env.example .env
open -e .env
```

也可以使用环境变量：

```bash
export CAMPUS_USERNAME='<你的学号或账号>'
export CAMPUS_PASSWORD='<你的密码>'
campus-drcom-keepalive --once
```

### 4. 运行

检测一次：

```bash
campus-drcom-keepalive --once
```

长期前台运行：

```bash
campus-drcom-keepalive
```

绑定源地址运行：

```bash
campus-drcom-keepalive --source-ip 10.110.245.255 --once
```

绑定网卡运行：

```bash
campus-drcom-keepalive --interface en0 --once
```

查看网卡名：

```bash
networksetup -listallhardwareports
ifconfig
```

### 5. 常驻方式

macOS 可以用 `launchd` 常驻，但仓库目前没有内置 plist 模板。建议先用 `--once` 验证账号、网关和网卡绑定都正常，再添加 launchd 配置。

## Windows

### 1. 下载

在 Releases 下载：

```text
campus-drcom-keepalive-x86_64-pc-windows-msvc.zip
```

PowerShell 下载示例：

```powershell
Invoke-WebRequest `
  -Uri "https://github.com/Cae1anSou/campus-drcom-keepalive/releases/latest/download/campus-drcom-keepalive-x86_64-pc-windows-msvc.zip" `
  -OutFile "campus-drcom-keepalive-x86_64-pc-windows-msvc.zip"
```

### 2. 解压和安装

```powershell
Expand-Archive .\campus-drcom-keepalive-x86_64-pc-windows-msvc.zip -DestinationPath .\campus-drcom-keepalive
cd .\campus-drcom-keepalive
.\campus-drcom-keepalive.exe --help
```

如果想全局使用，可以把该目录加入 `PATH`。

### 3. 配置

```powershell
Copy-Item .env.example .env
notepad .env
```

也可以使用环境变量：

```powershell
$env:CAMPUS_USERNAME = '<你的学号或账号>'
$env:CAMPUS_PASSWORD = '<你的密码>'
.\campus-drcom-keepalive.exe --once
```

### 4. 运行

检测一次：

```powershell
.\campus-drcom-keepalive.exe --once
```

长期前台运行：

```powershell
.\campus-drcom-keepalive.exe
```

绑定源地址运行：

```powershell
.\campus-drcom-keepalive.exe --source-ip 10.110.245.255 --once
```

绑定网卡运行：

```powershell
.\campus-drcom-keepalive.exe --interface "Wi-Fi" --once
```

查看网卡名和 IPv4 地址：

```powershell
Get-NetIPAddress -AddressFamily IPv4
Get-NetAdapter
```

### 5. 常驻方式

Windows 可以用“任务计划程序”运行。

建议先创建一个固定目录，例如：

```powershell
New-Item -ItemType Directory -Force C:\campus-drcom-keepalive
Copy-Item .\campus-drcom-keepalive.exe C:\campus-drcom-keepalive\
Copy-Item .\.env C:\campus-drcom-keepalive\
```

然后在任务计划程序中创建任务：

```text
程序: C:\campus-drcom-keepalive\campus-drcom-keepalive.exe
起始于: C:\campus-drcom-keepalive
触发器: 登录时，或开机时
```

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `--once` | 只检测一次后退出 |
| `--env-file <path>` | 指定配置文件 |
| `--base-url <url>` | 指定 Dr.COM 网关 |
| `--probe-url <url>` | 指定自动探测用 URL |
| `--gateway-cache-file <path>` | 指定网关缓存文件 |
| `--source-ip <ip>` | 绑定请求使用的本机 IPv4 地址 |
| `--interface <name>` | 绑定请求使用的网卡 |
| `--no-auto-discover-gateway` | 关闭网关自动探测 |

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
