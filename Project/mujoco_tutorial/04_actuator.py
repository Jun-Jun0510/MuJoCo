"""
04_actuator.py
Section 4: Actuators — motor / position / velocity の 3 タイプ比較

学ぶこと:
  1) data.ctrl[i] で制御入力を与える
  2) <motor>: 直接トルク入力 (force = gear × ctrl)
  3) <position>: 位置サーボ (force = kp·(ctrl - qpos) - kv·qvel)
  4) <velocity>: 速度サーボ (force = kv·(ctrl - qvel))
  5) gear, ctrlrange, forcerange, kp, kv の意味
  6) W6 で BLDC トルク入力をどう設計するかの見通し

モデル: models/04_actuator.xml (ベース) を XML 文字列で書き換え
  - 水平アーム (hinge, L=0.3m, tip mass=1.0kg) + 重力
  - Experiment A: motor タイプ — 定トルクステップ
  - Experiment B: position タイプ — 目標角度 45° へのサーボ
  - Experiment C: velocity タイプ — 目標角速度 2 rad/s

出力: figures/mujoco_tutorial/04_actuator.png (3 実験を横並び比較)
"""

from pathlib import Path

import mujoco
import numpy as np
import matplotlib.pyplot as plt

_HERE = Path(__file__).resolve().parent
_FIG_DIR = _HERE.parent / "figures" / "mujoco_tutorial"
_FIG_DIR.mkdir(parents=True, exist_ok=True)

# アクチュエータなしの共通モデル (XML テンプレート)
_BASE_XML = """\
<mujoco model="actuator_demo">
  <option timestep="0.001" gravity="0 0 -9.81"/>
  <worldbody>
    <body name="pivot" pos="0 0 0.5">
      <geom type="box" size="0.02 0.02 0.02" rgba="0.3 0.3 0.3 1"
            contype="0" conaffinity="0"/>
      <body name="arm">
        <joint name="hinge" type="hinge" axis="0 1 0" damping="0.01"/>
        <geom type="capsule" fromto="0 0 0 0.3 0 0" size="0.015"
              rgba="0.4 0.6 0.8 1" mass="0.05"
              contype="0" conaffinity="0"/>
        <body name="tip" pos="0.3 0 0">
          <geom type="sphere" size="0.03" rgba="0.9 0.4 0.2 1"
                mass="1.0" contype="0" conaffinity="0"/>
        </body>
      </body>
    </body>
  </worldbody>
  <actuator>
    {actuator_xml}
  </actuator>
</mujoco>
"""


def run_sim(xml: str, ctrl_fn, T_sim: float = 3.0):
    """モデルを読み込み、ctrl_fn(t) で制御して時系列を返す。"""
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)

    # 初期条件: θ=0 (水平), ω=0
    data.qpos[0] = 0.0
    data.qvel[0] = 0.0
    mujoco.mj_forward(model, data)

    dt = model.opt.timestep
    N = int(T_sim / dt)

    t_log = np.zeros(N)
    th_log = np.zeros(N)
    om_log = np.zeros(N)
    ctrl_log = np.zeros(N)
    force_log = np.zeros(N)

    for k in range(N):
        t = data.time
        ctrl_val = ctrl_fn(t)
        data.ctrl[0] = ctrl_val

        mujoco.mj_step(model, data)

        t_log[k] = data.time
        th_log[k] = data.qpos[0]
        om_log[k] = data.qvel[0]
        ctrl_log[k] = ctrl_val
        # 実際にアクチュエータが出した力
        force_log[k] = data.actuator_force[0]

    return t_log, th_log, om_log, ctrl_log, force_log


def main():
    print("=" * 60)
    print("Section 4: Actuators (motor / position / velocity)")
    print("=" * 60)

    T_sim = 3.0

    # =================================================================
    # Experiment A: Motor (直接トルク)
    # =================================================================
    xml_motor = _BASE_XML.format(
        actuator_xml='<motor name="torque" joint="hinge" gear="1.0"'
                      ' ctrllimited="true" ctrlrange="-10 10"/>'
    )
    # t=0.5s でステップトルク 3 N·m (重力トルク mgL≈2.94 N·m をやや超える)
    def ctrl_motor(t):
        return 3.0 if t >= 0.5 else 0.0

    t_a, th_a, om_a, ctrl_a, f_a = run_sim(xml_motor, ctrl_motor, T_sim)

    # 重力トルクの理論値: τ_gravity = m·g·L·cos(θ) ≈ 2.94 cos(θ) at θ=0
    mg_L = 1.0 * 9.81 * 0.3
    print(f"\n  [A] Motor: step torque 3.0 N·m at t=0.5s")
    print(f"      gravity torque (θ=0) = m·g·L = {mg_L:.3f} N·m")
    print(f"      → applied > gravity → arm lifts slowly")
    print(f"      final θ = {np.degrees(th_a[-1]):+.1f}°, ω = {om_a[-1]:+.3f} rad/s")

    # =================================================================
    # Experiment B: Position servo (位置追従)
    # =================================================================
    xml_pos = _BASE_XML.format(
        actuator_xml='<position name="pos_servo" joint="hinge"'
                      ' kp="20" kv="4"'
                      ' ctrllimited="true" ctrlrange="-1.57 1.57"/>'
    )
    # 目標: t=0.5s で 45° (π/4)
    target_rad = np.pi / 4
    def ctrl_pos(t):
        return target_rad if t >= 0.5 else 0.0

    t_b, th_b, om_b, ctrl_b, f_b = run_sim(xml_pos, ctrl_pos, T_sim)

    print(f"\n  [B] Position servo: target=45° at t=0.5s, kp=20, kv=4")
    print(f"      final θ = {np.degrees(th_b[-1]):+.1f}°  "
          f"(target={np.degrees(target_rad):.0f}°)")
    print(f"      → 重力があるので定常偏差あり (kp が有限 → droop)")

    # =================================================================
    # Experiment C: Velocity servo (速度追従)
    # =================================================================
    xml_vel = _BASE_XML.format(
        actuator_xml='<velocity name="vel_servo" joint="hinge"'
                      ' kv="10"'
                      ' ctrllimited="true" ctrlrange="-5 5"'
                      ' forcelimited="true" forcerange="-10 10"/>'
    )
    # 目標: t=0.5s で ω=2 rad/s
    target_vel = 2.0
    def ctrl_vel(t):
        return target_vel if t >= 0.5 else 0.0

    t_c, th_c, om_c, ctrl_c, f_c = run_sim(xml_vel, ctrl_vel, T_sim)

    print(f"\n  [C] Velocity servo: target=2.0 rad/s at t=0.5s, kv=10")
    print(f"      final ω = {om_c[-1]:+.3f} rad/s  (target={target_vel:.1f})")
    print(f"      final θ = {np.degrees(th_c[-1]):+.1f}°")

    # =================================================================
    # プロット: 3 列 × 3 行 (θ / ω / actuator force)
    # =================================================================
    fig, axes = plt.subplots(3, 3, figsize=(14, 9), sharex="col")

    experiments = [
        ("A: Motor (τ=3 N·m step)", t_a, th_a, om_a, ctrl_a, f_a, "tab:blue"),
        ("B: Position (θ*=45°)", t_b, th_b, om_b, ctrl_b, f_b, "tab:green"),
        ("C: Velocity (ω*=2 rad/s)", t_c, th_c, om_c, ctrl_c, f_c, "tab:red"),
    ]

    for col, (title, t, th, om, ctrl, force, color) in enumerate(experiments):
        # 角度
        axes[0, col].plot(t, np.degrees(th), color=color)
        if col == 1:  # position: 目標線
            axes[0, col].axhline(45, color="gray", ls="--", lw=0.8, label="target")
            axes[0, col].legend(fontsize=8)
        axes[0, col].set_ylabel("θ [deg]" if col == 0 else "")
        axes[0, col].set_title(title)
        axes[0, col].grid(True, alpha=0.3)
        axes[0, col].axhline(0, color="gray", lw=0.3)

        # 角速度
        axes[1, col].plot(t, om, color=color)
        if col == 2:  # velocity: 目標線
            axes[1, col].axhline(target_vel, color="gray", ls="--", lw=0.8,
                                  label="target")
            axes[1, col].legend(fontsize=8)
        axes[1, col].set_ylabel("ω [rad/s]" if col == 0 else "")
        axes[1, col].grid(True, alpha=0.3)
        axes[1, col].axhline(0, color="gray", lw=0.3)

        # アクチュエータ出力 + ctrl
        axes[2, col].plot(t, force, color=color, label="force", alpha=0.8)
        axes[2, col].plot(t, ctrl, color="gray", ls="--", lw=0.8, label="ctrl")
        axes[2, col].set_ylabel("Force [N·m]" if col == 0 else "")
        axes[2, col].set_xlabel("Time [s]")
        axes[2, col].grid(True, alpha=0.3)
        axes[2, col].legend(fontsize=8)
        axes[2, col].axhline(0, color="gray", lw=0.3)

    fig.suptitle("Section 4: Actuator comparison — arm with gravity (m=1 kg, L=0.3 m)",
                 fontsize=12, y=0.98)
    plt.tight_layout()
    out = _FIG_DIR / "04_actuator.png"
    plt.savefig(out, dpi=120)
    print(f"\n  plot → {out}")

    # =================================================================
    # サマリー: 各アクチュエータの動作原理
    # =================================================================
    print("\n  --- Actuator comparison summary ---")
    print("  motor:    force = gear × ctrl         (直接トルク)")
    print("  position: force = kp·(ctrl-qpos) - kv·qvel  (位置サーボ)")
    print("  velocity: force = kv·(ctrl-qvel)      (速度サーボ)")
    print(f"\n  → W6 BLDC: <motor> タイプが最適 (Te を直接入力)")


if __name__ == "__main__":
    main()
