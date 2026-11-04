use std::env;

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};

#[tauri::command]
fn amy_info() -> serde_json::Value {
    serde_json::json!({
        "name": "Amy",
        "role": "desktop-launcher",
        "default_url": "http://127.0.0.1:8787"
    })
}

fn host_base() -> (String, String, String) {
    let token = env::var("AMY_TOKEN").unwrap_or_default();
    let host = env::var("AMY_HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let port = env::var("AMY_PORT").unwrap_or_else(|_| "8787".into());
    (host, port, token)
}

fn with_token(url: &str, token: &str) -> String {
    if token.is_empty() {
        url.to_string()
    } else if url.contains('?') {
        format!("{url}&token={token}")
    } else {
        format!("{url}?token={token}")
    }
}

fn hud_url_from_env() -> String {
    if let Ok(u) = env::var("AMY_HUD_URL") {
        if !u.trim().is_empty() {
            return u;
        }
    }
    let (host, port, token) = host_base();
    with_token(&format!("http://{host}:{port}/"), &token)
}

fn orb_url_from_env() -> String {
    if let Ok(u) = env::var("AMY_ORB_URL") {
        if !u.trim().is_empty() {
            return u;
        }
    }
    let (host, port, token) = host_base();
    with_token(&format!("http://{host}:{port}/?view=orb"), &token)
}

fn env_f64(key: &str, default: f64) -> f64 {
    env::var(key)
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .unwrap_or(default)
}

fn open_or_focus_hud(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("hud") {
        let _ = w.show();
        let _ = w.set_focus();
        return;
    }
    let url = hud_url_from_env();
    let parsed = url
        .parse()
        .unwrap_or_else(|_| "http://127.0.0.1:8787/".parse().unwrap());
    let x = env_f64("AMY_HUD_X", 420.0);
    let y = env_f64("AMY_HUD_Y", 80.0);
    let w = env_f64("AMY_HUD_W", 720.0);
    let h = env_f64("AMY_HUD_H", 820.0);
    let builder = WebviewWindowBuilder::new(app, "hud", WebviewUrl::External(parsed))
        .title("Amy")
        .inner_size(w, h)
        .position(x, y)
        .resizable(true);
    let _ = builder.build();
}

fn open_or_focus_orb(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("orb") {
        let _ = w.show();
        let _ = w.set_focus();
        let _ = w.set_always_on_top(true);
        return;
    }
    let url = orb_url_from_env();
    let parsed = url
        .parse()
        .unwrap_or_else(|_| "http://127.0.0.1:8787/?view=orb".parse().unwrap());
    let x = env_f64("AMY_ORB_X", 28.0);
    let y = env_f64("AMY_ORB_Y", 120.0);
    let w = env_f64("AMY_ORB_W", 400.0);
    let h = env_f64("AMY_ORB_H", 440.0);
    let builder = WebviewWindowBuilder::new(app, "orb", WebviewUrl::External(parsed))
        .title("Amy")
        .inner_size(w, h)
        .position(x, y)
        .resizable(false)
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true);
    let _ = builder.build();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let args: Vec<String> = env::args().collect();
    for i in 0..args.len() {
        if args[i] == "--hud-url" {
            if let Some(u) = args.get(i + 1) {
                env::set_var("AMY_HUD_URL", u);
            }
        }
        if args[i] == "--chat-url" {
            // Back-compat: treat as full HUD URL
            if let Some(u) = args.get(i + 1) {
                env::set_var("AMY_HUD_URL", u);
            }
        }
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![amy_info])
        .setup(|app| {
            let show = MenuItem::with_id(app, "show", "Show launcher", true, None::<&str>)?;
            let hud = MenuItem::with_id(app, "hud", "Open Amy HUD", true, None::<&str>)?;
            let orb = MenuItem::with_id(app, "orb", "Open orb", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &hud, &orb, &quit])?;

            let _tray = TrayIconBuilder::new()
                .menu(&menu)
                .tooltip("Amy")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "quit" => app.exit(0),
                    "show" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "hud" => open_or_focus_hud(app),
                    "orb" => open_or_focus_orb(app),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        // Left-click opens full HUD on demand (not a captions pane).
                        open_or_focus_hud(tray.app_handle());
                    }
                })
                .build(app)?;

            // Production: do not auto-spawn captions/dock. Orb is owned by the Python host.
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" || window.label() == "orb" {
                    let _ = window.hide();
                    api.prevent_close();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Amy desktop");
}
