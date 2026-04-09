"""
motor_model.py
BLDC (PMSM) モータの連続時間 d-q 軸モデル

状態ベクトル x:
    x = [id, iq, omega_m, theta_m]
      id       : d軸電流 [A]
      iq       : q軸電流 [A]
      omega_m  : 機械角速度 [rad/s]
      theta_m  : 機械角 [rad]

入力 u:
    u = [vd, vq]
      vd, vq   : d/q軸指令電圧 [V]

外乱:
    TL        : 負荷トルク [N・m]
    D         : 粘性摩擦係数 [N・m・s/rad]

電気系 (d-q軸状態方程式, 振幅不変形ベース):
    did/dt = ( vd - Rs*id + ωe*Lq*iq )            / Ld
    diq/dt = ( vq - Rs*iq - ωe*Ld*id - ωe*Ke )    / Lq

機械系:
    Te     = (3/2) * Pn * ( Ke*iq + (Ld - Lq)*id*iq )   ← 振幅不変形なので 3/2 が必要
    dωm/dt = ( Te - TL - D*ωm ) / J
    dθm/dt = ωm
    ωe     = Pn * ωm

本モジュールは「真値(参照)」用として RK4 法で積分する。
離散化の簡易実装（前進オイラー / 双一次変換）は discrete_model.py 側で扱う。
"""

from __future__ import annotations
import numpy as np

from config import MotorConfig, motor_params


class BLDCMotor:
    """連続時間 BLDC モータモデル (RK4 積分)"""

    def __init__(self, cfg: MotorConfig = motor_params) -> None:
        self.cfg = cfg
        self.reset()

    # -----------------------------------------------------------------
    # 状態操作
    # -----------------------------------------------------------------
    def reset(
        self,
        id_: float = 0.0,
        iq_: float = 0.0,
        omega_m: float = 0.0,
        theta_m: float = 0.0,
    ) -> None:
        self.id = float(id_)
        self.iq = float(iq_)
        self.omega_m = float(omega_m)
        self.theta_m = float(theta_m)

    def state(self) -> np.ndarray:
        return np.array([self.id, self.iq, self.omega_m, self.theta_m])

    # -----------------------------------------------------------------
    # 物理量 helper
    # -----------------------------------------------------------------
    def electric_torque(self, id_: float, iq_: float) -> float:
        """
        電磁トルク [N・m]
        Te = (3/2) * Pn * [ Ke*iq + (Ld - Lq)*id*iq ]
             └──────┘   └─────┘   └─────────────┘
           振幅不変係数  マグネットトルク  リラクタンストルク
        """
        c = self.cfg
        return 1.5 * c.Pn * (c.Ke * iq_ + (c.Ld - c.Lq) * id_ * iq_)

    # -----------------------------------------------------------------
    # 連続系の状態微分 f(x, u)
    # -----------------------------------------------------------------
    def derivatives(
        self,
        x: np.ndarray,
        vd: float,
        vq: float,
        TL: float = 0.0,
        D: float = 0.0,
    ) -> np.ndarray:
        c = self.cfg
        id_, iq_, wm, _th = x

        omega_e = c.Pn * wm
        did_dt = (vd - c.Rs * id_ + omega_e * c.Lq * iq_) / c.Ld
        diq_dt = (vq - c.Rs * iq_ - omega_e * c.Ld * id_ - omega_e * c.Ke) / c.Lq

        Te = self.electric_torque(id_, iq_)
        dwm_dt = (Te - TL - D * wm) / c.J
        dth_dt = wm

        return np.array([did_dt, diq_dt, dwm_dt, dth_dt])

    # -----------------------------------------------------------------
    # RK4 1ステップ積分 (真値用)
    # -----------------------------------------------------------------
    def step_rk4(
        self,
        vd: float,
        vq: float,
        dt: float,
        TL: float = 0.0,
        D: float = 0.0,
    ) -> np.ndarray:
        x = self.state()
        k1 = self.derivatives(x,               vd, vq, TL, D)
        k2 = self.derivatives(x + 0.5 * dt * k1, vd, vq, TL, D)
        k3 = self.derivatives(x + 0.5 * dt * k2, vd, vq, TL, D)
        k4 = self.derivatives(x +       dt * k3, vd, vq, TL, D)
        x_new = x + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

        self.id, self.iq, self.omega_m, self.theta_m = x_new.tolist()
        return x_new


# ===========================================================================
# 単体動作確認: 無負荷で vq=30V を印加し、電流と回転数の時間応答を観察
# ===========================================================================
if __name__ == "__main__":
    motor = BLDCMotor()
    dt = 1.0e-5       # 10 μs (制御周期 10kHz 相当でさらに細かく積分)
    T  = 0.05         # 50 ms シミュレーション
    N  = int(T / dt)

    vd_cmd, vq_cmd = 0.0, 30.0

    log_t = np.zeros(N)
    log_id = np.zeros(N)
    log_iq = np.zeros(N)
    log_wm = np.zeros(N)

    for k in range(N):
        motor.step_rk4(vd_cmd, vq_cmd, dt)
        log_t[k]  = (k + 1) * dt
        log_id[k] = motor.id
        log_iq[k] = motor.iq
        log_wm[k] = motor.omega_m

    print("=== BLDCMotor (RK4, 連続系真値) ===")
    print(f"  dt        = {dt*1e6:.1f} μs,  シミュ時間 = {T*1e3:.1f} ms")
    print(f"  入力      : vd = {vd_cmd:.1f} V, vq = {vq_cmd:.1f} V")
    print("--- 時刻ごとの応答 ---")
    for k in [0, N // 10, N // 4, N // 2, N - 1]:
        print(
            f"  t = {log_t[k]*1e3:6.2f} ms | "
            f"id = {log_id[k]:+7.3f} A, "
            f"iq = {log_iq[k]:+7.3f} A, "
            f"ωm = {log_wm[k]:+8.2f} rad/s "
            f"({log_wm[k]*60/(2*np.pi):+7.1f} rpm)"
        )
