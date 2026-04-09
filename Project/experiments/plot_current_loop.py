"""
plot_current_loop.py
W4-1: 電流ループ PI の閉ループ応答を可視化する。

条件: id_ref = 0, iq_ref = 20 [A] のステップ入力、無負荷。
"""

import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT / "src"))
_FIG_DIR = _PROJECT / "figures"

import numpy as np
import matplotlib.pyplot as plt

from pi_controller import _simulate_current_loop
from config import motor_params


def main():
    id_ref, iq_ref = 0.0, 20.0
    T_sim = 0.1  # 100 ms

    t, id_, iq_, wm, vd, vq, Te = _simulate_current_loop(
        id_ref=id_ref, iq_ref=iq_ref,
        T_sim=T_sim, dt=1.0e-5, dt_ctrl=1.0e-4,
    )
    rpm = wm * 60.0 / (2.0 * np.pi)

    fig, axes = plt.subplots(5, 1, figsize=(9, 12), sharex=True)

    # --- 1) dq 軸電流 & 指令 ---
    axes[0].plot(t * 1e3, iq_, label="$i_q$", color="tab:red")
    axes[0].plot(t * 1e3, id_, label="$i_d$", color="tab:blue")
    axes[0].axhline(iq_ref, color="tab:red", linestyle="--", alpha=0.5, label="$i_q^*$")
    axes[0].axhline(id_ref, color="tab:blue", linestyle="--", alpha=0.5, label="$i_d^*$")
    axes[0].set_ylabel("Current [A]")
    axes[0].set_title(
        "W4-1: Current Loop PI (ACR)  "
        f"$i_d^*$=0, $i_q^*$={iq_ref}A step, no load"
    )
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best", ncol=2)

    # --- 2) 電流誤差 (ズームアップ) ---
    axes[1].plot(t * 1e3, iq_ - iq_ref, label="$i_q - i_q^*$", color="tab:red")
    axes[1].plot(t * 1e3, id_ - id_ref, label="$i_d - i_d^*$", color="tab:blue")
    axes[1].axhline(+0.02 * iq_ref, color="gray", linestyle=":", label="±2% band")
    axes[1].axhline(-0.02 * iq_ref, color="gray", linestyle=":")
    axes[1].set_ylabel("Current error [A]")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")

    # --- 3) 制御器出力電圧 (vd, vq) ---
    v_lim = motor_params.Vdc / np.sqrt(3.0)
    axes[2].plot(t * 1e3, vq, label="$v_q$ (cmd)", color="tab:red")
    axes[2].plot(t * 1e3, vd, label="$v_d$ (cmd)", color="tab:blue")
    axes[2].axhline(+v_lim, color="gray", linestyle=":", label="±V_limit")
    axes[2].axhline(-v_lim, color="gray", linestyle=":")
    axes[2].set_ylabel("Control voltage [V]")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc="best")

    # --- 4) 電磁トルク ---
    axes[3].plot(t * 1e3, Te, color="tab:purple")
    axes[3].set_ylabel("$T_e$ [N·m]")
    axes[3].grid(True, alpha=0.3)

    # --- 5) 回転数 (rpm) ---
    axes[4].plot(t * 1e3, rpm, color="tab:orange")
    axes[4].set_ylabel("Speed [rpm]")
    axes[4].set_xlabel("Time [ms]")
    axes[4].grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = str(_FIG_DIR / "current_loop_response.png")
    plt.savefig(out_path, dpi=120)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
