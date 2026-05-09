use anyhow::{Result, anyhow};
use campus_drcom_keepalive::{
    DEFAULT_BASE_URL, DEFAULT_GATEWAY_CACHE_FILE, DEFAULT_PROBE_URL, EnsureAction,
    KeepaliveOptions, ensure_online_with_fallback, load_env_file, resolve_source_ip,
};
use clap::Parser;
use std::collections::HashMap;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[derive(Debug, Parser)]
#[command(about = "Dr.COM campus network auto connect and keepalive")]
struct Cli {
    #[arg(long)]
    env_file: Option<String>,
    #[arg(long)]
    base_url: Option<String>,
    #[arg(long)]
    username: Option<String>,
    #[arg(long)]
    password: Option<String>,
    #[arg(long)]
    service: Option<String>,
    #[arg(long)]
    interval: Option<u64>,
    #[arg(long)]
    timeout: Option<u64>,
    #[arg(long)]
    probe_url: Option<String>,
    #[arg(long)]
    gateway_cache_file: Option<String>,
    #[arg(long)]
    source_ip: Option<String>,
    #[arg(long)]
    interface: Option<String>,
    #[arg(long)]
    no_auto_discover_gateway: bool,
    #[arg(long)]
    once: bool,
}

#[derive(Debug)]
struct Config {
    base_url: String,
    username: String,
    password: String,
    service: String,
    interval: u64,
    timeout: u64,
    probe_url: String,
    gateway_cache_file: String,
    source_ip: Option<String>,
    interface: Option<String>,
    auto_discover_gateway: bool,
    once: bool,
}

impl Config {
    fn from_cli(cli: Cli) -> Result<Self> {
        let env_file = cli
            .env_file
            .clone()
            .or_else(|| std::env::var("CAMPUS_ENV_FILE").ok())
            .unwrap_or_else(|| ".env".to_string());
        let file_env = load_env_file(&env_file)?;

        let username =
            value(cli.username, "CAMPUS_USERNAME", &file_env, None).ok_or_else(|| {
                anyhow!("missing credentials: set CAMPUS_USERNAME or pass --username")
            })?;
        let password =
            value(cli.password, "CAMPUS_PASSWORD", &file_env, None).ok_or_else(|| {
                anyhow!("missing credentials: set CAMPUS_PASSWORD or pass --password")
            })?;

        Ok(Self {
            base_url: value(
                cli.base_url,
                "CAMPUS_BASE_URL",
                &file_env,
                Some(DEFAULT_BASE_URL),
            )
            .unwrap(),
            username,
            password,
            service: value(cli.service, "CAMPUS_SERVICE", &file_env, Some("")).unwrap(),
            interval: numeric(cli.interval, "CAMPUS_INTERVAL", &file_env, 60)?,
            timeout: numeric(cli.timeout, "CAMPUS_TIMEOUT", &file_env, 10)?,
            probe_url: value(
                cli.probe_url,
                "CAMPUS_PROBE_URL",
                &file_env,
                Some(DEFAULT_PROBE_URL),
            )
            .unwrap(),
            gateway_cache_file: value(
                cli.gateway_cache_file,
                "CAMPUS_GATEWAY_CACHE_FILE",
                &file_env,
                Some(DEFAULT_GATEWAY_CACHE_FILE),
            )
            .unwrap(),
            source_ip: value(cli.source_ip, "CAMPUS_SOURCE_IP", &file_env, None)
                .filter(|value| !value.is_empty()),
            interface: value(cli.interface, "CAMPUS_INTERFACE", &file_env, None)
                .filter(|value| !value.is_empty()),
            auto_discover_gateway: !cli.no_auto_discover_gateway,
            once: cli.once,
        })
    }
}

fn value(
    cli_value: Option<String>,
    env_key: &str,
    file_env: &HashMap<String, String>,
    default: Option<&str>,
) -> Option<String> {
    cli_value
        .or_else(|| std::env::var(env_key).ok())
        .or_else(|| file_env.get(env_key).cloned())
        .or_else(|| default.map(str::to_string))
}

fn numeric(
    cli_value: Option<u64>,
    env_key: &str,
    file_env: &HashMap<String, String>,
    default: u64,
) -> Result<u64> {
    if let Some(value) = cli_value {
        return Ok(value);
    }
    if let Some(value) = std::env::var(env_key)
        .ok()
        .or_else(|| file_env.get(env_key).cloned())
    {
        return Ok(value.parse()?);
    }
    Ok(default)
}

fn log(message: &str) {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .unwrap_or_default();
    println!("[{seconds}] {message}");
}

fn run_once(config: &Config) -> Result<()> {
    let source_ip = resolve_source_ip(config.source_ip.as_deref(), config.interface.as_deref())?;
    let result = ensure_online_with_fallback(KeepaliveOptions {
        base_url: &config.base_url,
        username: &config.username,
        password: &config.password,
        service: &config.service,
        timeout_secs: config.timeout,
        cache_file: &config.gateway_cache_file,
        auto_discover_gateway: config.auto_discover_gateway,
        probe_url: &config.probe_url,
        source_ip,
    })?;
    let status_ip = result
        .status
        .get("v46ip")
        .or_else(|| result.status.get("v4ip"))
        .and_then(|value| value.as_str())
        .unwrap_or("");
    match result.action {
        EnsureAction::AlreadyOnline => log(&format!(
            "online uid={} ip={} gateway={}",
            result
                .status
                .get("uid")
                .and_then(|value| value.as_str())
                .unwrap_or(""),
            status_ip,
            result.base_url
        )),
        EnsureAction::Login => {
            let login = result.login.as_ref();
            let login_result = login
                .and_then(|value| value.get("result"))
                .map(ToString::to_string)
                .unwrap_or_default();
            let msg = login
                .and_then(|value| value.get("msg"))
                .and_then(|value| value.as_str())
                .unwrap_or("");
            log(&format!(
                "login attempted result={login_result} msg={msg} gateway={}",
                result.base_url
            ));
        }
    }
    Ok(())
}

fn main() -> Result<()> {
    let config = Config::from_cli(Cli::parse())?;
    loop {
        if let Err(error) = run_once(&config) {
            log(&format!("error: {error}"));
            if config.once {
                return Err(error);
            }
        }
        if config.once {
            return Ok(());
        }
        thread::sleep(Duration::from_secs(config.interval.max(5)));
    }
}
