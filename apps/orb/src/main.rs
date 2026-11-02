//! Amy companion orb — presentation-only Bevy sidecar.
//! Protocol: newline-delimited JSON on stdin.

use bevy::prelude::*;
use serde::Deserialize;
use std::io::{self, BufRead, Write};
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::sync::Mutex;
use std::thread;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Resource)]
enum AmyState {
    #[default]
    Idle,
    Listening,
    Thinking,
    Speaking,
    NeedsApproval,
    Error,
}

impl AmyState {
    fn from_str(s: &str) -> Self {
        match s.to_ascii_lowercase().as_str() {
            "listening" => Self::Listening,
            "thinking" => Self::Thinking,
            "speaking" => Self::Speaking,
            "needs_approval" => Self::NeedsApproval,
            "error" => Self::Error,
            _ => Self::Idle,
        }
    }

    fn color(self) -> Color {
        match self {
            Self::Idle => Color::srgb(0.25, 0.45, 0.55),
            Self::Listening => Color::srgb(0.3, 0.72, 0.91),
            Self::Thinking => Color::srgb(0.91, 0.64, 0.29),
            Self::Speaking => Color::srgb(0.24, 0.81, 0.65),
            Self::NeedsApproval => Color::srgb(0.95, 0.55, 0.2),
            Self::Error => Color::srgb(0.88, 0.42, 0.42),
        }
    }

    fn pulse_speed(self) -> f32 {
        match self {
            Self::Idle => 0.6,
            Self::Listening => 2.2,
            Self::Thinking => 3.0,
            Self::Speaking => 4.0,
            Self::NeedsApproval => 1.4,
            Self::Error => 5.0,
        }
    }
}

#[derive(Deserialize)]
struct InMsg {
    #[serde(rename = "type")]
    kind: String,
    state: Option<String>,
}

#[derive(Resource)]
struct StateRx(Mutex<Receiver<AmyState>>);

#[derive(Component)]
struct Orb;

fn main() {
    let _ = writeln!(
        io::stdout(),
        "{}",
        serde_json::json!({"type":"renderer_ready","name":"Amy"})
    );

    let (tx, rx) = mpsc::channel::<AmyState>();
    thread::spawn(move || {
        let stdin = io::stdin();
        for line in stdin.lock().lines().flatten() {
            let line = line.trim().to_string();
            if line.is_empty() {
                continue;
            }
            if let Ok(msg) = serde_json::from_str::<InMsg>(&line) {
                if msg.kind == "set_state" {
                    if let Some(s) = msg.state {
                        let _ = tx.send(AmyState::from_str(&s));
                    }
                } else if msg.kind == "open_hud" {
                    let _ = writeln!(
                        io::stdout(),
                        "{}",
                        serde_json::json!({"type":"open_hud","name":"Amy"})
                    );
                }
            }
        }
    });

    App::new()
        .insert_resource(ClearColor(Color::srgba(0.02, 0.04, 0.06, 0.85)))
        .insert_resource(AmyState::Idle)
        .insert_resource(StateRx(Mutex::new(rx)))
        .add_plugins(DefaultPlugins.set(WindowPlugin {
            primary_window: Some(Window {
                title: "Amy".into(),
                resolution: (280., 280.).into(),
                transparent: true,
                decorations: false,
                resizable: false,
                ..default()
            }),
            ..default()
        }))
        .add_systems(Startup, setup)
        .add_systems(Update, (poll_state, animate_orb))
        .run();
}

fn setup(
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
) {
    commands.spawn((
        Mesh3d(meshes.add(Sphere::new(0.85).mesh().uv(64, 32))),
        MeshMaterial3d(materials.add(StandardMaterial {
            base_color: AmyState::Idle.color(),
            emissive: LinearRgba::from(AmyState::Idle.color()) * 2.0,
            perceptual_roughness: 0.35,
            metallic: 0.1,
            alpha_mode: AlphaMode::Blend,
            ..default()
        })),
        Transform::from_xyz(0.0, 0.0, 0.0),
        Orb,
    ));
    commands.spawn((
        PointLight {
            shadows_enabled: false,
            intensity: 800_000.0,
            range: 20.0,
            ..default()
        },
        Transform::from_xyz(2.0, 3.0, 4.0),
    ));
    commands.spawn((
        Camera3d::default(),
        Transform::from_xyz(0.0, 0.0, 4.0).looking_at(Vec3::ZERO, Vec3::Y),
    ));
}

fn poll_state(rx: Res<StateRx>, mut state: ResMut<AmyState>) {
    let Ok(guard) = rx.0.lock() else {
        return;
    };
    loop {
        match guard.try_recv() {
            Ok(s) => *state = s,
            Err(TryRecvError::Empty) => break,
            Err(TryRecvError::Disconnected) => break,
        }
    }
}

fn animate_orb(
    time: Res<Time>,
    state: Res<AmyState>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    mut q: Query<(&mut Transform, &MeshMaterial3d<StandardMaterial>), With<Orb>>,
) {
    let t = time.elapsed_secs();
    let speed = state.pulse_speed();
    let scale = 1.0 + 0.06 * (t * speed).sin();
    let color = state.color();
    for (mut xf, mat_h) in &mut q {
        xf.scale = Vec3::splat(scale);
        xf.rotate_y(0.25 * time.delta_secs() * speed);
        if let Some(mat) = materials.get_mut(mat_h) {
            mat.base_color = color;
            mat.emissive = LinearRgba::from(color) * (1.5 + 0.8 * (t * speed).sin().abs());
        }
    }
}
