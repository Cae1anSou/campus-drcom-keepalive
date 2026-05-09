use anyhow::{Result, anyhow};
use if_addrs::IfAddr;
use rand::Rng;
use regex::Regex;
use serde_json::Value;
use std::collections::HashMap;
use std::net::IpAddr;
use std::path::Path;
use std::time::Duration;
use url::form_urlencoded;

pub const DEFAULT_BASE_URL: &str = "http://10.1.60.100";
pub const DEFAULT_JS_VERSION: &str = "4.2.1";
pub const DEFAULT_PROBE_URL: &str = "http://example.com/";
pub const DEFAULT_GATEWAY_CACHE_FILE: &str = ".campus_gateway_cache";

pub fn strip_inline_comment(value: &str) -> String {
    let mut quote: Option<char> = None;
    let chars: Vec<char> = value.chars().collect();
    for (index, ch) in chars.iter().enumerate() {
        if *ch == '\'' || *ch == '"' {
            quote = if quote == Some(*ch) {
                None
            } else if quote.is_none() {
                Some(*ch)
            } else {
                quote
            };
        } else if *ch == '#' && quote.is_none() && (index == 0 || chars[index - 1].is_whitespace())
        {
            return chars[..index]
                .iter()
                .collect::<String>()
                .trim_end()
                .to_string();
        }
    }
    value.trim().to_string()
}

pub fn unquote(value: &str) -> String {
    let chars: Vec<char> = value.chars().collect();
    if chars.len() >= 2
        && chars.first() == chars.last()
        && matches!(chars.first(), Some('\'') | Some('"'))
    {
        chars[1..chars.len() - 1].iter().collect()
    } else {
        value.to_string()
    }
}

pub fn parse_env_text(text: &str) -> HashMap<String, String> {
    let key_re = Regex::new(r"^[A-Za-z_][A-Za-z0-9_]*$").unwrap();
    let mut values = HashMap::new();
    for raw_line in text.lines() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') || !line.contains('=') {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        let key = key.trim();
        if key_re.is_match(key) {
            values.insert(
                key.to_string(),
                unquote(&strip_inline_comment(value.trim())),
            );
        }
    }
    values
}

pub fn load_env_file(path: impl AsRef<Path>) -> Result<HashMap<String, String>> {
    let path = path.as_ref();
    if path.as_os_str().is_empty() || !path.exists() {
        return Ok(HashMap::new());
    }
    Ok(parse_env_text(&std::fs::read_to_string(path)?))
}

pub fn parse_jsonp(text: &str) -> Result<Value> {
    let re = Regex::new(r"(?s)^[^(]*\((.*)\)\s*;?\s*$").unwrap();
    let payload = re
        .captures(text.trim())
        .and_then(|captures| captures.get(1))
        .ok_or_else(|| {
            anyhow!(
                "not a JSONP response: {:?}",
                text.chars().take(120).collect::<String>()
            )
        })?;
    Ok(serde_json::from_str(payload.as_str())?)
}

pub fn normalize_base_url(base_url: &str) -> String {
    base_url.trim().trim_end_matches('/').to_string()
}

pub fn interface_ipv4_address(interface: &str) -> Result<IpAddr> {
    for if_addr in if_addrs::get_if_addrs()? {
        if if_addr.name == interface
            && let IfAddr::V4(v4) = if_addr.addr
        {
            return Ok(IpAddr::V4(v4.ip));
        }
    }
    Err(anyhow!("interface {interface:?} has no IPv4 address"))
}

pub fn resolve_source_ip(
    source_ip: Option<&str>,
    interface: Option<&str>,
) -> Result<Option<IpAddr>> {
    match (
        source_ip.filter(|value| !value.is_empty()),
        interface.filter(|value| !value.is_empty()),
    ) {
        (Some(_), Some(_)) => Err(anyhow!("use either source-ip or interface, not both")),
        (Some(source_ip), None) => Ok(Some(source_ip.parse()?)),
        (None, Some(interface)) => Ok(Some(interface_ipv4_address(interface)?)),
        (None, None) => Ok(None),
    }
}

pub fn base_url_from_candidate_url(candidate_url: &str, probe_url: &str) -> Option<String> {
    let parsed = url::Url::parse(candidate_url).ok()?;
    if !matches!(parsed.scheme(), "http" | "https") || parsed.host_str().is_none() {
        return None;
    }
    let probe_host = url::Url::parse(probe_url)
        .ok()
        .and_then(|url| url.host_str().map(str::to_string));
    let host = parsed.host_str()?;
    let path = parsed.path().to_ascii_lowercase();
    let query = parsed.query().unwrap_or("").to_ascii_lowercase();
    let has_portal_hint =
        path.contains("drcom") || path.contains("chkuser") || query.contains("drcom");
    let is_private = is_private_ip(host);
    if Some(host) != probe_host.as_deref() && (is_private || has_portal_hint) {
        Some(
            format!("{}://{}", parsed.scheme(), parsed.authority())
                .trim_end_matches('/')
                .to_string(),
        )
    } else {
        None
    }
}

pub fn gateway_from_portal_html(html: &str) -> Option<String> {
    let patterns = [
        r#"v4serip=['"]([0-9]{1,3}(?:\.[0-9]{1,3}){3})['"]"#,
        r#"v46ip=['"]([0-9]{1,3}(?:\.[0-9]{1,3}){3})['"]"#,
        r#"http://([0-9]{1,3}(?:\.[0-9]{1,3}){3})/chkuser"#,
    ];
    for pattern in patterns {
        let re = Regex::new(pattern).unwrap();
        if let Some(ip) = re
            .captures(html)
            .and_then(|captures| captures.get(1))
            .map(|m| m.as_str())
            && is_private_ip(ip)
        {
            return Some(format!("http://{ip}"));
        }
    }
    None
}

fn is_private_ip(host: &str) -> bool {
    matches!(host.parse::<IpAddr>(), Ok(IpAddr::V4(addr)) if addr.is_private())
}

#[derive(Debug, Clone)]
pub struct DrcomClient {
    base_url: String,
    timeout: Duration,
    js_version: String,
    source_ip: Option<IpAddr>,
    http: reqwest::blocking::Client,
}

impl DrcomClient {
    pub fn new(
        base_url: impl Into<String>,
        timeout_secs: u64,
        source_ip: Option<IpAddr>,
    ) -> Result<Self> {
        let timeout = Duration::from_secs(timeout_secs);
        let mut builder = reqwest::blocking::Client::builder().timeout(timeout);
        if let Some(source_ip) = source_ip {
            builder = builder.local_address(source_ip);
        }
        Ok(Self {
            base_url: normalize_base_url(&base_url.into()),
            timeout,
            js_version: DEFAULT_JS_VERSION.to_string(),
            source_ip,
            http: builder.build()?,
        })
    }

    pub fn base_url(&self) -> &str {
        &self.base_url
    }

    pub fn source_ip(&self) -> Option<IpAddr> {
        self.source_ip
    }

    pub fn status(&self) -> Result<Value> {
        self.get_jsonp("/drcom/chkstatus", &[])
    }

    pub fn login(&self, username: &str, password: &str, service: &str) -> Result<Value> {
        let account = format!("{username}{service}");
        let params = [
            ("DDDDD", account.as_str()),
            ("upass", password),
            ("0MKKey", "123456"),
            ("R1", ""),
            ("R2", ""),
            ("R3", ""),
            ("R6", "0"),
            ("para", ""),
            ("v6ip", ""),
            ("terminal_type", "1"),
        ];
        self.get_jsonp("/drcom/login", &params)
    }

    fn get_jsonp(&self, path: &str, params: &[(&str, &str)]) -> Result<Value> {
        let url = build_drcom_url(&self.base_url, path, params, &self.js_version);
        let raw = self.http.get(url).timeout(self.timeout).send()?.text()?;
        parse_jsonp(&raw)
    }
}

pub fn build_drcom_url(
    base_url: &str,
    path: &str,
    params: &[(&str, &str)],
    js_version: &str,
) -> String {
    let mut serializer = form_urlencoded::Serializer::new(String::new());
    let callback = format!("dr{}", rand::rng().random_range(1000..=9999));
    serializer.append_pair("callback", &callback);
    for (key, value) in params {
        serializer.append_pair(key, value);
    }
    serializer.append_pair("jsVersion", js_version);
    serializer.append_pair("v", &rand::rng().random_range(500..=10499).to_string());
    serializer.append_pair("lang", "zh");
    format!(
        "{}{}?{}",
        normalize_base_url(base_url),
        path,
        serializer.finish()
    )
}

pub fn is_online(status: &Value, username: Option<&str>) -> bool {
    if status.get("result").and_then(Value::as_i64) != Some(1) {
        return false;
    }
    match (username, status.get("uid").and_then(Value::as_str)) {
        (Some(expected), Some(actual)) => expected == actual,
        _ => true,
    }
}

#[derive(Debug, Clone)]
pub enum EnsureAction {
    AlreadyOnline,
    Login,
}

#[derive(Debug, Clone)]
pub struct EnsureResult {
    pub action: EnsureAction,
    pub base_url: String,
    pub status: Value,
    pub login: Option<Value>,
}

pub fn ensure_online(
    client: &DrcomClient,
    username: &str,
    password: &str,
    service: &str,
) -> Result<EnsureResult> {
    let mut status_error = None;
    let status = match client.status() {
        Ok(status) => status,
        Err(error) => {
            status_error = Some(error.to_string());
            Value::Object(serde_json::Map::from_iter([(
                "result".to_string(),
                Value::from(0),
            )]))
        }
    };

    if is_online(&status, Some(username)) {
        return Ok(EnsureResult {
            action: EnsureAction::AlreadyOnline,
            base_url: client.base_url().to_string(),
            status,
            login: None,
        });
    }

    let login = client.login(username, password, service)?;
    if status_error.is_some() {
        // Keep behavior close to the Python version: status errors trigger login, but are not fatal.
    }
    Ok(EnsureResult {
        action: EnsureAction::Login,
        base_url: client.base_url().to_string(),
        status,
        login: Some(login),
    })
}

fn login_succeeded(result: &EnsureResult) -> bool {
    match result.action {
        EnsureAction::AlreadyOnline => true,
        EnsureAction::Login => result
            .login
            .as_ref()
            .and_then(|login| login.get("result"))
            .is_some_and(|value| value.as_i64() == Some(1) || value.as_str() == Some("1")),
    }
}

pub fn discover_gateway_base_url(
    probe_url: &str,
    timeout_secs: u64,
    source_ip: Option<IpAddr>,
) -> Option<String> {
    let timeout = Duration::from_secs(timeout_secs);
    let mut builder = reqwest::blocking::Client::builder().timeout(timeout);
    if let Some(source_ip) = source_ip {
        builder = builder.local_address(source_ip);
    }
    let client = builder.build().ok()?;
    let response = client.get(probe_url).timeout(timeout).send().ok()?;
    let final_url = response.url().to_string();
    let by_url = base_url_from_candidate_url(&final_url, probe_url);
    if by_url.is_some() {
        return by_url;
    }
    let html = response.text().ok()?;
    gateway_from_portal_html(&html)
}

pub fn load_cached_gateway(path: impl AsRef<Path>) -> Option<String> {
    let cached = std::fs::read_to_string(path).ok()?;
    let cached = normalize_base_url(&cached);
    let parsed = url::Url::parse(&cached).ok()?;
    if matches!(parsed.scheme(), "http" | "https") && parsed.host_str().is_some() {
        Some(cached)
    } else {
        None
    }
}

pub fn save_cached_gateway(path: impl AsRef<Path>, base_url: &str) -> Result<()> {
    let path = path.as_ref();
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        std::fs::create_dir_all(parent)?;
    }
    Ok(std::fs::write(
        path,
        format!("{}\n", normalize_base_url(base_url)),
    )?)
}

pub fn build_gateway_candidates(
    base_url: &str,
    cache_file: &str,
    auto_discover_gateway: bool,
    probe_url: &str,
    timeout_secs: u64,
    source_ip: Option<IpAddr>,
) -> Vec<String> {
    let mut candidates = vec![normalize_base_url(base_url)];
    let mut add = |candidate: Option<String>| {
        if let Some(candidate) = candidate.map(|url| normalize_base_url(&url))
            && !candidates.contains(&candidate)
        {
            candidates.push(candidate);
        }
    };
    add(load_cached_gateway(cache_file));
    if auto_discover_gateway {
        add(discover_gateway_base_url(
            probe_url,
            timeout_secs,
            source_ip,
        ));
    }
    candidates
}

pub struct KeepaliveOptions<'a> {
    pub base_url: &'a str,
    pub username: &'a str,
    pub password: &'a str,
    pub service: &'a str,
    pub timeout_secs: u64,
    pub cache_file: &'a str,
    pub auto_discover_gateway: bool,
    pub probe_url: &'a str,
    pub source_ip: Option<IpAddr>,
}

pub fn ensure_online_with_fallback(options: KeepaliveOptions<'_>) -> Result<EnsureResult> {
    let candidates = build_gateway_candidates(
        options.base_url,
        options.cache_file,
        options.auto_discover_gateway,
        options.probe_url,
        options.timeout_secs,
        options.source_ip,
    );
    let mut errors = Vec::new();
    for candidate in candidates {
        let client = match DrcomClient::new(&candidate, options.timeout_secs, options.source_ip) {
            Ok(client) => client,
            Err(error) => {
                errors.push(format!("{candidate}: {error}"));
                continue;
            }
        };
        match ensure_online(&client, options.username, options.password, options.service) {
            Ok(result) if login_succeeded(&result) => {
                save_cached_gateway(options.cache_file, &candidate)?;
                return Ok(result);
            }
            Ok(result) => {
                let msg = result
                    .login
                    .as_ref()
                    .and_then(|login| login.get("msg"))
                    .map(Value::to_string)
                    .unwrap_or_default();
                errors.push(format!("{candidate}: login failed {msg}"));
            }
            Err(error) => errors.push(format!("{candidate}: {error}")),
        }
    }
    Err(anyhow!(errors.join("; ")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_jsonp_payload() {
        let payload = parse_jsonp(r#"dr1002({"result":1,"uid":"test-user"});"#).unwrap();
        assert_eq!(payload["result"], 1);
        assert_eq!(payload["uid"], "test-user");
    }

    #[test]
    fn parses_env_text_with_quotes_and_comments() {
        let env = parse_env_text(
            r#"
            # comment
            CAMPUS_USERNAME=test-user
            CAMPUS_PASSWORD='secret value'
            CAMPUS_INTERVAL=30 # inline comment
            BAD-KEY=ignored
            "#,
        );
        assert_eq!(env.get("CAMPUS_USERNAME").unwrap(), "test-user");
        assert_eq!(env.get("CAMPUS_PASSWORD").unwrap(), "secret value");
        assert_eq!(env.get("CAMPUS_INTERVAL").unwrap(), "30");
        assert!(!env.contains_key("BAD-KEY"));
    }

    #[test]
    fn discovers_base_url_from_redirect_target() {
        let base = base_url_from_candidate_url(
            "http://10.99.253.230/chkuser?url=example.com/",
            DEFAULT_PROBE_URL,
        );
        assert_eq!(base.as_deref(), Some("http://10.99.253.230"));
    }

    #[test]
    fn discovers_base_url_from_portal_html() {
        let base = gateway_from_portal_html("v4serip='10.1.60.100'; v46ip='10.3.20.57';");
        assert_eq!(base.as_deref(), Some("http://10.1.60.100"));
    }

    #[test]
    fn login_url_keeps_credentials_before_common_params() {
        let url = build_drcom_url(
            "http://10.1.60.100",
            "/drcom/login",
            &[
                ("DDDDD", "test-user"),
                ("upass", "secret"),
                ("terminal_type", "1"),
            ],
            DEFAULT_JS_VERSION,
        );
        let query = url.split_once('?').unwrap().1;
        let keys: Vec<&str> = query
            .split('&')
            .map(|part| part.split_once('=').unwrap().0)
            .collect();
        assert!(
            keys.iter().position(|key| *key == "DDDDD").unwrap()
                < keys.iter().position(|key| *key == "jsVersion").unwrap()
        );
        assert!(
            keys.iter().position(|key| *key == "upass").unwrap()
                < keys.iter().position(|key| *key == "jsVersion").unwrap()
        );
        assert!(
            keys.iter().position(|key| *key == "terminal_type").unwrap()
                < keys.iter().position(|key| *key == "jsVersion").unwrap()
        );
    }

    #[test]
    fn resolves_source_ip_directly() {
        let source = resolve_source_ip(Some("10.3.20.57"), None).unwrap();
        assert_eq!(source.unwrap().to_string(), "10.3.20.57");
    }
}
