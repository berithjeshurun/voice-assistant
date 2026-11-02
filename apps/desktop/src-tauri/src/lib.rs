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
        "role": "desktop-hud",
        "default_url": "http://127.0.0.1:8787"
    })
}

fn chat_url_from_env() -> String {
    if let Ok(u) = env::var("AMY_CHAT_URL") {
        if !u.trim().is_empty() {
            return u;
        }
    }
    let token = env::var("AMY_TOKEN").unwrap_or_default();
    let host = env::var("AMY_HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let port = env::var("AMY_PORT").unwrap_or_else(|_| "8787".into());
    if token.is_empty() {
        format!("http://{host}:{port}/?view=chat")
    } else {
        format!("http://{host}:{port}/?view=chat&token={token}")
    }
}

fn dock_url_from_env() -> String {
    if let Ok(u) = env::var("AMY_DOCK_URL") {
        if !u.trim().is_empty() {
            return u;
        }
    }
    chat_url_from_env().replace("view=chat", "view=dock")
}

fn env_f64(key: &str, default: f64) -> f64 {
    env::var(key)
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .unwrap_or(default)
}

fn open_or_focus_chat(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("chat") {
        let _ = w.show();
        let _ = w.set_focus();
        return;
    }
    let url = chat_url_from_env();
    let parsed = url
        .parse()
        .unwrap_or_else(|_| "http://127.0.0.1:8787/?view=chat".parse().unwrap());
    let x = env_f64("AMY_CHAT_X", 1400.0);
    let y = env_f64("AMY_CHAT_Y", 36.0);
    let w = env_f64("AMY_CHAT_W", 440.0);
    let h = env_f64("AMY_CHAT_H", 760.0);
    let builder = WebviewWindowBuilder::new(app, "chat", WebviewUrl::External(parsed))
        .title("Amy Captions")
        .inner_size(w, h)
        .position(x, y)
        .resizable(true);
    let _ = builder.build();
}

fn open_or_focus_dock(app: &tauri::AppHandle) {
    if env::var("AMY_DOCK_URL").ok().filter(|s| !s.trim().is_empty()).is_none()
        && env::var("AMY_DOCK").unwrap_or_else(|_| "1".into()) == "0"
    {
        return;
    }
    if let Some(w) = app.get_webview_window("dock") {
        let _ = w.show();
        return;
    }
    let url = dock_url_from_env();
    let parsed = url
        .parse()
        .unwrap_or_else(|_| "http://127.0.0.1:8787/?view=dock".parse().unwrap());
    let x = env_f64("AMY_DOCK_X", 16.0);
    let y = env_f64("AMY_DOCK_Y", 980.0);
    let w = env_f64("AMY_DOCK_W", 1880.0);
    let h = env_f64("AMY_DOCK_H", 72.0);
    let builder = WebviewWindowBuilder::new(app, "dock", WebviewUrl::External(parsed))
        .title("Amy Dock")
        .inner_size(w, h)
        .position(x, y)
        .resizable(false)
        .decorations(false)
        .always_on_top(true);
    let _ = builder.build();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Optional CLI: amy-desktop --chat-url http://...
    let args: Vec<String> = env::args().collect();
    for i in 0..args.len() {
        if args[i] == "--chat-url" {
            if let Some(u) = args.get(i + 1) {
                env::set_var("AMY_CHAT_URL", u);
            }
        }
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![amy_info])
        .setup(|app| {
            let show = MenuItem::with_id(app, "show", "Show Amy", true, None::<&str>)?;
            let chat = MenuItem::with_id(app, "chat", "Captions chat", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &chat, &quit])?;

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
                    "chat" => {
                        open_or_focus_chat(app);
                        open_or_focus_dock(app);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        open_or_focus_chat(tray.app_handle());
                        open_or_focus_dock(tray.app_handle());
                    }
                })
                .build(app)?;

            // Captions (right) + dock (bottom) on launch
            open_or_focus_chat(app.handle());
            open_or_focus_dock(app.handle());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" || window.label() == "dock" {
                    let _ = window.hide();
                    api.prevent_close();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Amy desktop");
}
