# PLECS経験者向け Python/制御実装 移行ガイド
## BLDC モータ制御のための PLECS → MuJoCo/Python 移行ルート

**対象者**: パワーエレクトロニクス（モータドライブ制御）修士、PLECS経験者、Python/MuJoCo未経験
**目的**: 3ヶ月で「MuJoCoでBLDCモータ制御シミュレーション + RLでPID超え」をGitHub公開

---

## 1. PLECSとMuJoCoの概念対応表

### 1.1 根本的な思想の違い

| 観点 | PLECS | MuJoCo |
|:---|:---|:---|
| **設計思想** | 回路・信号フローベースのシミュレータ | 剛体力学ベースの物理シミュレータ |
| **モデリング対象** | 電気回路（V, I, R, L, C, スイッチ） | 剛体・関節・アクチュエータ（位置, 速度, トルク） |
| **時間ステップ** | 可変ステップ、μs～ns精度（PWMスイッチング解析） | 固定ステップ、ms精度（機械ダイナミクス解析） |
| **因果律** | 非因果的（回路方程式を自動求解）+ 信号フロー | 順方向物理シミュレーション（力/トルク → 加速度 → 速度 → 位置） |
| **入力** | 信号（参照値、ゲート信号） | アクチュエータ制御入力（トルク、位置、速度） |
| **出力** | 波形（電圧、電流、電力） | 状態量（関節角度、角速度、センサ値） |

### 1.2 コンポーネント対応表

| PLECSコンポーネント | 役割（PLECS） | MuJoCoでの対応 | 備考 |
|:---|:---|:---|:---|
| **電圧源 (V source)** | 電圧を印加 | `actuator` (motor) の制御入力 | MuJoCoでは「トルク」として抽象化 |
| **電流源 (I source)** | 電流を注入 | `actuator` の force/torque | 直接対応はない |
| **抵抗 R** | 電気的損失 | `damping` (関節の粘性摩擦) | 機械的損失に対応 |
| **インダクタンス L** | 電流の慣性 | `armature` (ロータ慣性) | 回転慣性 `inertia` に対応 |
| **キャパシタンス C** | 電荷蓄積 | （直接対応なし） | DCリンクCはPython側で計算 |
| **IGBT/MOSFETスイッチ** | インバータスイッチング | （MuJoCoでは扱わない） | Python側でインバータモデルを実装 |
| **ダイオード** | 整流 | （MuJoCoでは扱わない） | Python側で実装 |
| **PIDコントローラ** | フィードバック制御 | Python クラスとして実装 | 後述の `PIDController` クラス |
| **PWM変調器** | スイッチング信号生成 | Python関数として実装 | SVPWM等はPython側 |
| **スコープ / プローブ** | 波形観測 | Matplotlib / MuJoCo Viewer | リアルタイム可視化も可能 |
| **Cブロック（PLECS C Script）** | カスタムロジック | Python関数/クラス | 移行が最も直接的 |

### 1.3 シミュレーション時間ステップの違い

```
PLECS の世界:
  ┌─────────────────────────────────────────────────┐
  │ スイッチングイベント検出 → 可変ステップソルバ      │
  │ 典型的ステップ: 100ns～1μs                       │
  │ PWM周波数: 10kHz～100kHz (周期: 10μs～100μs)      │
  │ シミュレーション時間: 数ms～数秒                   │
  └─────────────────────────────────────────────────┘

MuJoCo の世界:
  ┌─────────────────────────────────────────────────┐
  │ 固定タイムステップ（Euler or RK4）                │
  │ 典型的ステップ: 0.5ms～5ms (timestep = 0.0005)    │
  │ 制御ループ: 500Hz（RL行動頻度 = 2ms）             │
  │ シミュレーション時間: 数秒～数分（リアルタイム）     │
  └─────────────────────────────────────────────────┘

Python（電気的モデル）で埋める領域:
  ┌─────────────────────────────────────────────────┐
  │ PLECSの電気的ダイナミクス（高速）を               │
  │ Pythonで離散化して計算                             │
  │ → MuJoCoのステップ間に複数回実行（サブステップ）   │
  │ 例: MuJoCo 0.5ms ステップの間に、電気モデルを      │
  │     10μsで50回計算                                │
  └─────────────────────────────────────────────────┘

タイムステップ階層（RL専門家との合意済み）:
  ┌─────────────────────────────────────────────────┐
  │ 電気モデルサブステップ: 10μs                       │
  │ MuJoCo内部ステップ:    0.5ms (timestep=0.0005)    │
  │ RL制御周期:            2ms   (n_substeps=4)       │
  │                                                   │
  │ 根拠: BLDCの電気時定数 L/R ≈ 1.6ms              │
  │ → RL周期2msで電流応答の1サイクル以上を観測可能    │
  │ → 制御性能と学習効率のバランスが最適               │
  └─────────────────────────────────────────────────┘
```

### 1.4 信号フロー思考 vs 物理シミュレーション思考

**PLECSでの信号フロー（慣れている考え方）**:
```
速度指令 → [PID] → 電流指令(iq*) → [電流PI] → 電圧指令(Vq*) → [SVPWM] → [インバータ] → [モータ] → 速度
               ↑                       ↑                                            │
               └───── 速度FB ───────────┘───── 電流FB ──────────────────────────────┘
```

**MuJoCo + Pythonでの構成（これから学ぶ考え方）**:
```
┌──────── Python 側（制御 + 電気モデル）─────────┐    ┌─── MuJoCo 側（機械モデル）──┐
│                                                │    │                              │
│  速度指令 → [PID] → iq* → [電流PI] → Vq*      │    │  トルク → [剛体力学]          │
│       ↑              ↑                         │    │         → 角速度, 角度        │
│       │              │    [電気モデル]           │    │         → 負荷, 摩擦          │
│   速度FB          電流FB   Vq → iq → トルク ───┼──→│                              │
│       │              │          ↑               │    │                              │
│       └──────────────┴──────────┼───────────────│←──│  角速度（逆起電力計算用）     │
└────────────────────────────────────────────────┘    └──────────────────────────────┘
```

**要点**: PLECSでは「全てが一つのシミュレータ内」だったものが、MuJoCoでは「機械はMuJoCo、電気と制御はPython」に分離される。この分離がPLECS経験者にとっての最大の思考転換点。

---

## 2. BLDCモータのPython実装方針

### 2.1 d-q軸変換モデルのPython実装

PLECSで使っていたd-q軸モデルをPythonに移植する。NumPy/SciPyベースで、PLECSの数式ブロックと1対1で対応する。

```python
import numpy as np

class BLDCMotorElectricalModel:
    """
    BLDCモータの電気的モデル（d-q軸座標系）

    PLECSでの等価回路:
      Vd = Rs*id + Ld*did/dt - omega_e*Lq*iq
      Vq = Rs*iq + Lq*diq/dt + omega_e*Ld*id + omega_e*lambda_m
      Te = 1.5 * P * (lambda_m*iq + (Ld - Lq)*id*iq)

    PLECSの「Permanent Magnet Synchronous Machine」ブロックに相当
    """

    def __init__(self, params: dict):
        # モータパラメータ（PLECSのパラメータダイアログと同じ）
        self.Rs = params['Rs']           # 固定子抵抗 [Ohm]
        self.Ld = params['Ld']           # d軸インダクタンス [H]
        self.Lq = params['Lq']           # q軸インダクタンス [H]
        self.lambda_m = params['lambda_m']  # 永久磁石鎖交磁束 [Wb]
        self.P = params['pole_pairs']    # 極対数
        self.J = params['J']             # 慣性モーメント [kg*m^2]  ← MuJoCo側に移管可能
        self.B = params['B']             # 粘性摩擦係数 [N*m*s/rad] ← MuJoCo側に移管可能

        # 状態変数（PLECSの初期値設定に相当）
        self.id = 0.0   # d軸電流 [A]
        self.iq = 0.0   # q軸電流 [A]

    def clarke_transform(self, ia: float, ib: float, ic: float) -> tuple:
        """
        Clarke変換（3相 → αβ座標）
        PLECSの "abc to alpha-beta" ブロックに相当
        """
        i_alpha = ia
        i_beta = (ia + 2 * ib) / np.sqrt(3)
        return i_alpha, i_beta

    def park_transform(self, i_alpha: float, i_beta: float, theta_e: float) -> tuple:
        """
        Park変換（αβ → dq座標）
        PLECSの "alpha-beta to dq" ブロックに相当
        """
        cos_th = np.cos(theta_e)
        sin_th = np.sin(theta_e)
        id = i_alpha * cos_th + i_beta * sin_th
        iq = -i_alpha * sin_th + i_beta * cos_th
        return id, iq

    def inverse_park_transform(self, vd: float, vq: float, theta_e: float) -> tuple:
        """
        逆Park変換（dq → αβ座標）
        PLECSの "dq to alpha-beta" ブロックに相当
        """
        cos_th = np.cos(theta_e)
        sin_th = np.sin(theta_e)
        v_alpha = vd * cos_th - vq * sin_th
        v_beta = vd * sin_th + vq * cos_th
        return v_alpha, v_beta

    def update(self, vd: float, vq: float, omega_m: float, dt: float):
        """
        1ステップの電気的状態更新（前進オイラー法）

        PLECSでは自動的に解かれていた微分方程式を、ここでは手動で離散化する。
        dt は電気的タイムステップ（例: 10μs）

        PLECSの可変ステップソルバ → Python の固定ステップ前進オイラー
        （精度が必要なら scipy.integrate.solve_ivp を使用）
        """
        omega_e = omega_m * self.P  # 電気角速度

        # 電圧方程式 → 電流の時間微分（PLECSの回路方程式と同一）
        did_dt = (vd - self.Rs * self.id + omega_e * self.Lq * self.iq) / self.Ld
        diq_dt = (vq - self.Rs * self.iq - omega_e * self.Ld * self.id
                  - omega_e * self.lambda_m) / self.Lq

        # 前進オイラー法で積分（PLECSの内部ソルバに相当）
        self.id += did_dt * dt
        self.iq += diq_dt * dt

    def get_torque(self) -> float:
        """
        電磁トルク計算
        PLECSの "Torque Output" に相当
        Te = 1.5 * P * (lambda_m * iq + (Ld - Lq) * id * iq)
        """
        return 1.5 * self.P * (
            self.lambda_m * self.iq +
            (self.Ld - self.Lq) * self.id * self.iq
        )


# ===== モータパラメータ例（PLECSのパラメータダイアログ値をそのまま転記）=====
motor_params = {
    'Rs': 0.5,            # [Ohm]
    'Ld': 0.8e-3,         # [H] = 0.8 mH
    'Lq': 0.8e-3,         # [H] = 0.8 mH (表面磁石型: Ld ≈ Lq)
    'lambda_m': 0.05,     # [Wb]
    'pole_pairs': 4,      # [-]
    'J': 1.0e-4,          # [kg*m^2]
    'B': 1.0e-4,          # [N*m*s/rad]
}
```

### 2.2 MuJoCoアクチュエータとPython電気モデルの分担

```
┌──────────────────────────────────────────────────────────────────┐
│  責任分担マトリクス                                                │
│                                                                  │
│  Python側が担当:                    MuJoCo側が担当:               │
│  ──────────────────                ───────────────────            │
│  ・FOC制御ループ                    ・ロータ慣性モーメント (J)      │
│  ・d-q軸電圧方程式                  ・粘性摩擦 (damping)           │
│  ・Park/Clarke変換                  ・クーロン摩擦 (friction)      │
│  ・PID制御器                        ・負荷トルク                   │
│  ・電磁トルク計算                   ・回転角度・角速度の積分        │
│  ・インバータモデル（必要時）        ・ギアモデル (transmission)     │
│  ・PWM生成（必要時）                ・多体間の力学的結合            │
│                                    ・接触力学                     │
│                                    ・可視化（3Dレンダリング）      │
│                                                                  │
│  Python → MuJoCo:  電磁トルク Te [N*m]                           │
│  MuJoCo → Python:  角速度 omega_m [rad/s], 角度 theta_m [rad]    │
└──────────────────────────────────────────────────────────────────┘
```

**MuJoCoモデル（MJCF XML）の例**:
```xml
<!-- bldc_motor.xml -->
<mujoco model="bldc_motor">
  <option timestep="0.0005" gravity="0 0 0"/>

  <worldbody>
    <!-- ステータ（固定） -->
    <body name="stator" pos="0 0 0">
      <geom type="cylinder" size="0.05 0.02" rgba="0.5 0.5 0.5 1"/>

      <!-- ロータ（回転） -->
      <body name="rotor" pos="0 0 0.03">
        <joint name="rotor_joint" type="hinge" axis="0 0 1"
               damping="0.0001" frictionloss="0.001"/>
        <!-- 慣性はPLECSの J パラメータに対応 -->
        <inertial pos="0 0 0" mass="0.1"
                  diaginertia="0.0001 0.0001 0.0001"/>
        <geom type="cylinder" size="0.03 0.015" rgba="0.8 0.2 0.2 1"/>

        <!-- 負荷（フライホイール等） -->
        <body name="load" pos="0 0 0.02">
          <geom type="cylinder" size="0.04 0.01" rgba="0.2 0.2 0.8 1"/>
          <inertial pos="0 0 0" mass="0.5"
                    diaginertia="0.001 0.001 0.001"/>
        </body>
      </body>
    </body>
  </worldbody>

  <!-- アクチュエータ: Python側から電磁トルクを入力 -->
  <actuator>
    <motor name="em_torque" joint="rotor_joint"
           ctrllimited="true" ctrlrange="-2.0 2.0"/>
  </actuator>

  <!-- センサ: Python側で制御に使用 -->
  <sensor>
    <jointpos name="rotor_pos" joint="rotor_joint"/>
    <jointvel name="rotor_vel" joint="rotor_joint"/>
  </sensor>
</mujoco>
```

**Python側でのMuJoCo連携コード**:
```python
import mujoco
import numpy as np

# --- MuJoCo モデルの読み込み ---
model = mujoco.MjModel.from_xml_path("bldc_motor.xml")
data = mujoco.MjData(model)

# --- 電気モデルとコントローラの初期化 ---
motor = BLDCMotorElectricalModel(motor_params)
speed_pid = PIDController(kp=0.5, ki=10.0, kd=0.001, dt=0.001,
                          output_min=-2.0, output_max=2.0)

# --- シミュレーションループ ---
omega_ref = 100.0  # 目標速度 [rad/s]
dt_mujoco = model.opt.timestep  # MuJoCoのタイムステップ (0.0005s)
dt_elec = 10e-6                 # 電気的タイムステップ (10μs)
n_elec_substeps = int(dt_mujoco / dt_elec)  # サブステップ数 = 50
dt_control = 0.002              # RL制御周期 (2ms = 500Hz)
n_mujoco_per_control = int(dt_control / dt_mujoco)  # = 4

sim_time = 2.0  # シミュレーション時間 [s]
n_steps = int(sim_time / dt_mujoco)

# 記録用配列（PLECSのスコープに相当）
time_log = np.zeros(n_steps)
omega_log = np.zeros(n_steps)
torque_log = np.zeros(n_steps)
iq_log = np.zeros(n_steps)

for step in range(n_steps):
    # --- MuJoCoからセンサ読み取り（PLECSのプローブに相当）---
    omega_m = data.sensordata[1]   # rotor_vel
    theta_m = data.sensordata[0]   # rotor_pos
    theta_e = theta_m * motor.P    # 電気角

    # --- 速度制御ループ（PLECSのPIDブロックに相当）---
    iq_ref = speed_pid.update(omega_ref, omega_m)
    id_ref = 0.0  # 表面磁石型: id* = 0 制御

    # --- 電流制御 + 電気モデル（サブステップ）---
    # PLECSが μs で解いていた部分を Python で再現
    vd, vq = 0.0, 0.0  # 簡易版: 電流PIは省略、直接トルク指令
    for _ in range(n_elec_substeps):
        motor.update(vd, vq, omega_m, dt_elec)

    # --- 電磁トルク → MuJoCoへ入力 ---
    Te = motor.get_torque()
    # 簡易版: PID出力を直接トルクとして使用（FOC省略時）
    Te_simplified = iq_ref * 1.5 * motor.P * motor.lambda_m

    data.ctrl[0] = Te_simplified  # MuJoCoアクチュエータへ

    # --- MuJoCo 1ステップ実行 ---
    mujoco.mj_step(model, data)

    # --- 記録 ---
    time_log[step] = step * dt_mujoco
    omega_log[step] = omega_m
    torque_log[step] = Te_simplified
    iq_log[step] = motor.iq

# --- 結果プロット（PLECSのスコープに相当）---
import matplotlib.pyplot as plt

fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
axes[0].plot(time_log, omega_log, label='omega_m')
axes[0].axhline(y=omega_ref, color='r', linestyle='--', label='omega_ref')
axes[0].set_ylabel('Speed [rad/s]')
axes[0].legend()

axes[1].plot(time_log, torque_log, label='Torque')
axes[1].set_ylabel('Torque [N*m]')
axes[1].legend()

axes[2].plot(time_log, iq_log, label='iq')
axes[2].set_ylabel('Current [A]')
axes[2].set_xlabel('Time [s]')
axes[2].legend()

plt.tight_layout()
plt.savefig('bldc_simulation_result.png', dpi=150)
plt.show()
```

### 2.3 PLECSユーザが自然に理解できるコード構造

```
プロジェクト構造:

bldc_mujoco_control/
├── models/
│   └── bldc_motor.xml           # MuJoCo MJCF（PLECSの回路図に相当）
├── electrical/
│   ├── motor_model.py           # BLDCMotorElectricalModel
│   │                            #  （PLECSの「モータブロック」に相当）
│   ├── transforms.py            # Clarke/Park変換
│   │                            #  （PLECSの「座標変換ブロック」に相当）
│   └── inverter.py              # インバータモデル（必要時）
│                                #  （PLECSの「スイッチ回路」に相当）
├── control/
│   ├── pid_controller.py        # PIDコントローラ
│   │                            #  （PLECSの「PIDブロック」に相当）
│   ├── foc_controller.py        # FOC制御器
│   │                            #  （PLECSの「FOC制御サブシステム」に相当）
│   └── speed_controller.py      # 速度制御ループ
├── simulation/
│   ├── sim_runner.py            # メインシミュレーションループ
│   └── data_logger.py           # データ記録（PLECSのスコープ）
├── visualization/
│   └── plot_results.py          # 波形プロット
├── rl/                          # （Phase 2: 強化学習）
│   ├── bldc_env.py              # Gymnasium環境
│   └── train_rl.py              # RL学習スクリプト
├── tests/
│   └── test_motor_model.py      # ユニットテスト
├── requirements.txt
└── README.md
```

**設計思想**: PLECSのサブシステム構造と1対1に対応させることで、PLECS経験者が「あのブロックはこのファイルだな」と直感的にマッピングできるようにする。

---

## 3. PID制御とFOC制御のPython実装

### 3.1 PIDコントローラ（PLECSのPIDブロック → Pythonクラス）

```python
class PIDController:
    """
    離散時間PIDコントローラ

    PLECSの "PID Controller" ブロックを Python で実装。

    PLECSとの対応:
      - Kp, Ki, Kd  → そのまま同名パラメータ
      - Saturation   → output_min, output_max
      - Anti-windup  → clamping方式（後述）
      - Sample Time  → dt（固定タイムステップ）

    離散化: 後退差分法（Backward Euler）
      積分: I[k] = I[k-1] + Ki * e[k] * dt
      微分: D[k] = Kd * (e[k] - e[k-1]) / dt

    注意: PLECSのPIDは連続時間で動作（内部ソルバが離散化を処理）するが、
         Pythonでは自分で離散化する必要がある。
    """

    def __init__(self, kp: float, ki: float, kd: float, dt: float,
                 output_min: float = -np.inf, output_max: float = np.inf):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.dt = dt
        self.output_min = output_min
        self.output_max = output_max

        # 内部状態
        self._integral = 0.0
        self._prev_error = 0.0

    def update(self, reference: float, measurement: float) -> float:
        """
        1ステップ実行

        PLECSでは「線を繋ぐ」だけだったが、Pythonでは明示的に
        誤差計算 → P, I, D計算 → 出力制限 → アンチワインドアップ
        を書く必要がある。
        """
        error = reference - measurement

        # P項
        p_term = self.kp * error

        # I項（後退差分積分）
        self._integral += error * self.dt
        i_term = self.ki * self._integral

        # D項（後退差分微分、測定値微分でノイズ軽減も可）
        d_term = self.kd * (error - self._prev_error) / self.dt
        self._prev_error = error

        # 出力合計
        output = p_term + i_term + d_term

        # 出力制限 + アンチワインドアップ（クランピング方式）
        output_saturated = np.clip(output, self.output_min, self.output_max)

        # アンチワインドアップ: 飽和時は積分を巻き戻す
        if output != output_saturated:
            self._integral -= error * self.dt  # 積分をリセット

        return output_saturated

    def reset(self):
        """PLECSの "Reset" 端子に相当"""
        self._integral = 0.0
        self._prev_error = 0.0
```

### 3.2 アンチワインドアップの実装バリエーション

PLECSでは Anti-Windup のオプションを選ぶだけだったが、Pythonでは自分で実装する。

```python
class PIDControllerAdvanced:
    """
    高度なPIDコントローラ（複数のアンチワインドアップ方式対応）

    PLECSの Anti-Windup オプション:
      - "None"       → anti_windup_method = 'none'
      - "Clamping"   → anti_windup_method = 'clamping'
      - "Back-calculation" → anti_windup_method = 'back_calculation'
    """

    def __init__(self, kp, ki, kd, dt, output_min, output_max,
                 anti_windup_method='back_calculation', kb=None):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.dt = dt
        self.output_min = output_min
        self.output_max = output_max
        self.anti_windup_method = anti_windup_method
        # Back-calculationゲイン（Kb = 1/Ti = Ki/Kp が一般的）
        self.kb = kb if kb is not None else (ki / kp if kp != 0 else 0)

        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_measurement = 0.0

    def update(self, reference, measurement):
        error = reference - measurement

        # P項
        p_term = self.kp * error

        # I項
        i_term = self.ki * self._integral

        # D項（微分先行型: 測定値の微分を使用 → PLECSの "Derivative of measurement" オプション）
        d_term = -self.kd * (measurement - self._prev_measurement) / self.dt
        self._prev_measurement = measurement

        # 飽和前の出力
        output_raw = p_term + i_term + d_term

        # 飽和
        output = np.clip(output_raw, self.output_min, self.output_max)

        # アンチワインドアップ
        if self.anti_windup_method == 'clamping':
            # 飽和していない場合のみ積分を更新
            if output == output_raw:
                self._integral += error * self.dt

        elif self.anti_windup_method == 'back_calculation':
            # 飽和量をフィードバックして積分を修正
            saturation_error = output - output_raw
            self._integral += (error + self.kb * saturation_error) * self.dt

        else:  # 'none'
            self._integral += error * self.dt

        self._prev_error = error
        return output
```

### 3.3 FOC（Field-Oriented Control）のPython実装

```python
class FOCController:
    """
    磁界方向制御（FOC）

    PLECSでは以下をサブシステムとして構成:
      1. Clarke変換（abc → αβ）
      2. Park変換（αβ → dq）
      3. d軸電流PI制御器
      4. q軸電流PI制御器
      5. 逆Park変換（dq → αβ）
      6. SVPWM

    Pythonではこれらを1クラスにまとめる。
    """

    def __init__(self, motor_params: dict, dt: float):
        self.P = motor_params['pole_pairs']
        self.lambda_m = motor_params['lambda_m']
        self.Ld = motor_params['Ld']
        self.Lq = motor_params['Lq']

        # 電流制御器（PLECSのPI Controller ブロック x 2）
        # バンド幅設計: 電流ループは速度ループの5-10倍速く
        self.pi_d = PIDController(kp=5.0, ki=1000.0, kd=0.0, dt=dt,
                                  output_min=-24.0, output_max=24.0)
        self.pi_q = PIDController(kp=5.0, ki=1000.0, kd=0.0, dt=dt,
                                  output_min=-24.0, output_max=24.0)

        # 速度制御器
        self.speed_pid = PIDController(kp=0.5, ki=10.0, kd=0.001, dt=dt,
                                       output_min=-10.0, output_max=10.0)

    def compute(self, omega_ref: float, omega_m: float,
                id_meas: float, iq_meas: float, theta_e: float) -> tuple:
        """
        FOC制御の1ステップ実行

        入力:
            omega_ref : 速度指令 [rad/s]
            omega_m   : 測定速度 [rad/s]（MuJoCoセンサから）
            id_meas   : d軸電流測定値 [A]（電気モデルから）
            iq_meas   : q軸電流測定値 [A]（電気モデルから）
            theta_e   : 電気角 [rad]（= theta_m * P）

        出力:
            vd, vq    : d-q軸電圧指令 [V]
            iq_ref    : q軸電流指令 [A]（ログ用）
        """
        # 速度ループ → q軸電流指令
        iq_ref = self.speed_pid.update(omega_ref, omega_m)
        id_ref = 0.0  # 表面磁石型BLDC: id* = 0

        # 電流ループ
        vd = self.pi_d.update(id_ref, id_meas)
        vq = self.pi_q.update(iq_ref, iq_meas)

        # 非干渉制御（デカップリング）
        # PLECSでは加算器ブロックで実装していた部分
        omega_e = omega_m * self.P
        vd -= omega_e * self.Lq * iq_meas           # d軸非干渉項
        vq += omega_e * self.Ld * id_meas            # q軸非干渉項
        vq += omega_e * self.lambda_m                 # 逆起電力補償

        return vd, vq, iq_ref
```

### 3.4 離散化の注意点（連続 → 離散）

PLECSは内部で自動的に連続時間モデルを解いていたが、Pythonでは自分で離散化する必要がある。

```
離散化手法の比較（PLECS経験者向け）:

手法              精度    安定性    PLECSの対応ソルバ     Python実装の難易度
────────────────────────────────────────────────────────────────────────
前進オイラー       低      条件付き  （PLECSでは非推奨）   簡単 ★
後退オイラー       中      無条件安定 暗黙的トラペゾイド    やや面倒
Tustin (双一次)   中      無条件安定 Trapezoidal          推奨 ★★
RK4               高      条件付き  Dormand-Prince       推奨 ★★★
────────────────────────────────────────────────────────────────────────

推奨:
  - 電気モデル: Tustin法 or RK4（電気時定数が小さいため安定性が重要）
  - 制御器のPID: 後退オイラー（シンプルで十分）
  - MuJoCoの内部: Euler or RK4（MuJoCoが自動で処理）
```

**重要: タイムステップの選び方**

```python
# PLECSでの経験則がそのまま使える
# 電気的時定数: tau_e = L / R
tau_e = motor_params['Ld'] / motor_params['Rs']  # 例: 0.8e-3 / 0.5 = 1.6ms

# 電気モデルのタイムステップ: tau_e / 10 以下
dt_elec = tau_e / 20  # 例: 80μs（実用では10μsを推奨）

# MuJoCoの内部タイムステップ
dt_mujoco = 0.5e-3  # 0.5ms（機械系の数値精度向上のため）

# RL制御周期: 電気時定数より大きく設定（RL専門家との合意）
dt_control = 2e-3  # 2ms = 500Hz（制御性能と学習効率のバランス）

# サブステップ数
n_elec_per_mujoco = int(dt_mujoco / dt_elec)  # = 50（10μsの場合）
n_mujoco_per_control = int(dt_control / dt_mujoco)  # = 4
```

---

## 4. PLECS経験者の知識仕分け

### 4.1 そのまま活かせる知識（アドバンテージ）

| 知識領域 | PLECSでの使用場面 | Python/MuJoCoでの活用場面 |
|:---|:---|:---|
| **モータの電気方程式** | 回路モデル構築 | `BLDCMotorElectricalModel` の実装 |
| **d-q軸変換理論** | 座標変換ブロック | `clarke_transform`, `park_transform` |
| **FOC制御設計** | 制御サブシステム構築 | `FOCController` クラス設計 |
| **PIDチューニング** | パラメータ調整 | そのまま同じ手法が使える |
| **伝達関数/ボード線図** | 安定性解析 | `scipy.signal` で同等の解析 |
| **状態空間モデル** | 高度なモデリング | `scipy.signal.StateSpace` |
| **PWM/SVPWM** | スイッチング制御 | Python関数として実装 |
| **電力損失解析** | 熱解析 | 効率計算に直接活用 |
| **過渡応答の読み方** | 波形解析 | Matplotlibのプロットで同じ解析 |
| **離散化の概念** | C Script Block | そのまま活きる（手動実装が必要） |
| **シミュレーションのデバッグ** | 波形の異常検知 | 数値不安定性の原因特定 |

### 4.2 新たに学ぶ必要がある知識

| 知識領域 | 優先度 | 目安期間 | 推奨リソース |
|:---|:---|:---|:---|
| **Python基礎文法** | 必須 | 1-2週間 | 公式チュートリアル |
| **NumPy配列操作** | 必須 | 1週間 | NumPy公式、PLECSのベクトル計算との対比で学ぶ |
| **Matplotlib** | 必須 | 2-3日 | PLECSのスコープの代替として最初に習得 |
| **オブジェクト指向（クラス）** | 必須 | 1週間 | PIDController の実装を通じて学ぶ |
| **Git/GitHub** | 必須 | 2-3日 | 最低限のadd/commit/push/branchを覚える |
| **仮想環境（venv/conda）** | 必須 | 1日 | 最初のセットアップで習得 |
| **MuJoCo API** | 必須 | 1-2週間 | 公式チュートリアル |
| **SciPy（微分方程式ソルバ）** | 重要 | 3-5日 | `solve_ivp` でモータモデルの精度向上 |
| **Gymnasium（RL環境）** | 重要 | 1週間 | Phase 2開始時 |
| **PyTorch基礎** | 重要 | 2週間 | Phase 2のRL学習用 |
| **型ヒント/テスト** | 推奨 | 継続 | コードの品質向上 |

### 4.3 PLECS → Python 思考の転換ポイント

```
PLECSでの思考              Pythonでの思考                学び方のコツ
──────────────────────────────────────────────────────────────────────
ブロックを配置して繋ぐ  →  クラスを定義して関数を呼ぶ     PLECSの各ブロック =
                                                        Pythonの1クラス と考える

線を引く = データフロー  →  変数の代入 = データフロー       a = block_a.output()
                                                        b = block_b.update(a)

パラメータダイアログ     →  __init__の引数/dict            motor_params = {...}

シミュレーション実行     →  forループ                      for step in range(n_steps):
 (Run ボタン)                                                mujoco.mj_step(...)

スコープで波形を見る     →  配列に記録 → Matplotlibで描画   data_log[step] = value
                                                        plt.plot(time, data_log)

Cスクリプトブロック      →  Python関数/クラス              ← 最も直接的な移行！
```

---

## 5. 週単位の移行ロードマップ（Month 1-3 詳細）

### Month 1: Python基礎 + モータモデリング

| 週 | 目標 | 詳細タスク | 成果物 | PLECSとの対応 |
|:---|:---|:---|:---|:---|
| **W1** | 開発環境構築 + Python入門 | - Python 3.11+, VS Code インストール<br>- venv仮想環境の作成<br>- NumPy, SciPy, Matplotlib インストール<br>- Git初期化, GitHub リポジトリ作成<br>- Python基礎: 変数, リスト, forループ, 関数 | GitHub初コミット | PLECSのインストール+ライセンス設定に相当 |
| **W2** | NumPy + Matplotlib 習熟 | - NumPy: 配列生成, 演算, ブロードキャスト<br>- Matplotlib: 波形プロット, サブプロット<br>- **課題**: PLECSで作った波形をPythonで再現<br>  (正弦波3相電圧, Clarke/Park変換の可視化) | Clarke/Park変換のPython実装 + プロット | PLECSの3相電圧源 + 座標変換ブロック |
| **W3** | BLDCモータの電気モデル実装 | - `BLDCMotorElectricalModel` クラス作成<br>- 前進オイラー法でd-q軸方程式を離散化<br>- オープンループテスト: 一定電圧印加→電流応答<br>- PLECSの結果と比較検証 | motor_model.py + 比較プロット | PLECSのPMSMブロック |
| **W4** | PIDコントローラ実装 | - `PIDController` クラス作成<br>- アンチワインドアップ実装<br>- 簡易速度制御（電気モデル + PID）<br>- ステップ応答の確認 | pid_controller.py + ステップ応答 | PLECSのPIDブロック |

### Month 2: MuJoCo統合 + FOC制御

| 週 | 目標 | 詳細タスク | 成果物 | PLECSとの対応 |
|:---|:---|:---|:---|:---|
| **W5** | MuJoCo入門 | - MuJoCo インストール (`pip install mujoco`)<br>- 公式チュートリアル: Hello MuJoCo<br>- MJCF XMLの基本構造理解<br>- 単純な回転体（フライホイール）の作成 | MuJoCoフライホイールモデル | PLECSの慣性ブロック |
| **W6** | MuJoCo BLDCモデル構築 | - `bldc_motor.xml` 作成<br>- アクチュエータ（トルク入力）設定<br>- センサ（位置、速度）設定<br>- Python からの制御入力テスト<br>- MuJoCo Viewer での3D表示確認 | bldc_motor.xml + 動作確認 | PLECSの回路図全体のMuJoCo版 |
| **W7** | 電気モデル + MuJoCo 統合 | - Python電気モデルとMuJoCoの連携<br>- サブステップの実装（電気→機械→電気...）<br>- PID速度制御の統合テスト<br>- PLECSとの応答比較検証 | 統合シミュレーション + 比較 | PLECSシミュレーション全体 |
| **W8** | FOC制御の実装 | - `FOCController` クラス作成<br>- d軸/q軸電流PIの実装<br>- 非干渉制御（デカップリング）<br>- FOC + MuJoCo統合テスト | foc_controller.py + 動作確認 | PLECSのFOCサブシステム |

### Month 3: 性能検証 + RL実装 + GitHub公開（RL専門家との調整済み）

| 週 | 目標 | 詳細タスク | 成果物 | 備考 |
|:---|:---|:---|:---|:---|
| **W9** | PIDベースライン + Gymnasium環境構築（並行） | - PID Optunaチューニング（1000回試行、自動実行中に環境構築）<br>- `BLDCMotorEnv(gymnasium.Env)` 作成<br>- 状態空間（7次元）、行動空間（[-1,1]）、報酬関数設計<br>- 環境テスト（ランダム行動 + PIDで動作確認） | 最適PIDパラメータ + bldc_env.py | PIDコードはW4で完成済みのため並行可能 |
| **W10** | PPO学習（RL基礎体験）+ 環境デバッグ | - PPOでCartPole/Pendulum体験（1-2日）<br>- PPOでBLDCMotorEnv学習<br>- 環境バグの発見と修正<br>- 報酬スケールの調整 | PPO学習曲線 + デバッグ済み環境 | PPOは安定、環境の問題を切り分けやすい |
| **W11** | SAC学習 + ハイパーパラメータ探索 | - SACに切り替えて本格学習<br>- Optunaでハイパーパラメータ探索（50試行）<br>- シナリオA-D での評価<br>- PID vs SAC 比較データ収集 | 学習済みSACモデル + 比較データ | 計算時間: 500K steps ≈ 数時間 |
| **W12** | 比較評価 + 可視化 + GitHub公開 | - 5軸レーダーチャート作成<br>- 時系列比較プロット（シナリオA-D）<br>- README（英語+日本語）<br>- コード整理、requirements.txt | **GitHub公開リポジトリ** | 最終成果物 |

---

## 6. 補足: よくある落とし穴と対処法

### 6.1 PLECSユーザが陥りやすいミス

| 落とし穴 | 原因 | 対処法 |
|:---|:---|:---|
| **数値発散** | タイムステップが大きすぎる | 電気時定数 τ = L/R の1/20以下に設定 |
| **MuJoCoで電気現象が見えない** | MuJoCoは機械のみ | 電気的ダイナミクスはPython側で計算 |
| **単位の不一致** | PLECSはSI単位、MuJoCoもSI | ただしMuJoCoのデフォルトはkg, m, s。注意深く確認 |
| **PLECSのように回路を描こうとする** | MuJoCoは回路シミュレータではない | 「電気=Python、機械=MuJoCo」の分担を常に意識 |
| **制御ループが遅い** | Pure Pythonが遅い | NumPyのベクトル演算を活用。必要ならNumba JIT |
| **PIDが発振する** | 離散化の影響 | 連続設計→Tustin変換で離散化。またはkdを小さくする |

### 6.2 PLECSの結果と比較検証する方法

```python
# PLECSの波形データをCSV出力し、Pythonの結果と比較する
import pandas as pd

# PLECSからエクスポートしたCSV
plecs_data = pd.read_csv('plecs_result.csv')

# Pythonシミュレーションの結果
fig, ax = plt.subplots()
ax.plot(plecs_data['time'], plecs_data['omega'], label='PLECS', linestyle='--')
ax.plot(time_log, omega_log, label='Python/MuJoCo')
ax.set_xlabel('Time [s]')
ax.set_ylabel('Speed [rad/s]')
ax.legend()
ax.set_title('PLECS vs Python/MuJoCo Comparison')
plt.show()
```

**検証基準**: ステップ応答の立ち上がり時間、整定時間、オーバーシュートが PLECS結果と5%以内で一致すれば、モデルの移行は成功。

---

## 7. MuJoCoモデルの詳細度に関する選択肢

プロジェクトの目的（RLでPIDを超える制御性能）に応じて、モデルの詳細度を段階的に上げる。

```
Level 1 (推奨開始点): トルク入力モデル
  ・MuJoCoのmotorアクチュエータに直接トルク指令
  ・電気的ダイナミクスは無視
  ・最もシンプル、RL学習に最適
  ・PLECSとの比較は機械系のみ

Level 2: 簡易電気モデル付き
  ・Python側でd-q軸モデルを計算
  ・トルク定数で電流→トルク変換
  ・電気的時定数の影響を反映
  ・FOC制御を実装可能

Level 3: 詳細電気モデル
  ・インバータのスイッチング
  ・PWM歪み、デッドタイム
  ・鉄損、磁気飽和
  ・PLECSと高精度比較が可能

推奨: Level 1 からスタートし、必要に応じて Level 2 へ。
     Level 3 は本プロジェクトのスコープ外（PLECSで十分）。
```

---

## 8. チームメンバーへの申し送り事項

### MuJoCo専門家（mujoco-expert）へ

- MuJoCoの `motor` アクチュエータの `ctrlrange` はPythonの電磁トルク計算結果に合わせて設定してください。典型的な小型BLDCでは `-2.0 ~ 2.0` [N*m] 程度です。
- `timestep` は `0.0005`（0.5ms）を推奨。RL制御周期2ms（n_substeps=4）に合わせた設計です。
- `damping` と `frictionloss` はモータの機械的パラメータから設定してください。
- `frictionloss` はRLが「PIDを超える」シナリオ（起動時の非線形領域）で重要なパラメータとなります。

### RL専門家（rl-expert）へ（調整合意済み）

- **観測空間（2段階設計）**:
  - PID検証フェーズ: `[omega_m, error, integral_error]`（3次元、PIDの入出力と1対1対応）
  - RL学習フェーズ: `[angle, velocity, target_angle, target_velocity, angle_error, velocity_error, prev_action]`（7次元）
  - Level 2使用時は `id`, `iq` を追加可能（電気モデルの `motor.iq` を直接使用、MuJoCoの `actuator_force` ではなく）
- **行動空間**: 連続値 `[-1, 1]` → トルク指令にスケーリング。Level 2では `[vd, vq]` 指令も選択肢
- **RL行動頻度**: 2ms（500Hz）で合意。MuJoCo内部0.5ms x 4サブステップ
- **PIDが苦手なシナリオ**（RLターゲット）:
  - シナリオA: ステップ応答（基本）
  - シナリオB: 軌道追従（正弦波・台形波）
  - シナリオC: 外乱+軌道追従（RLが最も輝くシナリオ）
  - シナリオD: 起動時の非線形領域（静止摩擦が支配的、PLECSユーザにとって実機との乖離として実感しやすい）

---

*作成日: 2026年3月20日*
*タスク#2: PLECS経験者向けのPython/制御実装移行ルート設計*
