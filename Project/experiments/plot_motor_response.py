"""
plot_motor_response.py
motor_model.py (RK4真値) の開ループステップ応答を可視化する。

開ループ条件:
    vd = 0 V,  vq = 30 V  (ステップ印加)
    無負荷 (TL = 0, D = 0)
"""

import sys
from pathlib import Path

# src/ を import path に追加し、figures/ の出力先を決定
_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT / "src"))
_FIG_DIR = _PROJECT / "figures"

import numpy as np
import matplotlib.pyplot as plt

from motor_model import BLDCMotor
from config import motor_params


def simulate_open_loop(
    vd: float = 0.0,
    vq: float = 30.0,
    dt: float = 1.0e-5,     # 10 μs
    T: float = 0.1,         # 100 ms
):
    motor = BLDCMotor()
    N = int(T / dt)

    t     = np.zeros(N)
    log_id = np.zeros(N)
    log_iq = np.zeros(N)
    log_wm = np.zeros(N)
    log_Te = np.zeros(N)

    for k in range(N):
        motor.step_rk4(vd, vq, dt)
        t[k]     = (k + 1) * dt
        log_id[k] = motor.id
        log_iq[k] = motor.iq
        log_wm[k] = motor.omega_m
        log_Te[k] = motor.electric_torque(motor.id, motor.iq)

    return t, log_id, log_iq, log_wm, log_Te


def main():
    vd_cmd, vq_cmd = 0.0, 30.0
    T_sim = 0.2  # 200 ms (J を 10 倍にしたので観測時間も伸ばす)

    t, id_, iq_, wm, Te = simulate_open_loop(vd=vd_cmd, vq=vq_cmd, dt=1.0e-5, T=T_sim)
    rpm = wm * 60.0 / (2.0 * np.pi)

    # ステップ電圧波形を可視化用に作成 (t<0 はゼロ、t>=0 で指令値)
    pre_pad = 10
    t_plot = np.concatenate([np.linspace(-0.02, 0.0, pre_pad, endpoint=False), t])
    vd_plot = np.concatenate([np.zeros(pre_pad), np.full_like(t, vd_cmd)])
    vq_plot = np.concatenate([np.zeros(pre_pad), np.full_like(t, vq_cmd)])

    fig, axes = plt.subplots(5, 1, figsize=(9, 12), sharex=True)

    # --- 0) 入力: d/q 軸電圧 (ステップ) ---
    axes[0].step(t_plot * 1e3, vd_plot, where="post", label="$v_d$ (cmd)", color="tab:blue")
    axes[0].step(t_plot * 1e3, vq_plot, where="post", label="$v_q$ (cmd)", color="tab:red")
    axes[0].set_ylabel("Input Voltage [V]")
    axes[0].set_title(
        "BLDC Open-Loop Step Response  "
        "($v_d$=0 V, $v_q$=30 V step, no load, RK4 dt=10 μs, J=7e-3)"
    )
    axes[0].set_ylim(-5, 40)
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    # --- 1) d/q 軸電流 ---
    axes[1].plot(t * 1e3, id_, label="$i_d$", color="tab:blue")
    axes[1].plot(t * 1e3, iq_, label="$i_q$", color="tab:red")
    axes[1].axhline(motor_params.I_max, color="gray", linestyle=":", label="I_max")
    axes[1].axhline(-motor_params.I_max, color="gray", linestyle=":")
    axes[1].set_ylabel("Current [A]")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")

    # --- 2) 電磁トルク ---
    axes[2].plot(t * 1e3, Te, color="tab:purple")
    axes[2].set_ylabel("Electric Torque $T_e$ [N·m]")
    axes[2].grid(True, alpha=0.3)

    # --- 3) 機械角速度 ---
    axes[3].plot(t * 1e3, wm, color="tab:green")
    axes[3].set_ylabel("Mech. speed $\\omega_m$ [rad/s]")
    axes[3].grid(True, alpha=0.3)

    # --- 4) 回転数 (rpm) ---
    axes[4].plot(t * 1e3, rpm, color="tab:orange")
    axes[4].set_ylabel("Speed [rpm]")
    axes[4].set_xlabel("Time [ms]")
    axes[4].grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = str(_FIG_DIR / "motor_open_loop_response.png")
    plt.savefig(out_path, dpi=120)
    print(f"Saved: {out_path}")

    # 最終・ピーク統計を表示
    print("\n--- Response statistics ---")
    print(f"  peak  id = {id_.max():+.3f} A  (at t = {t[id_.argmax()]*1e3:.2f} ms)")
    print(f"  peak  iq = {iq_.max():+.3f} A  (at t = {t[iq_.argmax()]*1e3:.2f} ms)")
    print(f"  peak  ωm = {wm.max():+.2f} rad/s "
          f"({rpm.max():.1f} rpm)  at t = {t[wm.argmax()]*1e3:.2f} ms")
    print(f"  peak  Te = {Te.max():+.3f} N·m")
    print(f"  final id = {id_[-1]:+.3f} A")
    print(f"  final iq = {iq_[-1]:+.3f} A")
    print(f"  final ωm = {wm[-1]:+.2f} rad/s ({rpm[-1]:.1f} rpm)")


if __name__ == "__main__":
    main()
