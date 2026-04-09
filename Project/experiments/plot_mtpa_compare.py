"""
plot_mtpa_compare.py
MTPA (Maximum Torque Per Ampere) LUT vs id=0 戦略の比較検証。

ASR (Te* 出力) の構造は両方共通で、Te_max とその後段の電流指令生成だけが異なる:
  id=0  : id* = 0, iq* = clip(Te*/Kt, ±I_max),        Te_max = Kt·I_max ≈ 17.88 N·m
  MTPA  : (id*, iq*) = MTPA.lookup(Te*),               Te_max ≈ 42.07 N·m  (リラクタンス含)

シナリオ:
  A) 0 → 50 rad/s, 無負荷
     低トルク域なのでどちらも同一応答 (OS +4.85%)
  B) 0 → 50 rad/s, TL = 20 N·m (t=0 から印加)
     id=0 は Te_max=17.88 < 20 → 物理的に 50 rad/s に到達不能
     MTPA は Te_max=42.07 > 20 → 余裕で目標維持
"""

import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT / "src"))
_FIG_DIR = _PROJECT / "figures"

import numpy as np
import matplotlib.pyplot as plt

from pi_controller import _simulate_mtpa_loop, MTPATable
from config import motor_params


# ---------------------------------------------------------------------------
# 基礎情報を表示
# ---------------------------------------------------------------------------
def print_header():
    cfg = motor_params
    Kt = 1.5 * cfg.Pn * cfg.Ke
    mt = MTPATable(cfg)
    print("=" * 60)
    print("  MTPA vs id=0 Comparison")
    print("=" * 60)
    print(f"  Kt (= 1.5·Pn·Ke)  = {Kt:.3f} N·m/A")
    print(f"  Kt·I_max (id=0)   = {Kt*cfg.I_max:.3f} N·m")
    print(f"  MTPA@I_max        = {mt.Te_max:.3f} N·m")
    print(f"  Boost factor      = {mt.Te_max/(Kt*cfg.I_max):.2f}x")
    dL = cfg.Lq - cfg.Ld
    id_m = (cfg.Ke - np.sqrt(cfg.Ke**2 + 8*dL**2*cfg.I_max**2)) / (4*dL)
    iq_m = np.sqrt(cfg.I_max**2 - id_m**2)
    print(f"  MTPA point        : id={id_m:+.3f}, iq={iq_m:+.3f}")
    print("=" * 60)


def _metrics(res: dict, omega_ref: float):
    wm = res["wm"]
    t = res["t"]
    peak = wm.max()
    os_ = (peak - omega_ref) / omega_ref * 100.0 if omega_ref != 0 else 0.0
    band = 0.02 * abs(omega_ref)
    inside = np.abs(wm - omega_ref) <= band
    idx = None
    for i in range(len(inside)):
        if inside[i] and np.all(inside[i:]):
            idx = i
            break
    t_settle = t[idx] if idx is not None else np.nan
    ss_err = wm[-1] - omega_ref
    return dict(peak=peak, overshoot=os_, t_settle=t_settle, ss_err=ss_err)


# ---------------------------------------------------------------------------
# Scenario A: 無負荷ステップ
# ---------------------------------------------------------------------------
def scenario_A():
    omega_ref = 50.0
    T_sim = 0.3
    print("\n--- Scenario A: 0 → 50 rad/s, no load ---")

    res_id0  = _simulate_mtpa_loop(omega_ref=omega_ref, T_sim=T_sim, mode="id0")
    res_mtpa = _simulate_mtpa_loop(omega_ref=omega_ref, T_sim=T_sim, mode="mtpa")

    m_id0  = _metrics(res_id0,  omega_ref)
    m_mtpa = _metrics(res_mtpa, omega_ref)

    print(f"  {'':15s} {'id=0':>15s}  {'MTPA':>15s}")
    print(f"  {'peak [rad/s]':15s} {m_id0['peak']:15.3f}  {m_mtpa['peak']:15.3f}")
    print(f"  {'overshoot [%]':15s} {m_id0['overshoot']:+15.2f}  {m_mtpa['overshoot']:+15.2f}")
    print(f"  {'t_settle [ms]':15s} {m_id0['t_settle']*1e3:15.1f}  {m_mtpa['t_settle']*1e3:15.1f}")
    print(f"  {'SS |I| [A]':15s} {res_id0['Is'][-1]:15.3f}  {res_mtpa['Is'][-1]:15.3f}")

    # ---- プロット ----
    t_ms = res_id0["t"] * 1e3
    fig, axes = plt.subplots(4, 1, figsize=(9, 10), sharex=True)

    axes[0].plot(t_ms, res_id0["wm"], label="id=0",  color="tab:red",   linewidth=1.5)
    axes[0].plot(t_ms, res_mtpa["wm"], label="MTPA",  color="tab:green", linewidth=1.5)
    axes[0].axhline(omega_ref, color="gray", linestyle=":", label="$\\omega^*$")
    axes[0].set_ylabel("Speed $\\omega_m$ [rad/s]")
    axes[0].set_title("Scenario A: $\\omega^* = 50$ rad/s, no load")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    axes[1].plot(t_ms, res_id0["Te"], label="id=0 $T_e$",  color="tab:red",   linewidth=1.2)
    axes[1].plot(t_ms, res_mtpa["Te"], label="MTPA $T_e$", color="tab:green", linewidth=1.2)
    axes[1].plot(t_ms, res_id0["Te_ref"], "--", label="id=0 $T_e^*$", color="tab:red",   alpha=0.5)
    axes[1].plot(t_ms, res_mtpa["Te_ref"], "--", label="MTPA $T_e^*$", color="tab:green", alpha=0.5)
    axes[1].set_ylabel("Torque [N·m]")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best", ncol=2, fontsize=9)

    axes[2].plot(t_ms, res_id0["iq"],  label="id=0 $i_q$", color="tab:red",   linewidth=1.2)
    axes[2].plot(t_ms, res_id0["id_"], label="id=0 $i_d$", color="tab:red",   linestyle=":", linewidth=1.2)
    axes[2].plot(t_ms, res_mtpa["iq"],  label="MTPA $i_q$", color="tab:green", linewidth=1.2)
    axes[2].plot(t_ms, res_mtpa["id_"], label="MTPA $i_d$", color="tab:green", linestyle=":", linewidth=1.2)
    axes[2].axhline(+motor_params.I_max, color="gray", linestyle=":", alpha=0.5)
    axes[2].axhline(-motor_params.I_max, color="gray", linestyle=":", alpha=0.5)
    axes[2].set_ylabel("Current [A]")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc="best", ncol=2, fontsize=9)

    axes[3].plot(t_ms, res_id0["Is"],  label="id=0 $|I|$",  color="tab:red",   linewidth=1.5)
    axes[3].plot(t_ms, res_mtpa["Is"], label="MTPA $|I|$", color="tab:green", linewidth=1.5)
    axes[3].axhline(motor_params.I_max, color="gray", linestyle=":", label="$I_{max}$")
    axes[3].set_ylabel("$|I| = \\sqrt{i_d^2+i_q^2}$ [A]")
    axes[3].set_xlabel("Time [ms]")
    axes[3].grid(True, alpha=0.3)
    axes[3].legend(loc="best")

    plt.tight_layout()
    out = str(_FIG_DIR / "mtpa_compare_A.png")
    plt.savefig(out, dpi=120)
    print(f"  Saved: {out}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Scenario B: 重負荷ステップ
# ---------------------------------------------------------------------------
def scenario_B():
    omega_ref = 50.0
    TL = 20.0   # N·m, id=0 の Te_max=17.88 を超える重負荷
    T_sim = 0.5
    print("\n--- Scenario B: 0 → 50 rad/s, TL = 20 N·m from t=0 ---")

    res_id0  = _simulate_mtpa_loop(
        omega_ref=omega_ref, T_sim=T_sim, mode="id0",
        TL_step_time=0.0, TL_amp=TL,
    )
    res_mtpa = _simulate_mtpa_loop(
        omega_ref=omega_ref, T_sim=T_sim, mode="mtpa",
        TL_step_time=0.0, TL_amp=TL,
    )

    print(f"  {'':18s} {'id=0':>15s}  {'MTPA':>15s}")
    print(f"  {'SS ωm [rad/s]':18s} {res_id0['wm'][-1]:15.3f}  {res_mtpa['wm'][-1]:15.3f}")
    print(f"  {'SS Te [N·m]':18s} {res_id0['Te'][-1]:15.3f}  {res_mtpa['Te'][-1]:15.3f}")
    print(f"  {'SS id, iq [A]':18s} "
          f"{res_id0['id_'][-1]:+7.2f},{res_id0['iq'][-1]:+6.2f}  "
          f"{res_mtpa['id_'][-1]:+7.2f},{res_mtpa['iq'][-1]:+6.2f}")
    print(f"  {'SS |I| [A]':18s} {res_id0['Is'][-1]:15.3f}  {res_mtpa['Is'][-1]:15.3f}")

    # ---- プロット ----
    t_ms = res_id0["t"] * 1e3
    fig, axes = plt.subplots(4, 1, figsize=(9, 10), sharex=True)

    axes[0].plot(t_ms, res_id0["wm"], label="id=0  (FAIL)", color="tab:red",   linewidth=1.5)
    axes[0].plot(t_ms, res_mtpa["wm"], label="MTPA (OK)",    color="tab:green", linewidth=1.5)
    axes[0].axhline(omega_ref, color="gray", linestyle=":", label="$\\omega^*$=50")
    axes[0].axhline(0.0,       color="black", linestyle="-", linewidth=0.5)
    axes[0].set_ylabel("Speed $\\omega_m$ [rad/s]")
    axes[0].set_title(f"Scenario B: $\\omega^* = 50$ rad/s, $T_L = {TL}$ N·m")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    axes[1].plot(t_ms, res_id0["Te"],  label="id=0 $T_e$",   color="tab:red",   linewidth=1.2)
    axes[1].plot(t_ms, res_mtpa["Te"], label="MTPA $T_e$",   color="tab:green", linewidth=1.2)
    axes[1].axhline(TL, color="tab:brown", linestyle="--", label=f"$T_L$={TL}")
    axes[1].axhline(1.5*motor_params.Pn*motor_params.Ke*motor_params.I_max,
                    color="tab:red", linestyle=":", alpha=0.5,
                    label="$K_t·I_{max}$=17.88")
    axes[1].set_ylabel("Torque [N·m]")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best", fontsize=9)

    axes[2].plot(t_ms, res_id0["iq"],   label="id=0 $i_q$", color="tab:red",   linewidth=1.2)
    axes[2].plot(t_ms, res_id0["id_"],  label="id=0 $i_d$", color="tab:red",   linestyle=":", linewidth=1.2)
    axes[2].plot(t_ms, res_mtpa["iq"],  label="MTPA $i_q$", color="tab:green", linewidth=1.2)
    axes[2].plot(t_ms, res_mtpa["id_"], label="MTPA $i_d$", color="tab:green", linestyle=":", linewidth=1.2)
    axes[2].axhline(+motor_params.I_max, color="gray", linestyle=":", alpha=0.5)
    axes[2].axhline(-motor_params.I_max, color="gray", linestyle=":", alpha=0.5)
    axes[2].set_ylabel("Current [A]")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc="best", ncol=2, fontsize=9)

    axes[3].plot(t_ms, res_id0["Is"],  label="id=0 $|I|$", color="tab:red",   linewidth=1.5)
    axes[3].plot(t_ms, res_mtpa["Is"], label="MTPA $|I|$", color="tab:green", linewidth=1.5)
    axes[3].axhline(motor_params.I_max, color="gray", linestyle=":", label="$I_{max}$")
    axes[3].set_ylabel("$|I|$ [A]")
    axes[3].set_xlabel("Time [ms]")
    axes[3].grid(True, alpha=0.3)
    axes[3].legend(loc="best")

    plt.tight_layout()
    out = str(_FIG_DIR / "mtpa_compare_B.png")
    plt.savefig(out, dpi=120)
    print(f"  Saved: {out}")
    plt.close(fig)


if __name__ == "__main__":
    print_header()
    scenario_A()
    scenario_B()
