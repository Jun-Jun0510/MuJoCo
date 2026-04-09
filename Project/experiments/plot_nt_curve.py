"""
plot_nt_curve.py
W4 追加検証: 現状パラメータの N-T (速度-トルク) 特性を描く。

目的: 弱め界磁制御 (Field Weakening) 実装の前に、
      現在のモータで何が理論上達成可能かを把握する。

2つの戦略を比較:
  (A) id = 0  (弱め界磁なし)  ── 電流・電圧制約下で iq を最大化
  (B) MTPA + FW               ── (id, iq) を最適化してトルク最大化
                                  高速域では id < 0 で界磁を弱める

制約 (定常状態, d(id)/dt = d(iq)/dt = 0):
  電流制約: id² + iq² ≤ I_max²
  電圧制約: vd² + vq² ≤ V_lim²
           vd = Rs·id − ωe·Lq·iq
           vq = Rs·iq + ωe·Ld·id + ωe·Ke

トルク (IPM リラクタンストルク含む):
  Te = (3/2)·Pn·[ Ke·iq + (Ld − Lq)·id·iq ]
  IPM (Ld < Lq) では (Ld−Lq) < 0 → リラクタンストルクを得るには id < 0
"""

import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT / "src"))
_FIG_DIR = _PROJECT / "figures"

import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize

from config import motor_params


cfg = motor_params
Kt_pm = 1.5 * cfg.Pn * cfg.Ke                 # マグネットトルク係数
V_lim = cfg.Vdc / np.sqrt(3.0)                # 六角形近似 電圧円半径
I_max = cfg.I_max
Ich = cfg.Ke / cfg.Ld                         # 特性電流


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def torque(id_: float, iq_: float) -> float:
    """電磁トルク [N·m]"""
    return 1.5 * cfg.Pn * (cfg.Ke * iq_ + (cfg.Ld - cfg.Lq) * id_ * iq_)


def voltage(id_: float, iq_: float, omega_e: float) -> tuple[float, float]:
    """定常状態の dq 電圧"""
    vd = cfg.Rs * id_ - omega_e * cfg.Lq * iq_
    vq = cfg.Rs * iq_ + omega_e * cfg.Ld * id_ + omega_e * cfg.Ke
    return vd, vq


def voltage_norm(id_: float, iq_: float, omega_e: float) -> float:
    vd, vq = voltage(id_, iq_, omega_e)
    return np.sqrt(vd * vd + vq * vq)


# ---------------------------------------------------------------------------
# (A) id = 0 戦略: 電流/電圧制約下で iq を最大化
# ---------------------------------------------------------------------------
def solve_id0(omega_e: float) -> tuple[float, float, float]:
    """id=0 固定で許容できる最大 iq を求める"""
    # 電圧制約: (ωe·Lq·iq)² + (Rs·iq + ωe·Ke)² = V_lim²
    # 2次方程式: a·iq² + b·iq + c = 0
    a = (omega_e * cfg.Lq) ** 2 + cfg.Rs ** 2
    b = 2.0 * cfg.Rs * omega_e * cfg.Ke
    c = (omega_e * cfg.Ke) ** 2 - V_lim ** 2

    # 背面 EMF だけで既に V_lim を超えている (c > 0 かつ b > 0) → iq ≥ 0 に解なし
    if c > 0.0:
        return 0.0, 0.0, 0.0

    # c ≤ 0 → iq = 0 は電圧制約内。正の iq は iq_v = (-b + √disc) / 2a まで許容
    disc = b * b - 4.0 * a * c
    iq_v = (-b + np.sqrt(disc)) / (2.0 * a) if a > 0.0 else I_max
    iq_best = min(I_max, max(0.0, iq_v))
    return 0.0, iq_best, torque(0.0, iq_best)


# ---------------------------------------------------------------------------
# (B) MTPA + Field Weakening 最適化: (id, iq) を同時に探索
# ---------------------------------------------------------------------------
def solve_mtpa_fw(omega_e: float, x_warm: np.ndarray | None = None) -> tuple[float, float, float]:
    """
    与えられた電気角速度 ωe において、電流/電圧制約下で Te を最大化する
    (id, iq) を scipy.optimize.minimize (SLSQP, マルチスタート) で求める。
    """
    # 目的: Te を最大化 → -Te を最小化
    def neg_torque(x: np.ndarray) -> float:
        return -torque(x[0], x[1])

    def neg_torque_grad(x: np.ndarray) -> np.ndarray:
        id_, iq_ = x
        dTe_did = 1.5 * cfg.Pn * (cfg.Ld - cfg.Lq) * iq_
        dTe_diq = 1.5 * cfg.Pn * (cfg.Ke + (cfg.Ld - cfg.Lq) * id_)
        return -np.array([dTe_did, dTe_diq])

    # 電流制約:  I_max² − (id² + iq²) ≥ 0
    def cons_current(x: np.ndarray) -> float:
        return I_max ** 2 - (x[0] ** 2 + x[1] ** 2)

    # 電圧制約:  V_lim² − (vd² + vq²) ≥ 0
    def cons_voltage(x: np.ndarray) -> float:
        return V_lim ** 2 - voltage_norm(x[0], x[1], omega_e) ** 2

    cons = [
        {"type": "ineq", "fun": cons_current},
        {"type": "ineq", "fun": cons_voltage},
    ]
    bounds = [(-I_max, 0.0), (0.0, I_max)]

    # マルチスタート: 電流円・電圧楕円の交点近傍を複数試す
    starts: list[np.ndarray] = []
    if x_warm is not None:
        starts.append(x_warm)

    # 1) MTPA 初期点 (低速用)
    a_ = 4.0 * (cfg.Lq - cfg.Ld)
    id_mtpa = (cfg.Ke - np.sqrt(cfg.Ke ** 2 + 8.0 * (cfg.Lq - cfg.Ld) ** 2 * I_max ** 2)) / a_
    iq_mtpa = np.sqrt(max(0.0, I_max ** 2 - id_mtpa ** 2))
    starts.append(np.array([id_mtpa, iq_mtpa]))

    # 2) id=0 近傍 (低速用)
    starts.append(np.array([-0.5, min(I_max * 0.8, 20.0)]))

    # 3) 電流円上を -Ich 方向へ振った点 (高速 FW 用)
    for frac in (0.3, 0.5, 0.7, 0.9):
        id_try = -I_max * frac
        iq_try = np.sqrt(max(0.0, I_max ** 2 - id_try ** 2))
        starts.append(np.array([id_try, iq_try]))

    # 4) 特性電流中心付近 (極高速 FW 用)
    starts.append(np.array([-Ich, min(5.0, I_max * 0.1)]))

    best_Te = -np.inf
    best_x = np.array([0.0, 0.0])
    for x0 in starts:
        # 初期点を実行可能領域に軽くクリップ
        x0c = np.clip(x0, [bounds[0][0], bounds[1][0]], [bounds[0][1], bounds[1][1]])
        try:
            res = minimize(
                neg_torque,
                x0c,
                jac=neg_torque_grad,
                method="SLSQP",
                bounds=bounds,
                constraints=cons,
                options={"ftol": 1e-10, "maxiter": 300},
            )
        except Exception:
            continue
        if not res.success:
            continue
        # 制約確認 (SLSQP が少しだけ破ることがあるので余裕を持たせる)
        if cons_current(res.x) < -1e-4 or cons_voltage(res.x) < -1e-4:
            continue
        Te_here = torque(res.x[0], res.x[1])
        if Te_here > best_Te:
            best_Te = Te_here
            best_x = res.x

    if best_Te <= 0.0:
        return 0.0, 0.0, 0.0
    return float(best_x[0]), float(best_x[1]), float(best_Te)


# ---------------------------------------------------------------------------
# メイン: 速度を振って両戦略の N-T 包絡線を計算
# ---------------------------------------------------------------------------
def main():
    # 速度グリッド [rpm]
    rpm_arr = np.linspace(1.0, 6000.0, 400)
    omega_m = rpm_arr * (2.0 * np.pi / 60.0)     # 機械角速度
    omega_e = cfg.Pn * omega_m                   # 電気角速度

    id0_id = np.zeros_like(rpm_arr)
    id0_iq = np.zeros_like(rpm_arr)
    id0_Te = np.zeros_like(rpm_arr)

    fw_id = np.zeros_like(rpm_arr)
    fw_iq = np.zeros_like(rpm_arr)
    fw_Te = np.zeros_like(rpm_arr)

    # 初期値は低速での MTPA 点から徐々にウォームスタート
    x_warm = None
    for i, we in enumerate(omega_e):
        id0_id[i], id0_iq[i], id0_Te[i] = solve_id0(we)

        id_, iq_, Te_ = solve_mtpa_fw(we, x_warm)
        fw_id[i], fw_iq[i], fw_Te[i] = id_, iq_, Te_
        if Te_ > 0:
            x_warm = np.array([id_, iq_])

    # パワー [kW]
    id0_P = id0_Te * omega_m * 1e-3
    fw_P  = fw_Te  * omega_m * 1e-3

    # --- 基準値の印字 ---
    print("===========================================================")
    print("N-T Envelope (current motor parameters)")
    print("===========================================================")
    print(f"  Vdc       = {cfg.Vdc} V       V_lim = Vdc/√3 = {V_lim:.2f} V")
    print(f"  I_max     = {I_max} A")
    print(f"  Ke        = {cfg.Ke} Wb")
    print(f"  Ld, Lq    = {cfg.Ld*1e3:.2f}, {cfg.Lq*1e3:.2f} mH  (IPM, Lq/Ld={cfg.Lq/cfg.Ld:.2f})")
    print(f"  Kt (PM)   = {Kt_pm:.3f} N·m/A  (マグネットトルクのみ)")
    print(f"  Ich=Ke/Ld = {Ich:.2f} A   (< I_max={I_max} → 理論上 ω→∞ で収束)")
    print("───────────────────────────────────────────────────────────")
    print(f"  Te @ id=0, iq=I_max        : {Kt_pm*I_max:.2f} N·m")
    # MTPA 理論 (低速域, リラクタンストルク最大化)
    # 最大値は解析解: id = (Ke − √(Ke² + 8·(Lq−Ld)²·I²)) / (4·(Lq−Ld))
    a_ = 4.0 * (cfg.Lq - cfg.Ld)
    I2 = I_max ** 2
    id_mtpa = (cfg.Ke - np.sqrt(cfg.Ke ** 2 + 8.0 * (cfg.Lq - cfg.Ld) ** 2 * I2)) / a_
    iq_mtpa = np.sqrt(max(0.0, I2 - id_mtpa ** 2))
    Te_mtpa = torque(id_mtpa, iq_mtpa)
    print(f"  MTPA @ I_max (analytic)    : id={id_mtpa:.3f}, iq={iq_mtpa:.3f}, Te={Te_mtpa:.2f} N·m")
    print(f"  → reluctance boost factor  : {Te_mtpa/(Kt_pm*I_max):.2f}x")
    print("───────────────────────────────────────────────────────────")
    # ベース速度 (id=0, iq=I_max 時に電圧制約に当たる速度)
    # ωe² ((Lq·I)² + (Rs·I/ωe + Ke)²) ≈ V_lim²  → 近似で Ke·ωe ≈ V_lim
    idx_cross = np.argmax(id0_Te < 0.99 * id0_Te[0])
    rpm_base_id0 = rpm_arr[idx_cross] if idx_cross > 0 else np.nan
    idx_cross_fw = np.argmax(fw_Te < 0.99 * fw_Te[0])
    rpm_base_fw  = rpm_arr[idx_cross_fw] if idx_cross_fw > 0 else np.nan
    print(f"  Base speed (id=0)   ≈ {rpm_base_id0:7.1f} rpm")
    print(f"  Base speed (MTPA+FW)≈ {rpm_base_fw:7.1f} rpm")
    print(f"  Max Te  (id=0)   = {id0_Te.max():.2f} N·m @ {rpm_arr[id0_Te.argmax()]:.0f} rpm")
    print(f"  Max Te  (FW)     = {fw_Te.max():.2f} N·m @ {rpm_arr[fw_Te.argmax()]:.0f} rpm")
    print(f"  Max P   (id=0)   = {id0_P.max():.2f} kW @ {rpm_arr[id0_P.argmax()]:.0f} rpm")
    print(f"  Max P   (FW)     = {fw_P.max():.2f} kW @ {rpm_arr[fw_P.argmax()]:.0f} rpm")
    print("===========================================================")

    # -----------------------------------------------------------------
    # プロット
    # -----------------------------------------------------------------
    fig, axes = plt.subplots(3, 1, figsize=(9, 11), sharex=True)

    # (1) N-T 曲線
    ax = axes[0]
    ax.plot(rpm_arr, id0_Te, label="id = 0 (no FW)",
            color="tab:red", linewidth=1.8)
    ax.plot(rpm_arr, fw_Te, label="MTPA + Field Weakening",
            color="tab:green", linewidth=1.8)
    ax.fill_between(rpm_arr, id0_Te, fw_Te,
                    where=(fw_Te > id0_Te),
                    color="tab:green", alpha=0.15, label="FW gain")
    ax.axhline(Kt_pm * I_max, color="gray", linestyle=":",
               label=f"Kt·I_max = {Kt_pm*I_max:.1f} N·m")
    ax.axhline(Te_mtpa, color="black", linestyle=":",
               label=f"MTPA max = {Te_mtpa:.1f} N·m")
    ax.set_ylabel("Torque Te [N·m]")
    ax.set_title(
        f"N-T Envelope  "
        f"(Vdc={cfg.Vdc}V, I_max={I_max}A, IPM Lq/Ld={cfg.Lq/cfg.Ld:.2f})"
    )
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)

    # (2) N-P (パワー) 曲線
    ax = axes[1]
    ax.plot(rpm_arr, id0_P, label="id = 0", color="tab:red", linewidth=1.8)
    ax.plot(rpm_arr, fw_P,  label="MTPA + FW",  color="tab:green", linewidth=1.8)
    ax.set_ylabel("Power P [kW]")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")

    # (3) 最適電流軌跡 (id, iq)
    ax = axes[2]
    ax.plot(rpm_arr, fw_id, label="$i_d^*$ (MTPA+FW)", color="tab:blue", linewidth=1.8)
    ax.plot(rpm_arr, fw_iq, label="$i_q^*$ (MTPA+FW)", color="tab:orange", linewidth=1.8)
    ax.plot(rpm_arr, id0_iq, label="$i_q^*$ (id=0)",
            color="tab:red", linestyle="--", alpha=0.7)
    ax.axhline(-Ich, color="black", linestyle=":",
               label=f"$-I_{{ch}} = {-Ich:.2f}$ A")
    ax.axhline(+I_max, color="gray", linestyle=":", alpha=0.5)
    ax.axhline(-I_max, color="gray", linestyle=":", alpha=0.5)
    ax.set_ylabel("Current [A]")
    ax.set_xlabel("Speed [rpm]")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", ncol=2, fontsize=9)

    plt.tight_layout()
    out_path = str(_FIG_DIR / "nt_curve.png")
    plt.savefig(out_path, dpi=120)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
