"""
transforms.py
Clarke / Park 変換および逆変換の実装

座標系:
  abc   : 3相静止座標 (A,B,C相)
  αβ    : 2相静止座標 (alpha, beta)
  dq    : 2相回転座標 (d軸: 磁束方向, q軸: トルク方向)

採用形式: 振幅不変形 (Amplitude-Invariant)
  - 3相正弦波の振幅 Im が、そのまま αβ・dq 軸の振幅として現れる
  - パワー不変形 (√(2/3)係数) ではないので注意

使用形態:
  - スカラー入力  : マイコン実機での逐次制御を模した1サンプル計算
  - ndarray 入力  : オフラインシミュレーション / 並列学習での一括計算
  (NumPy のブロードキャストにより、両者を同一関数で扱える)
"""

from __future__ import annotations
from typing import Union

import numpy as np

# スカラー / NumPy 配列の両対応を表す型エイリアス
FloatArray = Union[float, np.ndarray]


# ---------------------------------------------------------------------------
# Clarke 変換: abc → αβ  (3相静止 → 2相静止)
# ---------------------------------------------------------------------------
# 振幅不変形:
#   iα = (2/3) * ( ia - 0.5*ib - 0.5*ic )
#   iβ = (2/3) * ( (√3/2)*ib - (√3/2)*ic )
#      = (1/√3) * ( ib - ic )
# ---------------------------------------------------------------------------
def clarke(ia: FloatArray, ib: FloatArray, ic: FloatArray) -> tuple[FloatArray, FloatArray]:
    i_alpha = (2.0 / 3.0) * (ia - 0.5 * ib - 0.5 * ic)
    i_beta  = (1.0 / np.sqrt(3.0)) * (ib - ic)
    return i_alpha, i_beta


# ---------------------------------------------------------------------------
# 逆Clarke 変換: αβ → abc  (2相静止 → 3相静止)
# ---------------------------------------------------------------------------
#   ia =  iα
#   ib = -0.5*iα + (√3/2)*iβ
#   ic = -0.5*iα - (√3/2)*iβ
# ---------------------------------------------------------------------------
def inv_clarke(i_alpha: FloatArray, i_beta: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
    ia =  i_alpha
    ib = -0.5 * i_alpha + (np.sqrt(3.0) / 2.0) * i_beta
    ic = -0.5 * i_alpha - (np.sqrt(3.0) / 2.0) * i_beta
    return ia, ib, ic


# ---------------------------------------------------------------------------
# Park 変換: αβ → dq  (2相静止 → 2相回転)
# ---------------------------------------------------------------------------
#   id =  iα*cos(θe) + iβ*sin(θe)
#   iq = -iα*sin(θe) + iβ*cos(θe)
#   θe: 電気角 [rad]  (= Pn * 機械角)
# ---------------------------------------------------------------------------
def park(i_alpha: FloatArray, i_beta: FloatArray, theta_e: FloatArray) -> tuple[FloatArray, FloatArray]:
    cos_t = np.cos(theta_e)
    sin_t = np.sin(theta_e)
    i_d =  i_alpha * cos_t + i_beta * sin_t
    i_q = -i_alpha * sin_t + i_beta * cos_t
    return i_d, i_q


# ---------------------------------------------------------------------------
# 逆Park 変換: dq → αβ  (2相回転 → 2相静止)
# ---------------------------------------------------------------------------
#   iα = id*cos(θe) - iq*sin(θe)
#   iβ = id*sin(θe) + iq*cos(θe)
# ---------------------------------------------------------------------------
def inv_park(i_d: FloatArray, i_q: FloatArray, theta_e: FloatArray) -> tuple[FloatArray, FloatArray]:
    cos_t = np.cos(theta_e)
    sin_t = np.sin(theta_e)
    i_alpha = i_d * cos_t - i_q * sin_t
    i_beta  = i_d * sin_t + i_q * cos_t
    return i_alpha, i_beta


# ===========================================================================
# 単体動作確認 (後日 Cコードとの数値比較に使用)
# ===========================================================================
if __name__ == "__main__":
    # --- テスト条件 ---
    Im      = 10.0             # [A] 相電流の振幅
    f       = 50.0             # [Hz] 電気周波数
    omega_e = 2.0 * np.pi * f  # [rad/s] 電気角速度

    # 任意時刻 t における 3相平衡電流 (位相 0, -2π/3, -4π/3)
    t = 0.003  # [s]
    theta_e = omega_e * t

    ia = Im * np.cos(omega_e * t)
    ib = Im * np.cos(omega_e * t - 2.0 * np.pi / 3.0)
    ic = Im * np.cos(omega_e * t - 4.0 * np.pi / 3.0)

    # --- 1) Clarke 変換 ---
    i_alpha, i_beta = clarke(ia, ib, ic)

    # --- 2) Park 変換 ---
    i_d, i_q = park(i_alpha, i_beta, theta_e)

    # --- 3) 逆Park 変換 ---
    a2, b2 = inv_park(i_d, i_q, theta_e)

    # --- 4) 逆Clarke 変換 ---
    ia2, ib2, ic2 = inv_clarke(a2, b2)

    # --- 結果表示 ---
    print("=== Input (abc) ===")
    print(f"  ia = {ia:+.6f}, ib = {ib:+.6f}, ic = {ic:+.6f}")
    print("=== αβ ===")
    print(f"  i_alpha = {i_alpha:+.6f}, i_beta = {i_beta:+.6f}")
    print("=== dq  (θe = {:.4f} rad) ===".format(theta_e))
    print(f"  i_d = {i_d:+.6f}, i_q = {i_q:+.6f}")
    print("=== 往復復元 (inv_park → inv_clarke) ===")
    print(f"  ia' = {ia2:+.6f}, ib' = {ib2:+.6f}, ic' = {ic2:+.6f}")
    print("=== 復元誤差 ===")
    print(f"  |Δia| = {abs(ia-ia2):.2e}")
    print(f"  |Δib| = {abs(ib-ib2):.2e}")
    print(f"  |Δic| = {abs(ic-ic2):.2e}")

    # 期待値: 3相平衡電流を dq変換すると (id, iq) は時間によらず一定
    #         振幅不変形なら √(id^2 + iq^2) ≒ Im
    mag = np.sqrt(i_d**2 + i_q**2)
    print(f"\n  √(id² + iq²) = {mag:.6f}  (期待値: Im = {Im:.6f})")
