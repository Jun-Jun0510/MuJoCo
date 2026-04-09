"""
discrete_model.py
BLDC モータ d-q 軸モデルの離散化実装

目的:
  - マイコン (STM32H7 等) で 10kHz 制御ループ内に載せることを想定
  - 連続系モデル (motor_model.py, RK4) を「真値」として数値比較する
  - 離散化手法の違い (安定性・誤差) を可視化する

実装する離散化:
  1) Forward Euler  (前進オイラー法, 1次, 陽解法)
       x[k+1] = x[k] + dt * f(x[k], u[k])
     - 実装が最も単純。マイコンで一般的。
     - dt が大きいと不安定化しやすい (電流ループで振動・発散)。

  2) Tustin (双一次変換, 2次, 陰的・線形系にのみ適用)
       電気系を ωe を各ステップ固定の LTI とみなし、
       x_new = (I - dt/2 * A)^{-1} * [(I + dt/2 * A) * x_old + dt * B * u_avg]
     - 周波数応答が連続系に近く、電流ループの発振抑制に有利。
     - ωe 依存の A 行列はステップ毎に凍結 (前ステップの ωm を使う)。
     - 機械系は前進オイラーのまま (電気系より時定数が十分長いので)。
"""

from __future__ import annotations
import numpy as np

from config import MotorConfig, motor_params
from motor_model import BLDCMotor


# ===========================================================================
# 1) 前進オイラー離散化
# ===========================================================================
class EulerDiscreteMotor:
    """Forward-Euler 離散化モータモデル (マイコン実装と同じ陽解法)"""

    def __init__(self, cfg: MotorConfig = motor_params, dt: float = 1.0e-4) -> None:
        self.cfg = cfg
        self.dt = dt
        self.reset()

    def reset(self) -> None:
        self.id = 0.0
        self.iq = 0.0
        self.omega_m = 0.0
        self.theta_m = 0.0

    def step(self, vd: float, vq: float, TL: float = 0.0) -> tuple[float, float, float, float]:
        c = self.cfg
        dt = self.dt

        omega_e = c.Pn * self.omega_m
        # --- 電気系 ---
        did_dt = (vd - c.Rs * self.id + omega_e * c.Lq * self.iq) / c.Ld
        diq_dt = (vq - c.Rs * self.iq - omega_e * c.Ld * self.id - omega_e * c.Ke) / c.Lq
        # --- 機械系 ---
        Te = 1.5 * c.Pn * (c.Ke * self.iq + (c.Ld - c.Lq) * self.id * self.iq)
        dwm_dt = (Te - TL) / c.J

        # 1次オイラー更新
        self.id      += dt * did_dt
        self.iq      += dt * diq_dt
        self.omega_m += dt * dwm_dt
        self.theta_m += dt * self.omega_m

        return self.id, self.iq, self.omega_m, self.theta_m


# ===========================================================================
# 2) Tustin (双一次変換) 離散化
# ===========================================================================
class TustinDiscreteMotor:
    """
    電気系のみ Tustin, 機械系は前進オイラー。

    電気系 LTI 表現 (ωe 固定):
        dx/dt = A*x + B*u_aug
        x     = [id, iq]^T
        u_aug = [vd, vq, 1]^T
        A = [[-Rs/Ld,    ωe*Lq/Ld],
             [-ωe*Ld/Lq, -Rs/Lq  ]]
        B = [[1/Ld,  0,    0          ],
             [0,     1/Lq, -ωe*Ke/Lq  ]]

    Tustin 離散化:
        x_new = M1^{-1} * [ M2 * x_old + dt * B * u_aug ]
        M1 = I - (dt/2) * A
        M2 = I + (dt/2) * A
    """

    def __init__(self, cfg: MotorConfig = motor_params, dt: float = 1.0e-4) -> None:
        self.cfg = cfg
        self.dt = dt
        self.reset()

    def reset(self) -> None:
        self.id = 0.0
        self.iq = 0.0
        self.omega_m = 0.0
        self.theta_m = 0.0

    def _electric_matrices(self, omega_e: float) -> tuple[np.ndarray, np.ndarray]:
        c = self.cfg
        A = np.array([
            [-c.Rs / c.Ld,          omega_e * c.Lq / c.Ld],
            [-omega_e * c.Ld / c.Lq, -c.Rs / c.Lq       ],
        ])
        B = np.array([
            [1.0 / c.Ld, 0.0,         0.0                 ],
            [0.0,        1.0 / c.Lq, -omega_e * c.Ke / c.Lq],
        ])
        return A, B

    def step(self, vd: float, vq: float, TL: float = 0.0) -> tuple[float, float, float, float]:
        c = self.cfg
        dt = self.dt

        # ── 電気系: Tustin (ωe はステップ内で凍結) ──
        omega_e = c.Pn * self.omega_m
        A, B = self._electric_matrices(omega_e)
        I2 = np.eye(2)
        M1 = I2 - 0.5 * dt * A
        M2 = I2 + 0.5 * dt * A
        x_old = np.array([self.id, self.iq])
        u_aug = np.array([vd, vq, 1.0])
        rhs = M2 @ x_old + dt * (B @ u_aug)
        x_new = np.linalg.solve(M1, rhs)
        self.id, self.iq = float(x_new[0]), float(x_new[1])

        # ── 機械系: 前進オイラー ──
        Te = 1.5 * c.Pn * (c.Ke * self.iq + (c.Ld - c.Lq) * self.id * self.iq)
        dwm_dt = (Te - TL) / c.J
        self.omega_m += dt * dwm_dt
        self.theta_m += dt * self.omega_m

        return self.id, self.iq, self.omega_m, self.theta_m


# ===========================================================================
# 単体動作確認: RK4(真値) vs Euler vs Tustin の数値比較
# ===========================================================================
def _simulate(model, steps: int, dt: float, vd: float, vq: float) -> np.ndarray:
    """任意のモデルをステップ入力で回して状態ログを返す"""
    log = np.zeros((steps, 4))
    for k in range(steps):
        if isinstance(model, BLDCMotor):
            model.step_rk4(vd, vq, dt)
            log[k] = [model.id, model.iq, model.omega_m, model.theta_m]
        else:
            log[k] = model.step(vd, vq)
    return log


def _run_comparison(dt: float, T: float, vd: float, vq: float) -> None:
    steps = int(T / dt)
    t = np.arange(1, steps + 1) * dt

    # --- 真値 (RK4) ---
    ref = BLDCMotor()
    log_ref = _simulate(ref, steps, dt, vd, vq)

    # --- Euler ---
    m_euler = EulerDiscreteMotor(dt=dt)
    log_euler = _simulate(m_euler, steps, dt, vd, vq)

    # --- Tustin ---
    m_tustin = TustinDiscreteMotor(dt=dt)
    log_tustin = _simulate(m_tustin, steps, dt, vd, vq)

    # --- 誤差 (各ステップの iq を真値と比較, L∞ノルム) ---
    def max_err(log):
        return np.max(np.abs(log - log_ref), axis=0)

    err_e = max_err(log_euler)
    err_t = max_err(log_tustin)

    print(f"┌─ dt = {dt*1e6:7.1f} μs  (T = {T*1e3:.1f} ms, N = {steps})")
    print("│   [id誤差, iq誤差, ωm誤差, θm誤差]  (RK4 比較, L∞)")
    print(f"│  Euler  : [{err_e[0]:8.3e}, {err_e[1]:8.3e}, {err_e[2]:8.3e}, {err_e[3]:8.3e}]")
    print(f"│  Tustin : [{err_t[0]:8.3e}, {err_t[1]:8.3e}, {err_t[2]:8.3e}, {err_t[3]:8.3e}]")
    # 最終値の表示
    print(f"│  最終 iq  : RK4 = {log_ref[-1,1]:+.4f}, "
          f"Euler = {log_euler[-1,1]:+.4f}, "
          f"Tustin = {log_tustin[-1,1]:+.4f}")
    print(f"│  最終 ωm  : RK4 = {log_ref[-1,2]:+.2f}, "
          f"Euler = {log_euler[-1,2]:+.2f}, "
          f"Tustin = {log_tustin[-1,2]:+.2f}  [rad/s]")
    print("└─────────────────────────────────────────────")


if __name__ == "__main__":
    print("========================================================")
    print("BLDC 離散化モデル比較: 無負荷 vd=0, vq=30V ステップ印加")
    print("========================================================")
    # 細かい dt (10 μs): Euler も Tustin もほぼ RK4 と一致するはず
    _run_comparison(dt=1.0e-5, T=0.05, vd=0.0, vq=30.0)
    # 粗い dt (100 μs = 10kHz 制御周期相当): 誤差が見えてくる
    _run_comparison(dt=1.0e-4, T=0.05, vd=0.0, vq=30.0)
    # さらに粗い dt (500 μs): Euler が不安定化しやすい領域
    _run_comparison(dt=5.0e-4, T=0.05, vd=0.0, vq=30.0)
