"""
plot_prefilter_compare.py
W4 追加検証: 速度ループ PI の「プリフィルタ有無」でステップ応答を比較する。

理論:
  PI の閉ループ伝達関数には分子に零点 s = -Ki/Kp が現れ、
  ζ=0.707 設計でも実応答はオーバーシュートが大きくなる。
  プリフィルタ F(s) = 1/(1 + τf·s), τf = Kp/Ki を指令側に入れると
  零点が相殺され、純粋な2次標準形 ωn²/(s²+2ζωn·s+ωn²) となる。
  理論 OS: ~4.3% @ ζ=0.707
"""

import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT / "src"))
_FIG_DIR = _PROJECT / "figures"

import numpy as np
import matplotlib.pyplot as plt

from pi_controller import _simulate_speed_loop, SpeedPIController
from config import motor_params


def _metrics(res: dict, omega_ref: float):
    t = res["t"]
    wm = res["wm"]
    peak = wm.max()
    overshoot = (peak - omega_ref) / omega_ref * 100.0
    band = 0.02 * abs(omega_ref)
    inside = np.abs(wm - omega_ref) <= band
    idx_settle = None
    for i in range(len(inside)):
        if inside[i] and np.all(inside[i:]):
            idx_settle = i
            break
    t_settle = t[idx_settle] if idx_settle is not None else np.nan
    return dict(peak=peak, overshoot=overshoot, t_settle=t_settle)


def main():
    omega_ref = 50.0
    T_sim = 0.3

    # --- ケース A: プリフィルタなし (= 前回 W4-3) ---
    res_off = _simulate_speed_loop(
        omega_ref=omega_ref, T_sim=T_sim, dt=1.0e-5, use_prefilter=False
    )
    m_off = _metrics(res_off, omega_ref)

    # --- ケース B: プリフィルタあり ---
    res_on = _simulate_speed_loop(
        omega_ref=omega_ref, T_sim=T_sim, dt=1.0e-5, use_prefilter=True
    )
    m_on = _metrics(res_on, omega_ref)

    # --- 指標表 ---
    cfg = motor_params
    asr = SpeedPIController(cfg, use_prefilter=True)
    print("===========================================================")
    print("Prefilter Comparison: speed step 0 → 50 rad/s (no load)")
    print("===========================================================")
    print(f"  Kp_w = {asr.Kp:.4f},  Ki_w = {asr.Ki:.4f}")
    print(f"  τ_f  = Kp/Ki = {asr.tau_f*1e3:.2f} ms  (prefilter time constant)")
    print("───────────────────────────────────────────────────────────")
    print(f"  {'':22s}  {'w/o prefilter':>15s}  {'w/ prefilter':>15s}")
    print(f"  {'peak speed [rad/s]':22s}  {m_off['peak']:15.3f}  {m_on['peak']:15.3f}")
    print(f"  {'overshoot [%]':22s}  {m_off['overshoot']:+15.2f}  {m_on['overshoot']:+15.2f}")
    print(f"  {'t_settle ±2% [ms]':22s}  "
          f"{m_off['t_settle']*1e3:15.1f}  {m_on['t_settle']*1e3:15.1f}")
    print(f"  (theoretical OS @ ζ=0.707: pure 2nd order ≈ 4.32%)")
    print("===========================================================")

    # --- プロット ---
    t = res_off["t"] * 1e3
    fig, axes = plt.subplots(4, 1, figsize=(9, 10), sharex=True)

    # (1) 速度応答
    axes[0].plot(t, res_off["wm"], label="$\\omega_m$ (w/o PF)",
                 color="tab:red", linewidth=1.5)
    axes[0].plot(t, res_on["wm"], label="$\\omega_m$ (w/ PF)",
                 color="tab:green", linewidth=1.5)
    axes[0].plot(t, res_on["wref_f"], "--", label="$\\omega_m^*$ filtered",
                 color="tab:blue", alpha=0.7)
    axes[0].axhline(omega_ref, color="gray", linestyle=":", label="$\\omega_m^*$")
    axes[0].set_ylabel("Speed [rad/s]")
    axes[0].set_title(
        "W4 extra: Prefilter Comparison  "
        "(Speed Step 0 → 50 rad/s, no load)"
    )
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    # (2) 追従誤差
    axes[1].plot(t, res_off["wm"] - omega_ref,
                 label="w/o prefilter", color="tab:red")
    axes[1].plot(t, res_on["wm"] - omega_ref,
                 label="w/ prefilter",  color="tab:green")
    axes[1].axhline(+0.02 * omega_ref, color="gray", linestyle=":", label="±2%")
    axes[1].axhline(-0.02 * omega_ref, color="gray", linestyle=":")
    axes[1].set_ylabel("$\\omega_m - \\omega_m^*$ [rad/s]")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")

    # (3) iq (内側ループへの指令)
    axes[2].plot(t, res_off["iq"], label="$i_q$ (w/o PF)", color="tab:red")
    axes[2].plot(t, res_on["iq"],  label="$i_q$ (w/ PF)",  color="tab:green")
    axes[2].axhline(+motor_params.I_max, color="gray", linestyle=":", label="±I_max")
    axes[2].axhline(-motor_params.I_max, color="gray", linestyle=":")
    axes[2].set_ylabel("$i_q$ [A]")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc="best")

    # (4) 電磁トルク
    axes[3].plot(t, res_off["Te"], label="w/o PF", color="tab:red")
    axes[3].plot(t, res_on["Te"],  label="w/ PF",  color="tab:green")
    axes[3].set_ylabel("$T_e$ [N·m]")
    axes[3].set_xlabel("Time [ms]")
    axes[3].grid(True, alpha=0.3)
    axes[3].legend(loc="best")

    plt.tight_layout()
    out_path = str(_FIG_DIR / "prefilter_compare.png")
    plt.savefig(out_path, dpi=120)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
