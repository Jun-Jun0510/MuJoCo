"""
plot_speed_loop.py
W4-3: ASR + ACR カスケード制御の閉ループ応答を可視化する。

試験シナリオ:
  ① 速度ステップ応答 (無負荷): 0 → 50 rad/s (~478 rpm) ステップ指令
  ② 負荷外乱応答        : 定常後 t=0.2s に TL=5 N·m 印加、ドロップ & 復帰
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


# ---------------------------------------------------------------------------
# 共通プロットルーチン
# ---------------------------------------------------------------------------
def _plot_result(res: dict, title: str, save_path: str):
    t = res["t"] * 1e3  # ms
    rpm = res["wm"] * 60.0 / (2.0 * np.pi)
    rpm_ref = res["wref"] * 60.0 / (2.0 * np.pi)

    fig, axes = plt.subplots(6, 1, figsize=(9, 14), sharex=True)

    # --- 1) 速度追従 ---
    axes[0].plot(t, res["wm"], label="$\\omega_m$", color="tab:green")
    axes[0].plot(t, res["wref"], "--", label="$\\omega_m^*$", color="gray")
    axes[0].set_ylabel("Speed [rad/s]")
    axes[0].set_title(title)
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    # --- 2) 速度 (rpm) ---
    axes[1].plot(t, rpm, color="tab:orange")
    axes[1].plot(t, rpm_ref, "--", color="gray")
    axes[1].set_ylabel("Speed [rpm]")
    axes[1].grid(True, alpha=0.3)

    # --- 3) iq と iq_ref (内側ループから見た指令追従) ---
    axes[2].plot(t, res["iq"], label="$i_q$", color="tab:red")
    axes[2].plot(t, res["iq_ref"], "--", label="$i_q^*$ (from ASR)", color="tab:red", alpha=0.5)
    axes[2].plot(t, res["id_"], label="$i_d$", color="tab:blue")
    axes[2].axhline(+motor_params.I_max, color="gray", linestyle=":", label="±I_max")
    axes[2].axhline(-motor_params.I_max, color="gray", linestyle=":")
    axes[2].set_ylabel("Current [A]")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc="best", ncol=2)

    # --- 4) 制御電圧 ---
    v_lim = motor_params.Vdc / np.sqrt(3.0)
    axes[3].plot(t, res["vq"], label="$v_q$", color="tab:red")
    axes[3].plot(t, res["vd"], label="$v_d$", color="tab:blue")
    axes[3].axhline(+v_lim, color="gray", linestyle=":", label="±V_limit")
    axes[3].axhline(-v_lim, color="gray", linestyle=":")
    axes[3].set_ylabel("Voltage [V]")
    axes[3].grid(True, alpha=0.3)
    axes[3].legend(loc="best")

    # --- 5) 電磁トルク & 負荷トルク ---
    axes[4].plot(t, res["Te"], label="$T_e$", color="tab:purple")
    axes[4].plot(t, res["TL"], label="$T_L$", color="tab:brown", linestyle="--")
    axes[4].set_ylabel("Torque [N·m]")
    axes[4].grid(True, alpha=0.3)
    axes[4].legend(loc="best")

    # --- 6) 速度誤差 ---
    err = res["wm"] - res["wref"]
    axes[5].plot(t, err, color="tab:red")
    axes[5].axhline(0, color="gray", linewidth=0.5)
    axes[5].set_ylabel("$\\omega_m - \\omega_m^*$ [rad/s]")
    axes[5].set_xlabel("Time [ms]")
    axes[5].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=120)
    print(f"Saved: {save_path}")


def _compute_metrics(res: dict, omega_ref: float, step_time: float = 0.0):
    """速度ステップ応答の指標を計算"""
    t = res["t"]
    wm = res["wm"]

    mask = t >= step_time
    t_post = t[mask]
    wm_post = wm[mask]

    peak = wm_post.max()
    overshoot = (peak - omega_ref) / omega_ref * 100.0 if omega_ref != 0 else 0.0

    band = 0.02 * abs(omega_ref)
    inside = np.abs(wm_post - omega_ref) <= band
    idx_settle = None
    for i in range(len(inside)):
        if inside[i] and np.all(inside[i:]):
            idx_settle = i
            break
    t_settle = (t_post[idx_settle] - step_time) if idx_settle is not None else np.nan

    ss_err = wm[-1] - omega_ref

    return dict(
        peak=peak,
        overshoot=overshoot,
        t_settle=t_settle,
        ss_err=ss_err,
    )


# ---------------------------------------------------------------------------
# Scenario 1: 速度ステップ応答 (無負荷)
# ---------------------------------------------------------------------------
def scenario_step():
    print("\n=== Scenario 1: Speed Step (0 → 50 rad/s, no load) ===")
    omega_ref = 50.0
    res = _simulate_speed_loop(
        omega_ref=omega_ref,
        T_sim=0.3,
        dt=1.0e-5,
    )
    m = _compute_metrics(res, omega_ref)
    print(f"  peak        = {m['peak']:.3f} rad/s "
          f"({m['peak']*60/(2*np.pi):.1f} rpm)")
    print(f"  overshoot   = {m['overshoot']:+.2f} %")
    print(f"  t_settle±2% = {m['t_settle']*1e3:.1f} ms"
          if not np.isnan(m["t_settle"]) else "  t_settle±2% = (not reached)")
    print(f"  SS error    = {m['ss_err']:+.4e} rad/s")

    _plot_result(
        res,
        title=f"W4-3 Scenario 1: Speed Step ($\\omega^*$=50 rad/s, no load)",
        save_path=str(_FIG_DIR / "speed_loop_step.png"),
    )


# ---------------------------------------------------------------------------
# Scenario 2: 外乱応答 (定常後に負荷トルク印加)
# ---------------------------------------------------------------------------
def scenario_disturbance():
    print("\n=== Scenario 2: Load Torque Disturbance ===")
    omega_ref = 50.0
    TL = 5.0  # N·m
    t_step = 0.2  # s  (定常に達した後に負荷印加)

    res = _simulate_speed_loop(
        omega_ref=omega_ref,
        T_sim=0.4,
        dt=1.0e-5,
        TL_step_time=t_step,
        TL_amp=TL,
    )

    # 外乱応答指標
    t = res["t"]
    wm = res["wm"]
    mask_post = t >= t_step
    wm_post = wm[mask_post]
    t_post = t[mask_post]
    drop = wm_post.min() - omega_ref
    t_min = t_post[np.argmin(wm_post)] - t_step
    # 復帰 (±2% 内)
    band = 0.02 * abs(omega_ref)
    inside = np.abs(wm_post - omega_ref) <= band
    recovered = None
    for i in range(len(inside)):
        if inside[i] and np.all(inside[i:]):
            recovered = t_post[i] - t_step
            break

    print(f"  TL          = {TL} N·m @ t = {t_step*1e3:.0f} ms")
    print(f"  max drop    = {drop:.3f} rad/s ({drop*60/(2*np.pi):.1f} rpm)")
    print(f"  drop time   = {t_min*1e3:.1f} ms after TL")
    print(f"  recovery±2% = {recovered*1e3:.1f} ms after TL"
          if recovered is not None else "  recovery±2% = (not reached)")
    print(f"  SS iq       = {res['iq'][-1]:.3f} A  (expected {TL/(1.5*motor_params.Pn*motor_params.Ke):.3f} A)")

    _plot_result(
        res,
        title=f"W4-3 Scenario 2: Load Disturbance ($T_L$={TL} N·m @ {t_step*1e3:.0f} ms)",
        save_path=str(_FIG_DIR / "speed_loop_disturbance.png"),
    )


if __name__ == "__main__":
    cfg = motor_params
    asr = SpeedPIController(cfg)
    Kt = 1.5 * cfg.Pn * cfg.Ke
    print("============================================================")
    print("W4-3: ASR+ACR カスケード制御 閉ループ検証")
    print("============================================================")
    print(f"  Vdc      = {cfg.Vdc} V")
    print(f"  J        = {cfg.J} kg·m²")
    print(f"  Kt       = {Kt:.3f} N·m/A")
    print(f"  ω_asr    = {cfg.W_asr} rad/s ({cfg.W_asr/(2*np.pi):.2f} Hz)")
    print(f"  Kp_w     = {asr.Kp:.4f}")
    print(f"  Ki_w     = {asr.Ki:.4f}")

    scenario_step()
    scenario_disturbance()
