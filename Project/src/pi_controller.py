"""
pi_controller.py
BLDC モータ用 PI 制御器

W4-1 : 電流ループ PI (ACR: Automatic Current Regulator)
W4-2 : 速度ループ PI (ASR: Automatic Speed Regulator)

設計手法: 極配置法 (Pole Placement, 極零相殺)
─────────────────────────────────────────────────
d軸電流ループのプラント:
    Gd(s) = 1 / (Ld·s + Rs)
これに PI 制御器 C(s) = Kp + Ki/s を直列接続し、PI の零点で Gd の極を相殺する:
    Ki/Kp = Rs/Ld  →  開ループは Kp/(Ld·s) の純積分器
閉ループ伝達関数:
    G_cl(s) = (Kp/Ld) / (s + Kp/Ld) = 1 / (1 + s/ω_acr)
したがって 1次遅れ系の帯域 ω_acr は:
    Kp_d = ω_acr · Ld,   Ki_d = ω_acr · Rs
q軸も同様 (Ld → Lq):
    Kp_q = ω_acr · Lq,   Ki_q = ω_acr · Rs

非干渉化 (Decoupling):
─────────────────────────────────────────────────
d-q軸は ωe·Lq·iq / ωe·Ld·id / ωe·Ke の項で相互に干渉する。
PI出力に非干渉化項 (Feed-Forward) を加えると、d/q が独立した 1次遅れ系になる:
    vd_ref = PI_d + (-ωe·Lq·iq)          ← iq クロスカップリング打ち消し
    vq_ref = PI_q + ( ωe·Ld·id + ωe·Ke ) ← id カップリング + 逆起電力打ち消し
これにより、上記の極配置設計が厳密に成立する。

アンチワインドアップ:
─────────────────────────────────────────────────
インバータ電圧は Vdc により制限される (|v| ≤ Vdc/√3 程度)。
飽和が起きると積分器が暴走するため、「条件付き積分 (Clamping)」方式を採用:
  - 飽和していない   → 通常通り積分
  - 飽和中、かつ誤差が飽和方向と同符号 → 積分を止める (ワインドアップ防止)
  - 飽和中、逆符号   → 通常通り積分 (積分器を抜け出す方向)
"""

from __future__ import annotations
from dataclasses import dataclass

import numpy as np

from config import MotorConfig, motor_params


# ===========================================================================
# [WIP - 一時保留] 弱め界磁制御関連クラス
# ---------------------------------------------------------------------------
# 以下の MTPATable / FieldWeakeningController / CurrentRefGenerator /
# SpeedPIControllerTe / NumericalRefGenerator / _simulate_fw_loop は
# 弱め界磁制御を試験するために追加したが、無負荷ステップ時の
# (a) FW PI ワインドアップ + 位相反転
# (b) 高速域での制動トルク不能 (電圧制約)
# の組み合わせで暴走する問題があり、一旦保留。
# 既存テストには影響しない (呼び出さない限り無効)。
# 再開時は (1) 負荷ありシナリオでのチューニング, (2) ASR への AWR 連携,
# (3) id_fw 制限の物理根拠に基づく再設計 から進める想定。
# ===========================================================================


# ===========================================================================
# MTPA テーブル (Te* → (id*, iq*) 解析解の線形補間)
# ===========================================================================
class MTPATable:
    """
    IPM モータの MTPA (Maximum Torque Per Ampere) 曲線を
    電流振幅 I_s ∈ [0, I_max] でサンプリングし、Te ↔ (id, iq) の
    線形補間テーブルを構築する。

    MTPA 解析解 (IPM, Lq > Ld):
      sin β = (-Ke + √(Ke² + 8(Lq-Ld)²·I_s²)) / (4(Lq-Ld)·I_s)
      id = -I_s·sin β,   iq = I_s·cos β
    テーブルの Te は I_s に関して単調増加なので np.interp で直接参照可能。
    """

    def __init__(self, cfg: MotorConfig, n_points: int = 256) -> None:
        self.cfg = cfg
        I_s = np.linspace(0.0, cfg.I_max, n_points)
        dL = cfg.Lq - cfg.Ld                          # > 0 (IPM)
        # id_mtpa (I_s=0 では 0/0 になるので個別処理)
        id_arr = np.zeros_like(I_s)
        id_arr[1:] = (cfg.Ke - np.sqrt(cfg.Ke ** 2
                       + 8.0 * dL ** 2 * I_s[1:] ** 2)) / (4.0 * dL)
        iq_arr = np.sqrt(np.maximum(0.0, I_s ** 2 - id_arr ** 2))
        Te_arr = 1.5 * cfg.Pn * (cfg.Ke * iq_arr + (cfg.Ld - cfg.Lq) * id_arr * iq_arr)

        self.I_s = I_s
        self.id_arr = id_arr
        self.iq_arr = iq_arr
        self.Te_arr = Te_arr
        self.Te_max = float(Te_arr[-1])

    def lookup(self, Te_ref: float) -> tuple[float, float]:
        """指令トルク Te_ref [N·m] に対して (id*, iq*) を返す。負トルクは iq を反転。"""
        if Te_ref == 0.0:
            return 0.0, 0.0
        sign = 1.0 if Te_ref > 0.0 else -1.0
        Te_abs = min(abs(Te_ref), self.Te_max)
        id_ = float(np.interp(Te_abs, self.Te_arr, self.id_arr))
        iq_ = float(np.interp(Te_abs, self.Te_arr, self.iq_arr)) * sign
        return id_, iq_


# ===========================================================================
# 汎用 PI 制御器 (アンチワインドアップ付き)
# ===========================================================================
@dataclass
class PIController:
    Kp: float
    Ki: float
    out_min: float = -np.inf
    out_max: float = +np.inf
    integral: float = 0.0

    def reset(self) -> None:
        self.integral = 0.0

    def update(self, error: float, dt: float) -> float:
        """
        1 ステップ分の PI 演算 (Clamping 方式アンチワインドアップ)
          u = Kp * e + Ki * ∫e dt
        飽和中かつ e と飽和方向が同符号なら積分を停止する。
        """
        u_unsat = self.Kp * error + self.Ki * self.integral
        u_sat = max(self.out_min, min(self.out_max, u_unsat))

        saturated = (u_unsat != u_sat)
        # 飽和していない、あるいは誤差が飽和を抜け出す方向 → 積分する
        freeze = saturated and (error * (u_unsat - u_sat) > 0.0)
        if not freeze:
            self.integral += error * dt
        return u_sat


# ===========================================================================
# 電流ループ制御器 (ACR)
# ===========================================================================
class CurrentPIController:
    """
    d-q 軸電流ループ PI + 非干渉化 (Decoupling) 補償

    使用方法:
        acr = CurrentPIController(cfg, dt_ctrl=1e-4)
        vd, vq = acr.update(id_ref, iq_ref, id_meas, iq_meas, omega_e)
    """

    def __init__(
        self,
        cfg: MotorConfig = motor_params,
        dt_ctrl: float = 1.0e-4,     # 制御周期 100 μs (10 kHz)
        v_limit: float | None = None,
    ) -> None:
        self.cfg = cfg
        self.dt_ctrl = dt_ctrl

        # 電圧制限: デフォルトは六角形近似の半径 Vdc/√3
        if v_limit is None:
            v_limit = cfg.Vdc / np.sqrt(3.0)
        self.v_limit = v_limit

        # 極配置法によるゲイン
        w = cfg.W_acr
        self.pi_d = PIController(
            Kp=w * cfg.Ld,
            Ki=w * cfg.Rs,
            out_min=-v_limit,
            out_max=+v_limit,
        )
        self.pi_q = PIController(
            Kp=w * cfg.Lq,
            Ki=w * cfg.Rs,
            out_min=-v_limit,
            out_max=+v_limit,
        )

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.pi_d.reset()
        self.pi_q.reset()

    # ------------------------------------------------------------------
    def update(
        self,
        id_ref: float,
        iq_ref: float,
        id_meas: float,
        iq_meas: float,
        omega_e: float,
    ) -> tuple[float, float]:
        """1 ステップ分の ACR 演算。vd*, vq* を返す。"""
        c = self.cfg

        # --- PI 部 (素の偏差ベース) ---
        vd_pi = self.pi_d.update(id_ref - id_meas, self.dt_ctrl)
        vq_pi = self.pi_q.update(iq_ref - iq_meas, self.dt_ctrl)

        # --- 非干渉化 (Decoupling feed-forward) ---
        vd_ff = -omega_e * c.Lq * iq_meas
        vq_ff = +omega_e * c.Ld * id_meas + omega_e * c.Ke

        # --- 合成 & 電圧制限 (軸別クリップ) ---
        vd_ref = np.clip(vd_pi + vd_ff, -self.v_limit, +self.v_limit)
        vq_ref = np.clip(vq_pi + vq_ff, -self.v_limit, +self.v_limit)
        return float(vd_ref), float(vq_ref)


# ===========================================================================
# 弱め界磁制御器 (Field Weakening, 電圧余裕フィードバック型)
# ===========================================================================
class FieldWeakeningController:
    """
    電圧余裕フィードバック型の FW 制御器。

    入力: |v*| = √(vd*² + vq*²)   (前回の ACR 出力電圧ノルム)
    出力: id_fw ∈ [id_fw_min, 0]   (負 = 界磁を弱める方向)

    動作原理:
      err = |v*| − V_lim·margin
        err > 0 → 電圧オーバ  → id_fw を負側へ押す (界磁弱める)
        err < 0 → 余裕あり    → id_fw を 0 側へ戻す (非FW)

    下限 id_fw_min について:
      高速域で |v| を最小化する id は ≈ -Ich (特性電流)。
      それ以上負に振っても |v| は逆に増加するので、id_fw_min = -k·Ich (k=1.5 程度)
      に制限することでワインドアップと位相反転を防止する。

    アンチワインドアップ: Clamping 方式
      出力が飽和していて、かつ誤差がさらに飽和方向に押そうとしている場合、
      積分を停止する。
    """

    def __init__(
        self,
        cfg: MotorConfig,
        dt_ctrl: float = 1.0e-4,
        Kp: float = 0.10,           # [A/V]
        Ki: float = 80.0,           # [A/V/s]
        margin: float = 0.95,       # V_lim の何割を閾値に使うか
        id_fw_limit_factor: float = 1.5,  # |id_fw_min| = factor·Ich
    ) -> None:
        self.cfg = cfg
        self.dt_ctrl = dt_ctrl
        self.margin = margin
        self.v_thr = cfg.Vdc / np.sqrt(3.0) * margin
        self.Kp = Kp
        self.Ki = Ki

        Ich = cfg.Ke / cfg.Ld
        self.id_fw_min = -id_fw_limit_factor * Ich
        self.id_fw_max = 0.0

        self.integral = 0.0

    def reset(self) -> None:
        self.integral = 0.0

    def update(self, v_norm: float) -> float:
        e = v_norm - self.v_thr                  # > 0 で過電圧

        # 仮の積分更新
        integral_new = self.integral - self.Ki * e * self.dt_ctrl
        # 仮の出力 (比例 + 積分)
        u_unsat = -self.Kp * e + integral_new
        u_sat = max(self.id_fw_min, min(self.id_fw_max, u_unsat))

        # Clamping AWR:
        #   飽和 かつ 誤差が飽和方向へさらに押そうとしているなら積分を凍結
        saturated = (u_unsat != u_sat)
        freeze = False
        if saturated:
            # 下限飽和 (u_unsat < u_sat)→ e > 0 (さらに負へ押す方向) なら freeze
            if u_unsat < u_sat and e > 0.0:
                freeze = True
            # 上限飽和 (u_unsat > u_sat) → e < 0 (さらに正へ押す方向) なら freeze
            if u_unsat > u_sat and e < 0.0:
                freeze = True

        if not freeze:
            self.integral = integral_new
        return u_sat


# ===========================================================================
# 電流指令生成器 (MTPA + FW 統合)
# ===========================================================================
class CurrentRefGenerator:
    """
    Te* (ASR出力トルク指令) と前回 |v*| から (id*, iq*) を生成する統合器。

    手順:
      1) MTPA テーブル参照 : (id_mtpa, iq_mtpa) = MTPA(Te*)
      2) FW 制御器        : id_fw = FW(|v*|)
      3) id* = min(id_mtpa, id_fw)   (より負側を採用)
      4) iq* = iq_mtpa をクリップ   (id* が負に振られた分 iq 余裕あり)
                                    ただし電流円 √(I_max²-id²) を超えない
    """

    def __init__(
        self,
        cfg: MotorConfig = motor_params,
        dt_ctrl: float = 1.0e-4,
        fw_Kp: float = 0.30,
        fw_Ki: float = 300.0,
        fw_margin: float = 0.95,
    ) -> None:
        self.cfg = cfg
        self.mtpa = MTPATable(cfg)
        self.fw = FieldWeakeningController(
            cfg, dt_ctrl=dt_ctrl, Kp=fw_Kp, Ki=fw_Ki, margin=fw_margin
        )

    @property
    def Te_max(self) -> float:
        return self.mtpa.Te_max

    def reset(self) -> None:
        self.fw.reset()

    def update(self, Te_ref: float, v_norm: float) -> tuple[float, float, float, float]:
        """
        Returns
        -------
        id_ref, iq_ref, id_mtpa, id_fw : float
            後段ログのため MTPA と FW の内訳も一緒に返す。
        """
        id_mtpa, iq_mtpa = self.mtpa.lookup(Te_ref)
        id_fw = self.fw.update(v_norm)

        # より負側を採用
        id_ref = min(id_mtpa, id_fw)

        # 電流円による iq 制限
        I_max = self.cfg.I_max
        iq_lim = np.sqrt(max(0.0, I_max * I_max - id_ref * id_ref))
        iq_ref = float(np.clip(iq_mtpa, -iq_lim, +iq_lim))

        return float(id_ref), iq_ref, float(id_mtpa), float(id_fw)


# ===========================================================================
# 速度ループ制御器 (ASR)
# ===========================================================================
class SpeedPIController:
    """
    速度ループ PI (ASR) + 零点相殺プリフィルタ (オプション)

    設計:
      プラント:  Gm(s) = Kt / (J·s)    (ACR が十分速く iq ≈ iq_ref を仮定, 無摩擦)
      閉ループ:  2次標準形 s² + 2ζωn·s + ωn² を課す
                Kp_w = 2ζ·ω_asr·J/Kt
                Ki_w = ω_asr²·J/Kt
      標準値:    ζ = 1/√2 ≈ 0.707 (バタワース)

    ただし PI の構造から閉ループに零点 s=-Ki/Kp が残り、
    ステップ応答のオーバーシュートが理論値 (4.3%) より大きくなる。

    対策: 指令値側に 1次遅れプリフィルタを挿入して零点を相殺する。
        F(s) = 1 / (1 + τ_f·s),  τ_f = Kp/Ki = 2ζ/ω_asr
      合成後:  F·G_cl = ω_n²/(s² + 2ζω_n·s + ω_n²)  ← 純粋な2次系
      離散化 (Forward Euler):
        ω_ref_f ← ω_ref_f + (dt/τ_f)·(ω_ref - ω_ref_f)

    出力制限:
      ASR 出力は iq 指令そのものなので ±I_max でクリップ。
      id = 0 固定 (弱め界磁なし) を前提とし、iq に全電流余裕を割り当てる。
    """

    def __init__(
        self,
        cfg: MotorConfig = motor_params,
        dt_ctrl: float = 1.0e-3,    # 1 ms (1 kHz) ← ACR の 10 倍周期
        zeta: float = 1.0 / np.sqrt(2.0),
        use_prefilter: bool = True,
    ) -> None:
        self.cfg = cfg
        self.dt_ctrl = dt_ctrl
        self.use_prefilter = use_prefilter

        Kt = 1.5 * cfg.Pn * cfg.Ke
        w = cfg.W_asr
        Kp = 2.0 * zeta * w * cfg.J / Kt
        Ki = (w ** 2) * cfg.J / Kt

        self.pi = PIController(
            Kp=Kp,
            Ki=Ki,
            out_min=-cfg.I_max,
            out_max=+cfg.I_max,
        )
        self.Kp = Kp
        self.Ki = Ki

        # --- プリフィルタ (1次遅れ) 状態 ---
        # 零点 -Ki/Kp を相殺する時定数 τ_f = Kp/Ki
        self.tau_f = Kp / Ki
        self.omega_ref_f = 0.0  # フィルタ後の指令値

    def reset(self) -> None:
        self.pi.reset()
        self.omega_ref_f = 0.0

    def update(self, omega_ref: float, omega_meas: float) -> float:
        """速度偏差から iq 指令値 (id=0 固定) を生成"""
        if self.use_prefilter:
            # 1次遅れプリフィルタ (Forward Euler で更新)
            alpha = self.dt_ctrl / self.tau_f
            self.omega_ref_f += alpha * (omega_ref - self.omega_ref_f)
            ref = self.omega_ref_f
        else:
            ref = omega_ref

        iq_ref = self.pi.update(ref - omega_meas, self.dt_ctrl)
        return iq_ref

    @property
    def filtered_ref(self) -> float:
        return self.omega_ref_f


# ===========================================================================
# 速度ループ制御器 (Te* 出力版, FW 併用時に使う)
# ===========================================================================
class SpeedPIControllerTe:
    """
    Te* (トルク指令) を出力する ASR。

    プラント:  Gm(s) = 1/(J·s)   (ACR が瞬時に Te を追従すると仮定)
      → 2次標準形: s² + 2ζω·s + ω² = 0
        Kp_w = 2ζ·ω_asr·J
        Ki_w = ω_asr²·J
      (iq 版の Kp/Kt・Ki/Kt から Kt 除去)

    出力制限: ±Te_max   (= MTPA@I_max, CurrentRefGenerator から取得可能)

    プリフィルタと Clamping AWR は iq 版と同じ構造。
    """

    def __init__(
        self,
        cfg: MotorConfig = motor_params,
        dt_ctrl: float = 1.0e-3,
        zeta: float = 1.0 / np.sqrt(2.0),
        Te_max: float | None = None,
        use_prefilter: bool = True,
    ) -> None:
        self.cfg = cfg
        self.dt_ctrl = dt_ctrl
        self.use_prefilter = use_prefilter

        # Te_max: 未指定なら MTPA@I_max を計算
        if Te_max is None:
            dL = cfg.Lq - cfg.Ld
            id_m = (cfg.Ke - np.sqrt(cfg.Ke ** 2 + 8.0 * dL ** 2 * cfg.I_max ** 2)) / (4.0 * dL)
            iq_m = np.sqrt(cfg.I_max ** 2 - id_m ** 2)
            Te_max = 1.5 * cfg.Pn * (cfg.Ke * iq_m + (cfg.Ld - cfg.Lq) * id_m * iq_m)
        self.Te_max = float(Te_max)

        w = cfg.W_asr
        Kp = 2.0 * zeta * w * cfg.J
        Ki = (w ** 2) * cfg.J

        self.pi = PIController(
            Kp=Kp, Ki=Ki,
            out_min=-self.Te_max, out_max=+self.Te_max,
        )
        self.Kp = Kp
        self.Ki = Ki

        self.tau_f = Kp / Ki       # 零点相殺時定数 (= 2ζ/ω_asr)
        self.omega_ref_f = 0.0

    def reset(self) -> None:
        self.pi.reset()
        self.omega_ref_f = 0.0

    def update(self, omega_ref: float, omega_meas: float) -> float:
        if self.use_prefilter:
            alpha = self.dt_ctrl / self.tau_f
            self.omega_ref_f += alpha * (omega_ref - self.omega_ref_f)
            ref = self.omega_ref_f
        else:
            ref = omega_ref
        return self.pi.update(ref - omega_meas, self.dt_ctrl)

    @property
    def filtered_ref(self) -> float:
        return self.omega_ref_f


# ===========================================================================
# 純粋オンライン最適化型 電流指令生成 (比較用, scipy SLSQP)
# ===========================================================================
class NumericalRefGenerator:
    """
    制御周期ごとに scipy.optimize (SLSQP) で (id*, iq*) を解く「純粋オンライン最適化」版。

    問題:
      minimize   id² + iq²                 (= 銅損最小 = MTPA に一致)
      s.t.       Te(id, iq) ≥ Te_ref
                 id² + iq² ≤ I_max²
                 vd² + vq² ≤ V_lim²        (定常仮定: vd/vq は (id,iq,ωe) の代数式)

    Te_ref が達成不可能 (電圧制約で届かない) なら、
      maximize   Te(id, iq)   with same constraints
    にフォールバック。

    注: マイコンには非現実的な計算量。あくまでシミュレーションで
       解析MTPA+FW (CurrentRefGenerator) の精度を比較するベンチマーク用。
    """

    def __init__(self, cfg: MotorConfig = motor_params) -> None:
        self.cfg = cfg
        self.V_lim = cfg.Vdc / np.sqrt(3.0)
        self.x_warm = np.array([-1.0, 5.0])
        # Te_max (参考)
        dL = cfg.Lq - cfg.Ld
        id_m = (cfg.Ke - np.sqrt(cfg.Ke ** 2 + 8.0 * dL ** 2 * cfg.I_max ** 2)) / (4.0 * dL)
        iq_m = np.sqrt(cfg.I_max ** 2 - id_m ** 2)
        self.Te_max = float(1.5 * cfg.Pn * (cfg.Ke * iq_m + (cfg.Ld - cfg.Lq) * id_m * iq_m))

    def reset(self) -> None:
        self.x_warm = np.array([-1.0, 5.0])

    # 内部: (id, iq) のトルク & 電圧ノルム²
    def _te(self, x: np.ndarray) -> float:
        c = self.cfg
        return 1.5 * c.Pn * (c.Ke * x[1] + (c.Ld - c.Lq) * x[0] * x[1])

    def _vn2(self, x: np.ndarray, omega_e: float) -> float:
        c = self.cfg
        vd = c.Rs * x[0] - omega_e * c.Lq * x[1]
        vq = c.Rs * x[1] + omega_e * c.Ld * x[0] + omega_e * c.Ke
        return vd * vd + vq * vq

    def solve(self, Te_ref: float, omega_e: float) -> tuple[float, float]:
        from scipy.optimize import minimize

        if abs(Te_ref) < 1e-6:
            return 0.0, 0.0
        sign = 1.0 if Te_ref > 0.0 else -1.0
        Te_abs = min(abs(Te_ref), self.Te_max)
        c = self.cfg
        V2 = self.V_lim ** 2
        I2 = c.I_max ** 2

        cons_A = [
            {"type": "ineq", "fun": lambda x: self._te(x) - Te_abs},
            {"type": "ineq", "fun": lambda x: I2 - (x[0] ** 2 + x[1] ** 2)},
            {"type": "ineq", "fun": lambda x: V2 - self._vn2(x, omega_e)},
        ]
        bounds = [(-c.I_max, 0.0), (0.0, c.I_max)]

        # ① Te=Te_ref を満たす最小電流解 (feasible なら MTPA に一致)
        x0 = self.x_warm.copy()
        res = minimize(
            fun=lambda x: x[0] ** 2 + x[1] ** 2,
            x0=x0, jac=lambda x: np.array([2.0 * x[0], 2.0 * x[1]]),
            method="SLSQP", bounds=bounds, constraints=cons_A,
            options={"ftol": 1e-9, "maxiter": 200},
        )
        if res.success and self._te(res.x) >= Te_abs - 1e-3:
            self.x_warm = res.x
            return float(res.x[0]), float(res.x[1]) * sign

        # ② フォールバック: 電流/電圧制約下で最大 Te
        cons_B = cons_A[1:]

        # マルチスタート (plot_nt_curve.py と同じ戦略)
        starts: list[np.ndarray] = [self.x_warm]
        dL = c.Lq - c.Ld
        id_m = (c.Ke - np.sqrt(c.Ke ** 2 + 8.0 * dL ** 2 * I2)) / (4.0 * dL)
        iq_m = np.sqrt(max(0.0, I2 - id_m ** 2))
        starts.append(np.array([id_m, iq_m]))
        for frac in (0.4, 0.7, 0.9):
            id_try = -c.I_max * frac
            iq_try = np.sqrt(max(0.0, I2 - id_try ** 2))
            starts.append(np.array([id_try, iq_try]))

        best_Te = -np.inf
        best_x = np.array([0.0, 0.0])
        for x0 in starts:
            x0c = np.clip(x0, [bounds[0][0], bounds[1][0]], [bounds[0][1], bounds[1][1]])
            try:
                r = minimize(
                    fun=lambda x: -self._te(x),
                    x0=x0c,
                    jac=lambda x: -np.array([
                        1.5 * c.Pn * (c.Ld - c.Lq) * x[1],
                        1.5 * c.Pn * (c.Ke + (c.Ld - c.Lq) * x[0]),
                    ]),
                    method="SLSQP", bounds=bounds, constraints=cons_B,
                    options={"ftol": 1e-9, "maxiter": 200},
                )
            except Exception:
                continue
            if not r.success:
                continue
            if I2 - (r.x[0] ** 2 + r.x[1] ** 2) < -1e-4:
                continue
            if V2 - self._vn2(r.x, omega_e) < -1e-4:
                continue
            Te_here = self._te(r.x)
            if Te_here > best_Te:
                best_Te = Te_here
                best_x = r.x
        if best_Te > 0.0:
            self.x_warm = best_x
            return float(best_x[0]), float(best_x[1]) * sign
        return 0.0, 0.0


# ===========================================================================
# 閉ループシミュレーション (電流ループのみ、W4-1 用)
# ===========================================================================
def _simulate_current_loop(
    id_ref: float = 0.0,
    iq_ref: float = 20.0,
    T_sim: float = 0.05,
    dt: float = 1.0e-5,      # シミュ積分ステップ 10 μs
    dt_ctrl: float = 1.0e-4, # 制御周期 100 μs
):
    """
    電流ループ PI の閉ループ動作検証。
    モータは motor_model.py (RK4) を真値モデルとして使用。
    """
    from motor_model import BLDCMotor

    motor = BLDCMotor()
    ctrl = CurrentPIController(motor_params, dt_ctrl=dt_ctrl)

    N = int(T_sim / dt)
    ratio = int(round(dt_ctrl / dt))  # = 10

    # ログ
    t     = np.zeros(N)
    log_id = np.zeros(N)
    log_iq = np.zeros(N)
    log_wm = np.zeros(N)
    log_vd = np.zeros(N)
    log_vq = np.zeros(N)
    log_Te = np.zeros(N)

    vd_cmd, vq_cmd = 0.0, 0.0

    for k in range(N):
        # 制御器の更新は ratio ステップに1回
        if k % ratio == 0:
            omega_e = motor_params.Pn * motor.omega_m
            vd_cmd, vq_cmd = ctrl.update(
                id_ref, iq_ref, motor.id, motor.iq, omega_e
            )
        # モータは常に細かい dt で積分
        motor.step_rk4(vd_cmd, vq_cmd, dt)

        t[k]      = (k + 1) * dt
        log_id[k] = motor.id
        log_iq[k] = motor.iq
        log_wm[k] = motor.omega_m
        log_vd[k] = vd_cmd
        log_vq[k] = vq_cmd
        log_Te[k] = motor.electric_torque(motor.id, motor.iq)

    return t, log_id, log_iq, log_wm, log_vd, log_vq, log_Te


def _simulate_speed_loop(
    omega_ref: float = 50.0,
    T_sim: float = 0.3,
    dt: float = 1.0e-5,         # 10 μs シミュ積分
    dt_ctrl_acr: float = 1.0e-4, # 100 μs 電流ループ
    dt_ctrl_asr: float = 1.0e-3, # 1 ms 速度ループ
    TL_step_time: float | None = None,
    TL_amp: float = 0.0,
    use_prefilter: bool = True,
):
    """
    ASR + ACR カスケード制御の閉ループシミュレーション。

    Parameters
    ----------
    omega_ref : float
        速度指令値 [rad/s] (ステップ入力)
    TL_step_time : float | None
        負荷トルクを印加する時刻 [s] (None なら負荷なし)
    TL_amp : float
        負荷トルク振幅 [N·m]
    """
    from motor_model import BLDCMotor

    motor = BLDCMotor()
    asr = SpeedPIController(
        motor_params, dt_ctrl=dt_ctrl_asr, use_prefilter=use_prefilter
    )
    acr = CurrentPIController(motor_params, dt_ctrl=dt_ctrl_acr)

    N = int(T_sim / dt)
    ratio_acr = int(round(dt_ctrl_acr / dt))    # 10
    ratio_asr = int(round(dt_ctrl_asr / dt))    # 100

    t       = np.zeros(N)
    log_id  = np.zeros(N)
    log_iq  = np.zeros(N)
    log_iq_ref = np.zeros(N)
    log_wm  = np.zeros(N)
    log_wref = np.zeros(N)
    log_wref_f = np.zeros(N)
    log_vd  = np.zeros(N)
    log_vq  = np.zeros(N)
    log_Te  = np.zeros(N)
    log_TL  = np.zeros(N)

    id_ref = 0.0
    iq_ref = 0.0
    vd_cmd, vq_cmd = 0.0, 0.0

    for k in range(N):
        tk = k * dt

        # --- 負荷トルク ---
        TL = TL_amp if (TL_step_time is not None and tk >= TL_step_time) else 0.0

        # --- 速度ループ (1 ms 周期) ---
        if k % ratio_asr == 0:
            iq_ref = asr.update(omega_ref, motor.omega_m)

        # --- 電流ループ (100 μs 周期) ---
        if k % ratio_acr == 0:
            omega_e = motor_params.Pn * motor.omega_m
            vd_cmd, vq_cmd = acr.update(
                id_ref, iq_ref, motor.id, motor.iq, omega_e
            )

        # --- モータ積分 ---
        motor.step_rk4(vd_cmd, vq_cmd, dt, TL=TL)

        t[k]         = (k + 1) * dt
        log_id[k]    = motor.id
        log_iq[k]    = motor.iq
        log_iq_ref[k] = iq_ref
        log_wm[k]    = motor.omega_m
        log_wref[k]  = omega_ref
        log_wref_f[k] = asr.filtered_ref
        log_vd[k]    = vd_cmd
        log_vq[k]    = vq_cmd
        log_Te[k]    = motor.electric_torque(motor.id, motor.iq)
        log_TL[k]    = TL

    return dict(
        t=t, id_=log_id, iq=log_iq, iq_ref=log_iq_ref,
        wm=log_wm, wref=log_wref, wref_f=log_wref_f,
        vd=log_vd, vq=log_vq,
        Te=log_Te, TL=log_TL,
    )


def _simulate_fw_loop(
    omega_ref: float = 150.0,
    T_sim: float = 0.5,
    dt: float = 1.0e-5,
    dt_ctrl_acr: float = 1.0e-4,
    dt_ctrl_asr: float = 1.0e-3,
    mode: str = "analytic",           # "analytic" (MTPA+FW) or "numerical" (SLSQP)
    numerical_rate: float = 1.0e-3,   # SLSQP 呼び出し周期 (mode="numerical" のみ)
    TL_step_time: float | None = None,
    TL_amp: float = 0.0,
    use_prefilter: bool = True,
):
    """
    ASR(Te*) + [MTPA+FW / Numerical] + ACR カスケードの FW 対応シミュレーション。

    mode:
      "analytic"  : MTPA テーブル + 電圧余裕 FB FW (マイコン実装可)
      "numerical" : scipy SLSQP を毎 numerical_rate 秒で呼び出し最適解 (参考)
    """
    from motor_model import BLDCMotor

    motor = BLDCMotor()
    asr = SpeedPIControllerTe(
        motor_params, dt_ctrl=dt_ctrl_asr, use_prefilter=use_prefilter
    )
    acr = CurrentPIController(motor_params, dt_ctrl=dt_ctrl_acr)

    if mode == "analytic":
        ref_gen = CurrentRefGenerator(motor_params, dt_ctrl=dt_ctrl_acr)
    elif mode == "numerical":
        ref_gen = NumericalRefGenerator(motor_params)
    else:
        raise ValueError(f"unknown mode: {mode}")

    N = int(T_sim / dt)
    ratio_acr = int(round(dt_ctrl_acr / dt))
    ratio_asr = int(round(dt_ctrl_asr / dt))
    ratio_num = int(round(numerical_rate / dt)) if mode == "numerical" else ratio_acr

    t_log       = np.zeros(N)
    log_id      = np.zeros(N)
    log_iq      = np.zeros(N)
    log_id_ref  = np.zeros(N)
    log_iq_ref  = np.zeros(N)
    log_id_mtpa = np.zeros(N)
    log_id_fw   = np.zeros(N)
    log_wm      = np.zeros(N)
    log_wref    = np.zeros(N)
    log_Te_ref  = np.zeros(N)
    log_vd      = np.zeros(N)
    log_vq      = np.zeros(N)
    log_vnorm   = np.zeros(N)
    log_Te      = np.zeros(N)
    log_TL      = np.zeros(N)

    Te_ref = 0.0
    id_ref = 0.0
    iq_ref = 0.0
    id_mtpa_last = 0.0
    id_fw_last = 0.0
    vd_cmd, vq_cmd = 0.0, 0.0
    v_norm = 0.0

    for k in range(N):
        tk = k * dt
        TL = TL_amp if (TL_step_time is not None and tk >= TL_step_time) else 0.0

        # --- 速度ループ (1 ms) ---
        if k % ratio_asr == 0:
            Te_ref = asr.update(omega_ref, motor.omega_m)

        # --- 電流指令生成 ---
        if mode == "analytic":
            if k % ratio_acr == 0:
                id_ref, iq_ref, id_mtpa_last, id_fw_last = ref_gen.update(Te_ref, v_norm)
        else:
            if k % ratio_num == 0:
                omega_e_tmp = motor_params.Pn * motor.omega_m
                id_ref, iq_ref = ref_gen.solve(Te_ref, omega_e_tmp)

        # --- 電流ループ (100 μs) ---
        if k % ratio_acr == 0:
            omega_e = motor_params.Pn * motor.omega_m
            vd_cmd, vq_cmd = acr.update(
                id_ref, iq_ref, motor.id, motor.iq, omega_e
            )
            v_norm = float(np.sqrt(vd_cmd * vd_cmd + vq_cmd * vq_cmd))

        # --- モータ積分 ---
        motor.step_rk4(vd_cmd, vq_cmd, dt, TL=TL)

        t_log[k]       = (k + 1) * dt
        log_id[k]      = motor.id
        log_iq[k]      = motor.iq
        log_id_ref[k]  = id_ref
        log_iq_ref[k]  = iq_ref
        log_id_mtpa[k] = id_mtpa_last
        log_id_fw[k]   = id_fw_last
        log_wm[k]      = motor.omega_m
        log_wref[k]    = omega_ref
        log_Te_ref[k]  = Te_ref
        log_vd[k]      = vd_cmd
        log_vq[k]      = vq_cmd
        log_vnorm[k]   = v_norm
        log_Te[k]      = motor.electric_torque(motor.id, motor.iq)
        log_TL[k]      = TL

    return dict(
        t=t_log, id_=log_id, iq=log_iq,
        id_ref=log_id_ref, iq_ref=log_iq_ref,
        id_mtpa=log_id_mtpa, id_fw=log_id_fw,
        wm=log_wm, wref=log_wref,
        Te_ref=log_Te_ref, Te=log_Te, TL=log_TL,
        vd=log_vd, vq=log_vq, vnorm=log_vnorm,
    )


def _simulate_mtpa_loop(
    omega_ref: float = 50.0,
    T_sim: float = 0.5,
    dt: float = 1.0e-5,
    dt_ctrl_acr: float = 1.0e-4,
    dt_ctrl_asr: float = 1.0e-3,
    mode: str = "mtpa",            # "mtpa" or "id0"
    TL_step_time: float | None = None,
    TL_amp: float = 0.0,
    use_prefilter: bool = True,
):
    """
    ASR(Te*) + [MTPA LUT or id=0] + ACR カスケードの MTPA 比較用シミュレーション。

    FW は使わない (定トルク領域での比較が目的)。
    ASR は両モード共通で Te*[N·m] を出力するため、上限 Te_max だけが異なる:
      mode="id0"  : Te_max = Kt · I_max = 1.5·Pn·Ke·I_max  (≈17.88 N·m)
      mode="mtpa" : Te_max = MTPA@I_max                    (≈42.07 N·m)
    """
    from motor_model import BLDCMotor

    motor = BLDCMotor()
    cfg = motor_params
    Kt = 1.5 * cfg.Pn * cfg.Ke

    mtpa = MTPATable(cfg)
    if mode == "mtpa":
        Te_max = mtpa.Te_max
    elif mode == "id0":
        Te_max = Kt * cfg.I_max
    else:
        raise ValueError(f"unknown mode: {mode}")

    asr = SpeedPIControllerTe(
        cfg, dt_ctrl=dt_ctrl_asr, Te_max=Te_max, use_prefilter=use_prefilter,
    )
    acr = CurrentPIController(cfg, dt_ctrl=dt_ctrl_acr)

    N = int(T_sim / dt)
    ratio_acr = int(round(dt_ctrl_acr / dt))
    ratio_asr = int(round(dt_ctrl_asr / dt))

    t_log      = np.zeros(N)
    log_id     = np.zeros(N)
    log_iq     = np.zeros(N)
    log_id_ref = np.zeros(N)
    log_iq_ref = np.zeros(N)
    log_wm     = np.zeros(N)
    log_wref   = np.zeros(N)
    log_Te_ref = np.zeros(N)
    log_Te     = np.zeros(N)
    log_TL     = np.zeros(N)
    log_vd     = np.zeros(N)
    log_vq     = np.zeros(N)
    log_Is     = np.zeros(N)        # |I| = √(id²+iq²)

    Te_ref = 0.0
    id_ref = 0.0
    iq_ref = 0.0
    vd_cmd = 0.0
    vq_cmd = 0.0

    for k in range(N):
        tk = k * dt
        TL = TL_amp if (TL_step_time is not None and tk >= TL_step_time) else 0.0

        # --- 速度ループ (1 ms): Te* 出力 ---
        if k % ratio_asr == 0:
            Te_ref = asr.update(omega_ref, motor.omega_m)

        # --- 電流指令生成 + 電流ループ (100 μs) ---
        if k % ratio_acr == 0:
            if mode == "mtpa":
                id_ref, iq_ref = mtpa.lookup(Te_ref)
            else:  # "id0"
                id_ref = 0.0
                iq_ref = float(np.clip(Te_ref / Kt, -cfg.I_max, +cfg.I_max))

            omega_e = cfg.Pn * motor.omega_m
            vd_cmd, vq_cmd = acr.update(
                id_ref, iq_ref, motor.id, motor.iq, omega_e
            )

        motor.step_rk4(vd_cmd, vq_cmd, dt, TL=TL)

        t_log[k]      = (k + 1) * dt
        log_id[k]     = motor.id
        log_iq[k]     = motor.iq
        log_id_ref[k] = id_ref
        log_iq_ref[k] = iq_ref
        log_wm[k]     = motor.omega_m
        log_wref[k]   = omega_ref
        log_Te_ref[k] = Te_ref
        log_Te[k]     = motor.electric_torque(motor.id, motor.iq)
        log_TL[k]     = TL
        log_vd[k]     = vd_cmd
        log_vq[k]     = vq_cmd
        log_Is[k]     = float(np.hypot(motor.id, motor.iq))

    return dict(
        t=t_log, id_=log_id, iq=log_iq,
        id_ref=log_id_ref, iq_ref=log_iq_ref,
        wm=log_wm, wref=log_wref,
        Te_ref=log_Te_ref, Te=log_Te, TL=log_TL,
        vd=log_vd, vq=log_vq, Is=log_Is,
        Te_max=Te_max,
    )


def _print_metrics(t, id_, iq_, id_ref, iq_ref):
    # 整定時間 (iq が 指令 ±2% 内に入る最初の時刻)
    band = 0.02 * abs(iq_ref)
    inside = np.abs(iq_ - iq_ref) <= band
    if np.any(inside):
        # 連続して外に出ないことを保証するため後から走査
        idx_settle = None
        for i in range(len(inside)):
            if inside[i] and np.all(inside[i:]):
                idx_settle = i
                break
        t_settle = t[idx_settle] if idx_settle is not None else np.nan
    else:
        t_settle = np.nan

    overshoot = (iq_.max() - iq_ref) / iq_ref * 100.0 if iq_ref != 0 else 0.0
    ss_err_iq = iq_[-1] - iq_ref
    ss_err_id = id_[-1] - id_ref

    print("─── W4-1 Current Loop Metrics ───")
    print(f"  iq_ref       = {iq_ref:.2f} A   (id_ref = {id_ref:.2f} A)")
    print(f"  iq peak      = {iq_.max():.3f} A  @ t = {t[iq_.argmax()]*1e3:.2f} ms")
    print(f"  overshoot    = {overshoot:+.2f} %")
    print(f"  settling ±2% = {t_settle*1e3:.2f} ms" if not np.isnan(t_settle)
          else "  settling ±2% = (not yet)")
    print(f"  SS error iq  = {ss_err_iq:+.4e} A")
    print(f"  SS error id  = {ss_err_id:+.4e} A")


if __name__ == "__main__":
    print("=============================================")
    print("W4-1: 電流ループPI制御 閉ループ動作確認")
    print("=============================================")
    cfg = motor_params
    w = cfg.W_acr
    Kt = 1.5 * cfg.Pn * cfg.Ke
    print(f"  Vdc      = {cfg.Vdc} V,  V_limit = {cfg.Vdc/np.sqrt(3):.2f} V")
    print(f"  Kt       = {Kt:.3f} N·m/A")
    print(f"  ω_acr    = {w} rad/s ({w/(2*np.pi):.1f} Hz)")
    print(f"  Kp_d     = {w*cfg.Ld:.3f},  Ki_d = {w*cfg.Rs:.3f}")
    print(f"  Kp_q     = {w*cfg.Lq:.3f},  Ki_q = {w*cfg.Rs:.3f}")
    print()

    id_ref, iq_ref = 0.0, 20.0
    t, id_, iq_, wm, vd, vq, Te = _simulate_current_loop(id_ref, iq_ref)
    _print_metrics(t, id_, iq_, id_ref, iq_ref)

    print("\n  t[ms]  | id[A]   iq[A]   ωm[rad/s]  vd[V]  vq[V]  Te[N·m]")
    for k in [9, 99, 499, 999, 2499, len(t) - 1]:
        print(f"  {t[k]*1e3:6.2f} | "
              f"{id_[k]:+6.3f}  {iq_[k]:+6.3f}  "
              f"{wm[k]:+8.2f}  "
              f"{vd[k]:+7.2f} {vq[k]:+7.2f}  "
              f"{Te[k]:+6.3f}")

    # ------------------------------------------------------------------
    # W4-2: 速度ループ ASR + 電流ループ ACR の カスケード動作確認
    # ------------------------------------------------------------------
    print("\n=============================================")
    print("W4-2: 速度ループPI (ASR+ACR カスケード) 動作確認")
    print("=============================================")
    asr = SpeedPIController(cfg)
    print(f"  ω_asr  = {cfg.W_asr} rad/s ({cfg.W_asr/(2*np.pi):.2f} Hz)")
    print(f"  ζ       = {1/np.sqrt(2):.3f}  (バタワース標準形)")
    print(f"  Kp_w   = {asr.Kp:.4f}")
    print(f"  Ki_w   = {asr.Ki:.4f}")
    print(f"  ASR 更新周期 = {asr.dt_ctrl*1e3:.1f} ms")
