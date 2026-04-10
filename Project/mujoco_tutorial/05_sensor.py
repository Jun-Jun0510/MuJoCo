"""
05_sensor.py
Section 5: Sensors — センサ定義・data.sensordata の読み出し

学ぶこと:
  1) <sensor> 要素のタイプ: jointpos, jointvel, actuatorfrc, framepos, framelinvel
  2) data.sensordata の構造 (フラットな 1D 配列, アドレス管理)
  3) model.sensor_adr / model.sensor_dim で各センサのオフセット・次元を取得
  4) センサ名 → data.sensor('name').data で直接アクセス
  5) Gymnasium Env の observation 設計への応用

モデル: models/05_sensor.xml (水平アーム + motor + 5 種センサ)
出力: figures/mujoco_tutorial/05_sensor.png (センサ値の時系列)
"""

from pathlib import Path

import mujoco
import numpy as np
import matplotlib.pyplot as plt

_HERE = Path(__file__).resolve().parent
_MODEL = _HERE / "models" / "05_sensor.xml"
_FIG_DIR = _HERE.parent / "figures" / "mujoco_tutorial"
_FIG_DIR.mkdir(parents=True, exist_ok=True)


def main():
    model = mujoco.MjModel.from_xml_path(str(_MODEL))
    data = mujoco.MjData(model)

    # 初期条件: θ=π/6 (30°)
    theta0 = np.pi / 6
    data.qpos[0] = theta0
    data.qvel[0] = 0.0
    mujoco.mj_forward(model, data)

    print("=" * 60)
    print("Section 5: Sensors")
    print("=" * 60)

    # -----------------------------------------------------------------
    # センサ構造の解析
    # -----------------------------------------------------------------
    print(f"\n  model.nsensor = {model.nsensor}")
    print(f"  model.nsensordata = {model.nsensordata}")
    print(f"  data.sensordata.shape = {data.sensordata.shape}")
    print()

    for i in range(model.nsensor):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_SENSOR, i)
        adr = model.sensor_adr[i]
        dim = model.sensor_dim[i]
        print(f"  sensor[{i}] '{name}':  adr={adr}, dim={dim}  "
              f"→ sensordata[{adr}:{adr+dim}]")

    # 直接アクセス API の確認
    print(f"\n  data.sensor('s_angle').data    = {data.sensor('s_angle').data}")
    print(f"  data.sensor('s_tip_pos').data  = {data.sensor('s_tip_pos').data}")

    # -----------------------------------------------------------------
    # シミュレーション: サイン波トルクを入力
    # -----------------------------------------------------------------
    T_sim = 4.0
    dt = model.opt.timestep
    N = int(T_sim / dt)

    t_log = np.zeros(N)
    angle_log = np.zeros(N)
    vel_log = np.zeros(N)
    torque_log = np.zeros(N)
    tip_x_log = np.zeros(N)
    tip_z_log = np.zeros(N)
    tip_vx_log = np.zeros(N)
    tip_vz_log = np.zeros(N)
    ctrl_log = np.zeros(N)

    # サイン波トルク: 振幅 4 N·m, 周波数 1 Hz
    A_torque = 4.0
    freq = 1.0

    for k in range(N):
        t = data.time
        ctrl = A_torque * np.sin(2 * np.pi * freq * t)
        data.ctrl[0] = ctrl

        mujoco.mj_step(model, data)

        t_log[k] = data.time

        # --- センサ経由で読む ---
        angle_log[k] = data.sensor("s_angle").data[0]
        vel_log[k] = data.sensor("s_velocity").data[0]
        torque_log[k] = data.sensor("s_torque").data[0]

        tip_pos = data.sensor("s_tip_pos").data
        tip_x_log[k] = tip_pos[0]
        tip_z_log[k] = tip_pos[2]

        tip_vel = data.sensor("s_tip_vel").data
        tip_vx_log[k] = tip_vel[0]
        tip_vz_log[k] = tip_vel[2]

        ctrl_log[k] = ctrl

    # 直接 qpos/qvel と比較 (一致確認)
    angle_direct = data.qpos[0]
    angle_sensor = data.sensor("s_angle").data[0]
    print(f"\n  --- Consistency check (final step) ---")
    print(f"  qpos[0]         = {angle_direct:.6f}")
    print(f"  sensor('angle') = {angle_sensor:.6f}")
    print(f"  → match: {np.isclose(angle_direct, angle_sensor)}")

    print(f"\n  final θ = {np.degrees(angle_log[-1]):+.1f}°")
    print(f"  final ω = {vel_log[-1]:+.3f} rad/s")

    # -----------------------------------------------------------------
    # プロット: 5 段
    # -----------------------------------------------------------------
    fig, axes = plt.subplots(5, 1, figsize=(10, 12), sharex=True)

    # (1) 角度 (jointpos)
    axes[0].plot(t_log, np.degrees(angle_log), color="tab:blue")
    axes[0].set_ylabel("θ [deg]\n(jointpos)")
    axes[0].set_title("Section 5: Sensors — sinusoidal torque (A=4 N·m, f=1 Hz)")
    axes[0].grid(True, alpha=0.3)
    axes[0].axhline(0, color="gray", lw=0.3)

    # (2) 角速度 (jointvel)
    axes[1].plot(t_log, vel_log, color="tab:green")
    axes[1].set_ylabel("ω [rad/s]\n(jointvel)")
    axes[1].grid(True, alpha=0.3)
    axes[1].axhline(0, color="gray", lw=0.3)

    # (3) アクチュエータ力 (actuatorfrc) + ctrl
    axes[2].plot(t_log, torque_log, color="tab:orange", label="actuatorfrc")
    axes[2].plot(t_log, ctrl_log, "--", color="gray", lw=0.8, label="ctrl input")
    axes[2].set_ylabel("Torque [N·m]\n(actuatorfrc)")
    axes[2].legend(fontsize=9)
    axes[2].grid(True, alpha=0.3)
    axes[2].axhline(0, color="gray", lw=0.3)

    # (4) 先端位置 (framepos) — x, z
    axes[3].plot(t_log, tip_x_log, color="tab:red", label="x")
    axes[3].plot(t_log, tip_z_log, color="tab:purple", label="z")
    axes[3].set_ylabel("Tip pos [m]\n(framepos)")
    axes[3].legend(fontsize=9)
    axes[3].grid(True, alpha=0.3)

    # (5) 先端速度 (framelinvel) — vx, vz
    axes[4].plot(t_log, tip_vx_log, color="tab:red", label="vx")
    axes[4].plot(t_log, tip_vz_log, color="tab:purple", label="vz")
    axes[4].set_ylabel("Tip vel [m/s]\n(framelinvel)")
    axes[4].set_xlabel("Time [s]")
    axes[4].legend(fontsize=9)
    axes[4].grid(True, alpha=0.3)

    plt.tight_layout()
    out = _FIG_DIR / "05_sensor.png"
    plt.savefig(out, dpi=120)
    print(f"\n  plot → {out}")

    # -----------------------------------------------------------------
    # sensordata の構造ダンプ (最終フレーム)
    # -----------------------------------------------------------------
    print(f"\n  --- Full sensordata dump (t={data.time:.3f}s) ---")
    print(f"  {data.sensordata}")
    print(f"  layout: [angle(1), velocity(1), torque(1), tip_pos(3), tip_vel(3)]")
    print(f"  total dim = {model.nsensordata}")


if __name__ == "__main__":
    main()
