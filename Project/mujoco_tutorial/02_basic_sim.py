"""
02_basic_sim.py
Section 2: Basic simulation — mj_step ループと時系列ログ

学ぶこと:
  1) `mj_step` ループで物理積分を回す
  2) `data.qpos`, `data.qvel`, `data.time` から状態をログする
  3) 定期的に `Renderer` でフレームを撮り、PIL で GIF 保存
     (MP4 にしたい場合は `brew install ffmpeg` 後 mediapy に切替可能)
  4) 解析解 (線形化単振子) との比較で数値積分の妥当性を確認

モデル: models/02_pendulum.xml  (hinge joint, nq=1, nv=1)
初期条件: θ0 = π/4 (45°),  θ'0 = 0
"""

from pathlib import Path

import mujoco
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

_HERE = Path(__file__).resolve().parent
_MODEL = _HERE / "models" / "02_pendulum.xml"
_FIG_DIR = _HERE.parent / "figures" / "mujoco_tutorial"
_FIG_DIR.mkdir(parents=True, exist_ok=True)


def main():
    # -----------------------------------------------------------------
    # モデル読み込み & 初期条件設定
    # -----------------------------------------------------------------
    model = mujoco.MjModel.from_xml_path(str(_MODEL))
    data = mujoco.MjData(model)

    # hinge joint は 1 自由度 → qpos[0] が角度 [rad], qvel[0] が角速度 [rad/s]
    theta0 = np.pi / 4.0  # 45 deg
    data.qpos[0] = theta0
    data.qvel[0] = 0.0
    mujoco.mj_forward(model, data)

    # 単振子の支点-重心距離 L (tip 位置から出す)
    tip_xpos = data.body("tip").xpos.copy()
    pivot_xpos = data.body("pivot").xpos.copy()
    L = float(np.linalg.norm(tip_xpos - pivot_xpos))  # ≈ 0.5 m
    g = float(-model.opt.gravity[2])
    omega_n = np.sqrt(g / L)                          # 線形近似の固有角周波数
    T_period = 2.0 * np.pi / omega_n

    print("=" * 60)
    print("Section 2: Basic simulation (free pendulum)")
    print("=" * 60)
    print(f"  timestep   = {model.opt.timestep*1e3:.1f} ms")
    print(f"  nq={model.nq}, nv={model.nv}   (1-DoF hinge)")
    print(f"  L (pivot→tip) = {L:.3f} m")
    print(f"  g  = {g:.3f} m/s²")
    print(f"  ω_n (linearized) = {omega_n:.3f} rad/s")
    print(f"  T (linearized)   = {T_period:.3f} s")
    print(f"  initial θ  = {np.degrees(theta0):.1f} deg")

    # -----------------------------------------------------------------
    # シミュレーション + フレーム収集
    # -----------------------------------------------------------------
    T_sim = 4.0                       # 4 秒回す (≈ 3 周期)
    dt = model.opt.timestep
    N = int(T_sim / dt)

    fps = 60
    render_every = int(round(1.0 / (fps * dt)))   # 1 フレームごとに何ステップ進むか
    frames: list[np.ndarray] = []

    # ログバッファ
    t_log = np.zeros(N)
    th_log = np.zeros(N)
    om_log = np.zeros(N)

    with mujoco.Renderer(model, height=360, width=480) as renderer:
        for k in range(N):
            mujoco.mj_step(model, data)

            t_log[k]  = data.time
            th_log[k] = data.qpos[0]
            om_log[k] = data.qvel[0]

            # フレームを渡す (動画用)
            if k % render_every == 0:
                renderer.update_scene(data, camera=-1)
                frames.append(renderer.render())

    print(f"  steps      = {N}")
    print(f"  frames     = {len(frames)}  ({fps} fps)")
    print(f"  final t    = {data.time:.3f} s")
    print(f"  final θ    = {np.degrees(data.qpos[0]):+.2f} deg")

    # -----------------------------------------------------------------
    # 動画保存 (GIF, PIL 経由。ffmpeg 不要)
    # -----------------------------------------------------------------
    gif_path = _FIG_DIR / "02_pendulum.gif"
    pil_frames = [Image.fromarray(f) for f in frames]
    pil_frames[0].save(
        str(gif_path),
        save_all=True,
        append_images=pil_frames[1:],
        duration=int(1000.0 / fps),  # ms per frame
        loop=0,
        optimize=False,
    )
    print(f"  video  → {gif_path}  ({len(pil_frames)} frames, {fps} fps)")

    # -----------------------------------------------------------------
    # 解析解 (線形近似: θ(t) = θ0 · cos(ω_n · t))
    # -----------------------------------------------------------------
    th_lin = theta0 * np.cos(omega_n * t_log)

    # -----------------------------------------------------------------
    # 時系列プロット
    # -----------------------------------------------------------------
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)

    # (1) 角度
    axes[0].plot(t_log, np.degrees(th_log), color="tab:blue",
                 label="MuJoCo (full nonlinear)")
    axes[0].plot(t_log, np.degrees(th_lin), "--", color="tab:orange",
                 label="linearized $\\theta_0 \\cos(\\omega_n t)$")
    axes[0].axhline(0, color="gray", linewidth=0.5)
    axes[0].set_ylabel("$\\theta$ [deg]")
    axes[0].set_title(f"Section 2: Free pendulum ($\\theta_0$ = 45°, L = {L:.2f} m)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    # (2) 角速度
    axes[1].plot(t_log, om_log, color="tab:green")
    axes[1].axhline(0, color="gray", linewidth=0.5)
    axes[1].set_ylabel("$\\dot\\theta$ [rad/s]")
    axes[1].grid(True, alpha=0.3)

    # (3) エネルギー (運動 + ポテンシャル) - damping 0.02 で少し減衰するはず
    I = 0.3 * L ** 2                             # tip mass のみで近似 (arm 質量は小さい)
    KE = 0.5 * I * om_log ** 2
    PE = 0.3 * g * L * (1.0 - np.cos(th_log))    # 支点を基準
    E = KE + PE
    axes[2].plot(t_log, KE, label="KE", color="tab:red", alpha=0.7)
    axes[2].plot(t_log, PE, label="PE", color="tab:blue", alpha=0.7)
    axes[2].plot(t_log, E,  label="Total", color="black", linewidth=1.3)
    axes[2].set_ylabel("Energy [J]")
    axes[2].set_xlabel("Time [s]")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc="best")

    plt.tight_layout()
    out = _FIG_DIR / "02_basic_sim.png"
    plt.savefig(out, dpi=120)
    print(f"  plot   → {out}")

    # -----------------------------------------------------------------
    # 数値チェック: エネルギー散逸量 (damping 0.001 + RK4 の精度)
    # -----------------------------------------------------------------
    dE_rel = (E[-1] - E[0]) / E[0] * 100
    print(f"\n  energy: E(0)={E[0]:.4f} J → E(T)={E[-1]:.4f} J  ({dE_rel:+.2f}%)")
    print(f"  (damping=0.001 の hinge joint 設定 + RK4 積分による微減衰)")


if __name__ == "__main__":
    main()
