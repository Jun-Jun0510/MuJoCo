# RLでPIDを超える制御を実現するための戦略設計

**担当**: 強化学習/機械学習 専門エージェント
**対象**: BLDCモータ制御（MuJoCo環境）への強化学習適用
**前提**: 対象者はPID/状態フィードバック制御に精通、Python/RL未経験

---

## 1. 「PIDを超える」の定量的基準

### 1.1 評価指標の定義

RLがPIDを「超えた」と主張するには、複数の定量指標で公平に比較する必要がある。以下の5軸で評価する。

| # | 指標 | 定義 | 制御工学での対応概念 | 単位 |
|---|:---|:---|:---|:---|
| 1 | **追従誤差 (Tracking Error)** | 目標値と実値のRMSE（Root Mean Square Error） | 定常偏差 + 過渡応答誤差 | rad or rad/s |
| 2 | **整定時間 (Settling Time)** | 目標値の ±2% に収束するまでの時間 | ステップ応答の整定時間 | 秒 |
| 3 | **オーバーシュート (Overshoot)** | 目標値を超える最大偏差の割合 | ステップ応答のオーバーシュート | % |
| 4 | **外乱抑制性能 (Disturbance Rejection)** | 外乱トルク印加後の回復時間とピーク偏差 | 外乱応答特性 | 秒 / rad |
| 5 | **エネルギー効率 (Energy Efficiency)** | モータ効率 η = ∫(Te·ωm)dt / ∫(Vq·iq + Vd·id)dt、および制御入力コスト ∫u²dt | 最適制御のコスト関数 / モータ効率 | % / V²·s |

> **注（motor-control-expertの補足）**: モータの場合、`∫u²dt` よりも機械出力 `∫(Te·ωm)dt` と電気入力 `∫(Vq·iq + Vd·id)dt` の比を効率として評価する方が、制御工学者にとって直感的。Level 1（トルク直接入力）では `∫u²dt` を使い、Level 2（電気モデル込み）ではモータ効率 η を使う。

### 1.2 公平な比較のためのPIDベースライン

**重要**: RLと比較するPIDは「適当にチューニングしたPID」ではなく、「最適チューニング済みPID」でなければならない。

```
PIDベースラインの準備手順:
1. Ziegler-Nichols法で初期パラメータを算出
2. scipy.optimize.minimize で RMSE を目的関数としてパラメータ探索
3. Optuna による自動チューニング（1000回試行）
4. 複数の評価シナリオ（ステップ応答、正弦波追従、外乱応答）で最良パラメータを選定
```

**PIDバリエーション（公平性の確保）**: Optunaの探索空間には以下も含める（motor-control-expertの提案に基づく）:
- **アンチワインドアップ方式**: clamping方式 / back-calculation方式を両方試行
- **微分先行型PID**: 速度制御タスクでは measurement derivative 方式も候補に含める
- 移行ガイドの `PIDController` クラスをそのままベースラインとして再利用する

```python
# PID最適チューニングの例（アンチワインドアップ・微分先行型を含む）
import optuna
import numpy as np

def objective(trial):
    kp = trial.suggest_float('kp', 0.1, 100.0, log=True)
    ki = trial.suggest_float('ki', 0.0, 50.0)
    kd = trial.suggest_float('kd', 0.0, 10.0)
    anti_windup = trial.suggest_categorical(
        'anti_windup', ['clamping', 'back_calculation']
    )
    use_derivative_on_measurement = trial.suggest_categorical(
        'derivative_on_measurement', [True, False]
    )

    # MuJoCoシミュレーション実行
    rmse = run_pid_simulation(
        kp, ki, kd, target_trajectory,
        anti_windup=anti_windup,
        derivative_on_measurement=use_derivative_on_measurement,
    )
    return rmse

study = optuna.create_study(direction='minimize')
study.optimize(objective, n_trials=1000)
best_pid = study.best_params
```

### 1.3 比較シナリオ（3段階）

| シナリオ | 内容 | PIDが得意 | RLが有利になり得る点 |
|:---|:---|:---|:---|
| **A: ステップ応答** | 0→目標角度のステップ入力 | 単純なので十分良い | 非線形性の活用で高速応答 |
| **B: 軌道追従** | 正弦波・台形波などの連続軌道 | まあまあ良い | 先読み（予測的制御入力）が可能 |
| **C: 外乱+軌道追従** | B + ランダム外乱トルク | 反応型なので遅れる | 外乱パターンの学習で事前対応可能 |
| **D: 起動時の非線形領域** | 静止状態→回転開始の起動シーケンス | 線形モデルベースのため振動・オーバーシュート | 静止摩擦等の非線形性を経験から学習 |

**RLが最も輝くのはシナリオC/D**。PIDは本質的にフィードバック制御（誤差が出てから反応）であり線形モデルを前提とするが、RLは状態の観測から外乱の影響を予測して事前に制御入力を調整でき、非線形性も経験から学習できる。

> **シナリオD補足（motor-control-expertの提案）**: モータ起動時は静止摩擦（クーロン摩擦）が支配的で、速度ゼロ付近では線形モデルが成立しない。PIDは起動時のオーバーシュートや振動が出やすいが、RLはシミュレーション中にこの非線形性を経験して学習できる。MuJoCoの `frictionloss` パラメータで静止摩擦を設定すれば再現可能。対象者がPLECSで経験した「実機とシミュレーションの乖離」に直結する話題であり、RLの価値を実感しやすい。

### 1.4 GitHubリポジトリでの見せ方

```
results/
├── comparison_step_response.png      # ステップ応答の時系列比較
├── comparison_trajectory_tracking.png # 軌道追従の時系列比較
├── comparison_disturbance.png        # 外乱応答の時系列比較
├── metrics_table.md                  # 全指標の数値比較テーブル
├── radar_chart.png                   # 5軸レーダーチャート（PID vs RL）
└── learning_curve.png                # RL学習曲線（報酬の推移）
```

**推奨グラフ構成**（1枚の比較画像）:

```python
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# 左上: 角度追従（PID vs RL vs 目標）
axes[0, 0].plot(t, target, 'k--', label='Reference')
axes[0, 0].plot(t, pid_response, 'b-', label='PID (tuned)')
axes[0, 0].plot(t, rl_response, 'r-', label='RL (SAC)')
axes[0, 0].set_title('Position Tracking')
axes[0, 0].legend()

# 右上: 追従誤差
axes[0, 1].plot(t, pid_error, 'b-', label='PID')
axes[0, 1].plot(t, rl_error, 'r-', label='RL')
axes[0, 1].set_title('Tracking Error')

# 左下: 制御入力
axes[1, 0].plot(t, pid_control, 'b-', label='PID')
axes[1, 0].plot(t, rl_control, 'r-', label='RL')
axes[1, 0].set_title('Control Input (Voltage)')

# 右下: レーダーチャート（5指標）
# ... radar chart code ...

plt.tight_layout()
plt.savefig('results/pid_vs_rl_comparison.png', dpi=150)
```

**READMEに載せるメトリクステーブル例**:

```markdown
| Metric | PID (Optuna-tuned) | RL (SAC) | Improvement |
|:---|:---:|:---:|:---:|
| RMSE (rad) | 0.045 | 0.018 | **60% reduction** |
| Settling Time (s) | 0.32 | 0.19 | **41% faster** |
| Overshoot (%) | 12.3 | 4.1 | **67% reduction** |
| Disturbance Recovery (s) | 0.45 | 0.22 | **51% faster** |
| Control Effort (V²·s) | 8.7 | 6.2 | **29% less energy** |
```

---

## 2. RL手法の選定と推奨

### 2.1 候補アルゴリズムの比較

| 特性 | PPO | SAC | TD3 |
|:---|:---|:---|:---|
| **カテゴリ** | On-policy | Off-policy | Off-policy |
| **行動空間** | 連続/離散 | 連続のみ | 連続のみ |
| **サンプル効率** | 低い（多くの経験が必要） | 高い | 高い |
| **安定性** | 非常に高い | 高い | 高い |
| **チューニング難度** | 低い（初心者向き） | 中程度 | 中程度 |
| **最終性能** | 良い | 非常に良い | 非常に良い |
| **探索** | 確率的方策 | エントロピー最大化 | ノイズ付加 |
| **制御工学との対応** | 確率的最適制御 | 最大エントロピー最適制御 | 決定的方策勾配 |

### 2.2 モータ制御タスクへの推奨

**最終推奨: SAC（Soft Actor-Critic）**

理由:
1. **連続行動空間との相性**: モータへの電圧入力は連続値であり、SACはこれに最適化されている
2. **サンプル効率**: MuJoCoシミュレーションは比較的高速だが、Off-policyであるSACはリプレイバッファを活用して効率的に学習する
3. **探索と活用のバランス**: エントロピー最大化により、局所解に陥りにくい。これは制御工学でいう「ロバスト性」に相当
4. **実績**: MuJoCoベンチマーク（HalfCheetah、Ant等）でSACは一貫して高い性能を示す
5. **制御タスクでの研究実績が豊富**: ロボット制御、ドローン制御等の先行研究多数

### 2.3 初学者向け段階的アプローチ

```
Stage 1: PPO で RL の基本を体験（Week 1-2）
  └── CartPole, Pendulum など既存環境で動かす
  └── 「方策が改善されていく」体験をする

Stage 2: PPO でカスタム環境（簡易DCモータ）を制御（Week 3-4）
  └── 自分でGymnasium環境を作る経験
  └── 報酬関数の設計を体験する

Stage 3: SAC に切り替え、BLDCモータ制御（Week 5-8）
  └── PPOとの性能差を体験
  └── ハイパーパラメータの影響を学ぶ

Stage 4: 最適チューニングPID vs SAC の本格比較（Week 9-12）
  └── Optunaでのハイパーパラメータ探索
  └── 複数シナリオでの評価・可視化

### モデル詳細度 × RLアルゴリズムの組み合わせ（motor-control-expertとの合意）

移行ガイドのモデル詳細度レベルと組み合わせた段階的進行:

Phase A: Level 1（トルク直接入力）+ PPO  → RL基礎体験、環境検証
Phase B: Level 1（トルク直接入力）+ SAC  → 同じ環境でアルゴリズム比較
Phase C: Level 2（電気モデル込み）+ SAC  → FOC知識活用、[vd,vq]行動空間

Phase Cでは行動空間が `[vd, vq]` の2次元になり、RLが「FOCコントローラの
代わり」を学習する形になる。対象者のFOC知識が報酬設計・結果解釈に活きる
最も面白いフェーズ。ただしPhase A/Bの成功を確認してから進むこと。
```

**なぜPPOから始めるか**:
- ハイパーパラメータに対して最もロバスト（壊れにくい）
- 「学習が動いている」実感を最短で得られる
- コードがシンプルでデバッグしやすい
- SB3のドキュメント・チュートリアルが最も充実

**なぜ最終的にSACに切り替えるか**:
- モータ制御で求められる精密な連続制御に向いている
- サンプル効率が高く、学習が速い
- 外乱に対するロバスト性が高い（エントロピー正則化の効果）

---

## 3. 報酬関数の設計

### 3.1 制御工学者のための報酬関数の理解

**核心的な対応関係**:

```
制御工学: J = ∫(x'Qx + u'Ru) dt   ← LQR評価関数（最小化）
    RL:   r = -(x'Qx + u'Ru)       ← 報酬関数（最大化）

つまり: 報酬 = -（評価関数）
```

制御工学で「評価関数を最小化する」ことと、RLで「累積報酬を最大化する」ことは数学的に等価。LQRの評価関数をそのまま符号反転すれば報酬関数になる。

### 3.2 タスク別の報酬関数設計

#### タスクA: 位置追従（角度制御）

```python
def reward_position_tracking(obs, action, target_angle):
    """
    制御工学の対応: LQR評価関数 J = q*(theta-theta_ref)^2 + r*u^2
    """
    angle_error = obs['angle'] - target_angle
    angular_velocity = obs['angular_velocity']

    # 主報酬: 追従誤差（Q行列の対角要素に相当）
    r_tracking = -10.0 * angle_error**2

    # 速度ペナルティ: 目標近傍では速度を抑えたい
    r_velocity = -0.1 * angular_velocity**2

    # 制御コスト: 入力の大きさにペナルティ（R行列に相当）
    r_control = -0.01 * action**2

    # ボーナス: 目標の近くにいるとき（整定を促進）
    if abs(angle_error) < 0.05:  # ~3度以内
        r_bonus = 1.0
    else:
        r_bonus = 0.0

    return r_tracking + r_velocity + r_control + r_bonus
```

#### タスクB: 速度追従

```python
def reward_velocity_tracking(obs, action, target_velocity):
    """
    速度制御: 回転数一定を保つタスク
    制御工学の対応: 速度偏差の最小化 + 入力コスト
    """
    velocity_error = obs['angular_velocity'] - target_velocity

    # 主報酬: 速度追従誤差
    r_tracking = -5.0 * velocity_error**2

    # 制御入力のスムーズさ（入力変化率にペナルティ）
    r_smooth = -0.1 * (action - prev_action)**2

    # 制御コスト
    r_control = -0.01 * action**2

    return r_tracking + r_smooth + r_control
```

#### タスクC: 外乱抑制付き軌道追従（最終目標）

```python
def reward_robust_tracking(obs, action, target, prev_action):
    """
    外乱環境下での軌道追従: RLの真価が発揮されるタスク
    制御工学の対応: H∞制御の評価関数に近い
    """
    angle_error = obs['angle'] - target['angle']
    velocity_error = obs['angular_velocity'] - target['angular_velocity']

    # 状態誤差コスト（Q行列: 追従精度重視）
    r_state = -(10.0 * angle_error**2 + 1.0 * velocity_error**2)

    # 制御入力コスト（R行列: エネルギー効率）
    r_control = -0.01 * np.sum(action**2)

    # 制御入力の滑らかさ（ジャーク的ペナルティ）
    r_smooth = -0.05 * np.sum((action - prev_action)**2)

    # 生存ボーナス（エピソードを長く続けるインセンティブ）
    r_alive = 0.1

    return r_state + r_control + r_smooth + r_alive
```

### 3.3 報酬設計のよくある失敗と対策

| # | 失敗パターン | 症状 | 原因 | 対策 |
|---|:---|:---|:---|:---|
| 1 | **報酬ハッキング** | 意図しない行動で高報酬を得る | 報酬関数の抜け穴 | 制御入力ペナルティの追加、行動空間のクリッピング |
| 2 | **スパース報酬** | 学習が全く進まない | 成功時のみ報酬で探索困難 | 連続的な追従誤差ベースの密な報酬を使う |
| 3 | **報酬スケールの不均衡** | 一部の項だけ最適化される | 各項の大きさが桁違い | 報酬の各項を正規化（概ね同じオーダーにする） |
| 4 | **振動する制御入力** | モータがブーンと唸る | 入力変化率のペナルティが無い | `r_smooth` を追加（下記補足参照） |

> **物理的根拠（motor-control-expertの補足）**: `(action - prev_action)^2` ペナルティは制御工学での「制御入力変化率制約（rate limiter）」に相当する。モータドライブでは電流変化率 di/dt が大きすぎるとスイッチング損失増大・EMI（電磁干渉）の原因になるため、このペナルティは物理的にも妥当。単なるRL学習の安定化テクニックではなく、実機適用時にも重要な制約である。
| 5 | **早期エピソード終了** | 短いエピソードばかりで学習不足 | 終了条件が厳しすぎる | 終了条件を緩和し、生存ボーナスを追加 |

**報酬関数デバッグのコツ**:
```python
# 各報酬成分を個別にログして、バランスを確認する
info = {
    'r_tracking': r_tracking,
    'r_control': r_control,
    'r_smooth': r_smooth,
    'r_alive': r_alive,
    'total_reward': total_reward,
}
# TensorBoardで各成分を可視化し、支配的な項がないか確認
```

---

## 4. Gymnasium環境の構築方針

### 4.1 制御工学者のためのアナロジー

```
制御工学           →  Gymnasium/RL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
状態空間 x(t)      →  観測空間 (observation_space)
制御入力 u(t)      →  行動空間 (action_space)
状態方程式 dx=f(x,u) → step() メソッド（MuJoCoが計算）
評価関数 J         →  報酬関数 reward（符号反転）
サンプリング周期 Ts →  タイムステップ dt
シミュレーション終了 →  エピソード終了 (terminated/truncated)
初期条件 x(0)      →  reset() メソッド
外乱 d(t)         →  環境内のランダム要素
```

### 4.2 観測空間の設計

```python
# BLDCモータ制御の観測空間（8次元）
observation_space = spaces.Box(
    low=np.array([
        -np.pi,     # theta: 回転角度 [rad]
        -50.0,      # omega: 角速度 [rad/s]
        -10.0,      # current: 電流 [A]（またはトルク）
        -np.pi,     # target_angle: 目標角度 [rad]
        -50.0,      # target_velocity: 目標速度 [rad/s]
        -np.pi,     # angle_error: 角度誤差 [rad]
        -50.0,      # velocity_error: 速度誤差 [rad/s]
        -1.0,       # prev_action: 前回の制御入力 [-1, 1]
    ]),
    high=np.array([
        np.pi,
        50.0,
        10.0,
        np.pi,
        50.0,
        np.pi,
        50.0,
        1.0,
    ]),
    dtype=np.float32
)
```

**設計判断のポイント**:
- **誤差情報を含める**: PIDコントローラは `e(t)` と `∫e dt` と `de/dt` を見る。RLエージェントにも同様の情報を与える
- **目標値を含める**: 追従制御では目標値が変化するため、観測に含める
- **prev_action を含める**: 報酬関数に `(action - prev_action)^2` のスムーズネスペナルティがあるため、エージェントが前回の行動を知っている方が最適化しやすい（motor-control-expertとの合意）
- **integral_error は含めない**: NNが内部的に積分効果を学習できるため、生の状態量（角度・速度）を渡す方がRL学習には合理的（motor-control-expertとの合意）
- **正規化**: すべての観測値を概ね [-1, 1] の範囲にスケーリングするとNNの学習が安定する

**MuJoCo固有の注意点（motor-control-expertの指摘）**:
- `data.actuator_force[0]` はMuJoCoの `motor` アクチュエータでは `ctrl[0]` そのもの（制御入力値）が返される。電流のプロキシとしては不正確
- Level 1（トルク直接入力）では電流情報の代わりにトルク指令値を使う
- Level 2（電気モデル込み）ではPython側の電気モデルから `motor.iq`, `motor.id` を直接取得して観測に含める

**Level 2での拡張観測空間**:
```python
# Level 2: FOC知識を活用する拡張観測空間（9次元）
observation_space = spaces.Box(
    low=-np.inf, high=np.inf,
    shape=(9,), dtype=np.float32
)
# [angle, velocity, id, iq, target_angle, target_velocity,
#  angle_error, velocity_error, electrical_angle]
```

### 4.3 行動空間の設計

```python
# 単相の電圧入力（簡略化モデル）
action_space = spaces.Box(
    low=np.array([-1.0]),   # -1 → 最大逆方向電圧
    high=np.array([1.0]),   # +1 → 最大正方向電圧
    dtype=np.float32
)
# 実際の電圧 = action * V_max (例: 24V)
```

**BLDCの3相制御を扱う場合**:
```python
# 3相電圧（またはdq軸電圧）
action_space = spaces.Box(
    low=np.array([-1.0, -1.0]),   # d軸, q軸
    high=np.array([1.0, 1.0]),
    dtype=np.float32
)
```

### 4.4 カスタムGymnasium環境の実装テンプレート

```python
import gymnasium as gym
from gymnasium import spaces
import numpy as np
import mujoco

class BLDCMotorEnv(gym.Env):
    """
    BLDCモータ制御のGymnasium環境

    制御工学での対応:
    - Plant: MuJoCoのBLDCモータモデル
    - Controller: RLエージェント（方策ネットワーク）
    - Sensor: 観測値（角度、速度、電流）
    """
    metadata = {'render_modes': ['human', 'rgb_array'], 'render_fps': 60}

    def __init__(self, render_mode=None):
        super().__init__()

        # MuJoCoモデルの読み込み
        self.model = mujoco.MjModel.from_xml_path('bldc_motor.xml')
        self.data = mujoco.MjData(self.model)

        # タイムステップ構成（motor-control-expertとの合意）:
        #   MuJoCo内部ステップ:     0.5ms (timestep=0.0005, 機械系精度向上)
        #   RL制御周期:             2ms   (n_substeps=4)
        #   電気モデルサブステップ:  10us  (Level 2のみ, n_elec_per_mujoco=50)
        self.control_dt = 0.002  # 2ms = 500Hz（RL行動頻度）
        self.n_substeps = int(self.control_dt / self.model.opt.timestep)  # = 4

        # 空間定義
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(8,), dtype=np.float32  # 7状態 + prev_action
        )
        self.action_space = spaces.Box(
            low=-1.0, high=1.0,
            shape=(1,), dtype=np.float32
        )

        # タスク設定
        self.max_steps = 2000       # エピソード最大ステップ（= 4秒）
        self.step_count = 0
        self.target_trajectory = None

        self.render_mode = render_mode

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        # MuJoCoの状態をリセット
        mujoco.mj_resetData(self.model, self.data)

        # ランダムな初期状態（制御工学の「初期条件のばらつき」に相当）
        self.data.qpos[0] = self.np_random.uniform(-0.5, 0.5)
        self.data.qvel[0] = self.np_random.uniform(-1.0, 1.0)

        # 目標軌道の生成（エピソードごとにランダム）
        self.target_trajectory = self._generate_target()
        self.step_count = 0
        self.prev_action = np.zeros(1)

        obs = self._get_obs()
        info = {}
        return obs, info

    def step(self, action):
        # 行動を電圧に変換（action は [-1, 1]）
        voltage = action[0] * 24.0  # V_max = 24V

        # MuJoCoアクチュエータに電圧を適用
        self.data.ctrl[0] = voltage

        # MuJoCoシミュレーションを制御周期分進める
        for _ in range(self.n_substeps):
            mujoco.mj_step(self.model, self.data)

        self.step_count += 1

        # 観測値の取得
        obs = self._get_obs()

        # 報酬の計算
        target = self.target_trajectory[self.step_count]
        angle_error = self.data.qpos[0] - target
        velocity = self.data.qvel[0]

        reward = (
            -10.0 * angle_error**2      # 追従誤差
            - 0.1 * velocity**2          # 速度ペナルティ（目標近傍で）
            - 0.01 * action[0]**2        # 制御コスト
            - 0.05 * (action[0] - self.prev_action[0])**2  # 滑らかさ
            + 0.1                         # 生存ボーナス
        )

        self.prev_action = action.copy()

        # 終了条件
        terminated = False
        truncated = self.step_count >= self.max_steps

        info = {
            'angle_error': angle_error,
            'control_effort': action[0]**2,
        }

        return obs, reward, terminated, truncated, info

    def _get_obs(self):
        target = self.target_trajectory[min(self.step_count, len(self.target_trajectory)-1)]
        angle = self.data.qpos[0]
        velocity = self.data.qvel[0]

        # NOTE: Level 1ではactuator_forceはctrl値そのもの（電流プロキシとしては不正確）
        # Level 2ではPython電気モデルの motor.iq を使うこと
        current_proxy = self.data.actuator_force[0]  # Level 1: トルク指令値

        return np.array([
            angle,                          # 現在角度
            velocity,                       # 現在角速度
            current_proxy,                  # Level 1: トルク指令 / Level 2: iq電流
            target,                         # 目標角度
            0.0,                            # 目標速度（位置制御なので0）
            angle - target,                 # 角度誤差
            velocity,                       # 速度誤差
            self.prev_action[0],            # 前回の制御入力（スムーズネス最適化用）
        ], dtype=np.float32)

    def _generate_target(self):
        """エピソードごとにランダムな目標軌道を生成"""
        # ステップ入力、正弦波、ランダムウォークからランダムに選択
        traj_type = self.np_random.choice(['step', 'sine', 'multi_step'])
        t = np.arange(self.max_steps + 1) * self.control_dt

        if traj_type == 'step':
            target_val = self.np_random.uniform(-1.0, 1.0)
            trajectory = np.full(len(t), target_val)
        elif traj_type == 'sine':
            freq = self.np_random.uniform(0.5, 3.0)
            amp = self.np_random.uniform(0.3, 1.5)
            trajectory = amp * np.sin(2 * np.pi * freq * t)
        else:  # multi_step
            trajectory = np.zeros(len(t))
            n_steps = self.np_random.integers(3, 8)
            step_times = np.sort(self.np_random.choice(len(t), n_steps, replace=False))
            for st in step_times:
                trajectory[st:] = self.np_random.uniform(-1.5, 1.5)

        return trajectory

    def render(self):
        # MuJoCoビューアの処理（省略）
        pass
```

### 4.5 環境のregister

```python
# __init__.py
from gymnasium.envs.registration import register

register(
    id='BLDCMotor-v0',
    entry_point='bldc_motor_env:BLDCMotorEnv',
    max_episode_steps=2000,
)
```

---

## 5. RL学習の具体的パイプライン

### 5.1 Stable-Baselines3でのトレーニング手順

```python
# train.py - メインの学習スクリプト
import gymnasium as gym
from stable_baselines3 import SAC
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv
import bldc_motor_env  # カスタム環境を import

# ========== Step 1: 環境の作成 ==========
def make_env():
    env = gym.make('BLDCMotor-v0')
    env = Monitor(env)  # 報酬・エピソード長のログ記録
    return env

train_env = DummyVecEnv([make_env])
eval_env = DummyVecEnv([make_env])

# ========== Step 2: コールバックの設定 ==========
eval_callback = EvalCallback(
    eval_env,
    best_model_save_path='./logs/best_model/',
    log_path='./logs/eval/',
    eval_freq=10000,        # 10000ステップごとに評価
    n_eval_episodes=10,     # 10エピソードで平均評価
    deterministic=True,
)

checkpoint_callback = CheckpointCallback(
    save_freq=50000,
    save_path='./logs/checkpoints/',
)

# ========== Step 3: エージェントの作成 ==========
model = SAC(
    'MlpPolicy',
    train_env,
    learning_rate=3e-4,
    buffer_size=100000,
    batch_size=256,
    tau=0.005,              # ソフトアップデート係数
    gamma=0.99,             # 割引率（制御工学: 将来コストの重み）
    learning_starts=1000,   # 最初の1000ステップはランダム探索
    verbose=1,
    tensorboard_log='./logs/tensorboard/',
)

# ========== Step 4: 学習の実行 ==========
model.learn(
    total_timesteps=500_000,
    callback=[eval_callback, checkpoint_callback],
    log_interval=10,
)

# ========== Step 5: モデルの保存 ==========
model.save('bldc_sac_final')
```

### 5.2 ハイパーパラメータガイドライン

**最低限チューニングすべきパラメータ（優先度順）**:

| パラメータ | デフォルト | 探索範囲 | 影響 |
|:---|:---:|:---|:---|
| `learning_rate` | 3e-4 | 1e-5 ~ 1e-3 | 学習の安定性と速度。最重要 |
| `gamma` | 0.99 | 0.95 ~ 0.999 | 将来の報酬の重み。長期タスクほど高く |
| `batch_size` | 256 | 64 ~ 1024 | 勾配推定の精度。大きいほど安定 |
| `tau` | 0.005 | 0.001 ~ 0.05 | ターゲットネットワークの更新速度 |
| `ent_coef` | 'auto' | 'auto' or 0.01~0.2 | 探索の積極性。autoが無難 |
| ネットワーク構造 | [256, 256] | [64,64] ~ [256,256,256] | モデルの表現力 |

**Optunaによるハイパーパラメータ探索**:

```python
import optuna
from stable_baselines3 import SAC
from stable_baselines3.common.evaluation import evaluate_policy

def optimize_sac(trial):
    lr = trial.suggest_float('learning_rate', 1e-5, 1e-3, log=True)
    gamma = trial.suggest_float('gamma', 0.95, 0.999)
    batch_size = trial.suggest_categorical('batch_size', [64, 128, 256, 512])
    tau = trial.suggest_float('tau', 0.001, 0.05)
    net_arch_size = trial.suggest_categorical('net_arch', [64, 128, 256])

    model = SAC(
        'MlpPolicy',
        train_env,
        learning_rate=lr,
        gamma=gamma,
        batch_size=batch_size,
        tau=tau,
        policy_kwargs={'net_arch': [net_arch_size, net_arch_size]},
        verbose=0,
    )

    model.learn(total_timesteps=100_000)  # 短めで探索
    mean_reward, _ = evaluate_policy(model, eval_env, n_eval_episodes=20)
    return mean_reward

study = optuna.create_study(direction='maximize')
study.optimize(optimize_sac, n_trials=50)
print(f"Best params: {study.best_params}")
```

### 5.3 学習が上手くいかないときのデバッグ手順

```
デバッグフローチャート:

報酬が全く増えない
├── Step 1: 環境のバグチェック
│   ├── ランダム行動で step() が正常に動くか？
│   ├── 観測値が NaN / Inf になっていないか？
│   ├── 報酬の範囲は妥当か？（-1000 ~ +1000 くらいが目安）
│   └── reset() で状態が正しくリセットされるか？
│
├── Step 2: 報酬関数のチェック
│   ├── 手動で「良い行動」をしたとき報酬が高いか？
│   ├── 各報酬成分のスケールは均衡しているか？
│   └── 報酬がスパース（稀にしか出ない）になっていないか？
│
├── Step 3: 観測空間のチェック
│   ├── 観測値は正規化されているか？
│   ├── エージェントに十分な情報が提供されているか？
│   └── 目標値が観測に含まれているか？
│
├── Step 4: ハイパーパラメータのチェック
│   ├── learning_rate を 10倍にしてみる → 学習が不安定ならlr高すぎ
│   ├── learning_rate を 1/10にしてみる → 改善するならlrが元々高すぎ
│   └── total_timesteps は十分か？（最低 100K、推奨 500K-1M）
│
└── Step 5: アルゴリズムの問題
    ├── PPOに切り替えて動くか試す（PPOが動かないなら環境の問題）
    └── 既知の環境（Pendulum-v1）で同じコードが動くか確認
```

### 5.4 学習曲線の読み方

```
TensorBoardで確認すべきグラフ（優先度順）:

1. ep_rew_mean（エピソード平均報酬）
   - 右肩上がり → 正常に学習中
   - フラット → 学習停滞（lr、報酬関数、観測空間を見直す）
   - 振動 → 不安定（lrを下げる、batch_sizeを上げる）
   - 急に下がる → 崩壊（lrが高すぎ、報酬関数にバグ）

2. ep_len_mean（エピソード平均長）
   - 増加 → エージェントが長く生存している（良い兆候）
   - 常に最大値 → truncated で終了している（正常）

3. actor_loss / critic_loss（SAC）
   - critic_loss が安定的に減少 → 価値関数が改善中
   - actor_loss の振動は正常（方策改善中）
   - どちらかが発散 → 学習率が高すぎ

4. entropy_coefficient（SAC, ent_coef='auto'の場合）
   - 学習初期: 高い（探索中）
   - 学習後期: 低下（活用に移行）
   - 下がらない → 方策が改善できていない
```

```python
# TensorBoardの起動
# ターミナルで:
# tensorboard --logdir ./logs/tensorboard/
# ブラウザで http://localhost:6006 にアクセス
```

---

## 6. Month 3のRL学習に備えて身につけるべき基礎

### 6.1 最小限のPyTorch知識リスト

Month 1-2で以下を理解しておけば、SB3でのRL学習に支障はない。

| # | トピック | 必要な理解レベル | 所要時間 |
|---|:---|:---|:---|
| 1 | **テンソル操作** | NumPy配列との対応。作成、形状変換、演算 | 2時間 |
| 2 | **自動微分 (autograd)** | `requires_grad=True`、`loss.backward()`、勾配の概念 | 2時間 |
| 3 | **nn.Module** | ニューラルネットワークの定義（Linear層、活性化関数） | 3時間 |
| 4 | **損失関数とオプティマイザ** | MSELoss、Adam、学習率の意味 | 2時間 |
| 5 | **学習ループ** | forward → loss → backward → step の4ステップ | 2時間 |

**推奨チュートリアル**: PyTorch公式の "60 Minute Blitz"（https://pytorch.org/tutorials/beginner/deep_learning_60min_blitz.html）

**制御工学者向けの対応表**:
```
勾配降下法      ←→  評価関数の最急降下法（最適制御との類似性）
ニューラルネット ←→  非線形関数近似器（y = f(x; θ) のθを学習）
バッチ学習      ←→  複数のシミュレーション結果からパラメータ更新
過学習         ←→  特定の運転条件だけに最適化されてしまう（ロバスト性の欠如）
```

### 6.2 RL理論の最小限の理解

**必須概念（Month 2で学習）**:

```
1. MDP（マルコフ決定過程）
   制御工学での対応: 離散時間状態空間モデル
   x(k+1) = f(x(k), u(k), w(k))  ← 状態遷移
   r(k) = g(x(k), u(k))           ← 報酬（= -評価関数）

2. 方策 π(a|s)
   制御工学での対応: 制御則 u = K(x)
   PID:  u = Kp*e + Ki*∫e + Kd*de/dt  ← 手動で構造を決める
   RL:   u = π(s; θ)                    ← NNが自動で構造を学習

3. 価値関数 V(s), Q(s,a)
   制御工学での対応: コスト関数 J(x)
   V(s) = この状態からどれくらいの累積報酬が期待できるか
   Q(s,a) = この状態でこの行動をしたら累積報酬はどれくらいか
   → LQRのリカッチ方程式の解 P が価値関数に対応

4. Actor-Critic
   Actor = 方策（制御器）: 状態を見て行動を決める
   Critic = 価値関数（評価器）: 状態・行動の良さを評価する
   → 制御器と評価器を同時に学習する枠組み
   → SACは Actor-Critic の一種
```

### 6.3 推奨リソース

**書籍**:

| 書籍 | 対象 | 優先度 |
|:---|:---|:---|
| "Reinforcement Learning: An Introduction" (Sutton & Barto) | RL理論の聖典。無料PDF公開 | 高（Ch.1-6, 13を読む） |
| "ゼロから作るDeep Learning" (斎藤康毅) | PyTorch/NNの基礎。日本語 | 高（Month 1で） |
| "Spinning Up in Deep RL" (OpenAI) | 実装寄りのRL入門。Web上で無料 | 高（Month 2で） |

**動画**:

| リソース | 内容 | 所要時間 |
|:---|:---|:---|
| David Silver RL講義 (YouTube) | DeepMind研究者によるRL入門 | 全10回、各1.5時間（Ch.1-4必須） |
| Mutual Information (YouTube) | SAC、PPOの直感的解説 | 各30分 |
| Stable-Baselines3公式ドキュメント | SB3の使い方チュートリアル | 適宜参照 |

**ハンズオン**:

| チュートリアル | 内容 | タイミング |
|:---|:---|:---|
| Gymnasium公式チュートリアル | CartPole, Pendulumを動かす | Month 2 Week 1 |
| SB3公式のカスタム環境作成ガイド | 自作環境の作り方 | Month 2 Week 2-3 |
| CleanRL (GitHub) | アルゴリズムの中身を理解したいとき | Month 2 Week 4（余裕があれば） |

---

## 7. 初学者がつまずくポイントと対策

### 7.1 「RLが学習しない」ときの典型的原因トップ5

| 順位 | 原因 | 発生頻度 | 症状 | 対策 |
|:---:|:---|:---:|:---|:---|
| **1** | **環境のバグ** | 非常に高い | 報酬が増えない、NaN出力 | `env.step(random_action)` を1000回回してログを確認 |
| **2** | **観測値が正規化されていない** | 高い | 学習が極端に遅い | `VecNormalize` ラッパーを使う or 手動で正規化 |
| **3** | **報酬スケールの問題** | 高い | 学習が不安定、または特定の行動に偏る | 報酬の各成分をログして確認。概ね [-10, 10] に収まるように調整 |
| **4** | **学習ステップ数が足りない** | 中程度 | 「まだ」学習していないだけ | 最低500K、できれば1-2Mステップ試す |
| **5** | **行動空間のスケールが不適切** | 中程度 | 制御入力が小さすぎ/大きすぎ | action * scale の scale を確認。物理的に妥当な範囲か |

### 7.2 環境のバグ vs ハイパーパラメータの問題の見分け方

```
判別フローチャート:

Step 1: 既知の環境でコードが動くか？
  │
  ├── Pendulum-v1 で SAC が学習する → 自分の環境の問題
  └── Pendulum-v1 でも学習しない → インストール/コードの問題

Step 2: 自分の環境でランダム行動は動くか？
  │
  ├── obs に NaN がある → MuJoCoモデルの問題（物理パラメータ等）
  ├── reward が常に同じ値 → 報酬関数のバグ
  ├── エピソードが即終了 → 終了条件のバグ
  └── 正常に動く → Step 3へ

Step 3: ハンドコーディングした方策で良い報酬が得られるか？
  │
  ├── PIDコントローラで良い報酬が出る → 環境は正常。RLの問題
  │   ├── 学習率を変えて試す
  │   ├── ネットワーク構造を変えて試す
  │   └── PPO/SAC/TD3 を全部試す
  │
  └── PIDでも良い報酬が出ない → 報酬関数の設計ミス
      └── 報酬の各成分を個別に確認
```

### 7.3 その他のよくある落とし穴

| 落とし穴 | 説明 | 対策 |
|:---|:---|:---|
| **再現性の欠如** | 実行ごとに結果が変わりパニック | seed を固定する（環境、PyTorch、NumPy） |
| **GPU不要の思い込み** | モータ制御RLではGPUはほぼ不要 | MuJoCoのシミュレーションがボトルネック。CPUで十分 |
| **観測のリーク** | 未来の情報を観測に入れてしまう | 「今」の時刻で利用可能な情報のみを含める |
| **報酬の遅延** | 行動の結果が数ステップ後に現れる | LSTMなどの時系列対応、またはフレームスタッキング |
| **過学習** | 特定の目標値でのみ性能が良い | 目標軌道をランダムに変えてドメインランダマイゼーション |

---

## 8. 推奨リポジトリ構成

```
bldc-motor-rl/
├── README.md                     # 概要、結果、使い方
├── requirements.txt
├── setup.py
│
├── envs/
│   ├── __init__.py
│   ├── bldc_motor_env.py         # Gymnasium環境
│   └── assets/
│       └── bldc_motor.xml        # MuJoCo MJCF モデル
│
├── controllers/
│   ├── pid_controller.py         # PIDベースライン
│   └── pid_tuning.py             # Optunaによる最適PIDチューニング
│
├── training/
│   ├── train_ppo.py              # PPO学習スクリプト（Stage 1-2）
│   ├── train_sac.py              # SAC学習スクリプト（Stage 3-4）
│   └── hyperparameter_search.py  # Optunaによるハイパラ探索
│
├── evaluation/
│   ├── evaluate.py               # PID vs RL の比較評価
│   ├── visualize.py              # グラフ・動画生成
│   └── metrics.py                # 評価指標の計算
│
├── results/
│   ├── figures/                   # 比較グラフ
│   └── videos/                    # MuJoCo可視化動画
│
├── notebooks/
│   └── analysis.ipynb            # 結果分析のJupyter Notebook
│
└── logs/                          # TensorBoard, チェックポイント
```

---

## 9. 実行タイムライン（Month 3 の週単位計画）

> **注**: このタイムラインはMonth 1-2（移行ガイドのW1-W8）完了後の想定。移行ガイドのW9-W12とRL戦略のWeekは統合タスク（#4）で一本化する。以下はRL作業の独立タイムライン。

| 週 | 内容 | 成果物 |
|:---|:---|:---|
| **Week 9** | PIDベースラインのOptunaチューニング（並行）+ Gymnasium環境構築 | 最適PIDパラメータ + `bldc_motor_env.py` v1 |
| **Week 10** | PPO学習（RL基礎体験）+ 環境デバッグ。CartPole/Pendulumも並行体験 | PPO学習曲線、環境バグ修正完了 |
| **Week 11** | SAC学習本格実行 + Optunaハイパーパラメータ探索 | 学習済みSACモデル |
| **Week 12** | 複数シナリオ（A-D）比較評価 + 可視化 + GitHub公開 | **公開リポジトリ** |

**W9でPIDチューニングとGymnasium環境構築を並行させる根拠**（motor-control-expertとの合意）: PIDコードは移行ガイドW4で既に完成しているため、W9でのチューニング作業量は少ない。Optuna自動チューニングスクリプトを回しながらGymnasium環境を実装できる。

**RL学習が間に合わないリスクへの対策**: Week 11でSACが収束しない場合、PPOの結果をフォールバックとして使う。PPOはWeek 10で既に学習済みのため、最低限の比較結果は確保できる。

---

## 10. まとめ: 成功のための3つの鍵

1. **環境を先に完璧にする**: RLの学習が失敗する原因の大半は環境のバグ。MuJoCoモデルとGymnasium環境が正しく動くことを最初に確認する。PIDで制御できる環境をまず作る。

2. **報酬関数 = LQR評価関数の符号反転**: 制御工学の知識を最大限活用する。`J = x'Qx + u'Ru` の感覚で報酬を設計すれば、直感が効く。

3. **段階的に複雑さを上げる**: PPO → SAC、ステップ応答 → 軌道追従 → 外乱付き、と段階的に進める。一気に複雑なことをしない。

---

*本文書は、RLでPIDを超えるモータ制御性能を達成するための包括的な技術戦略です。Month 1-2のMuJoCoモデル構築と並行して、RL理論の基礎学習を進め、Month 3で実装に入る計画を想定しています。*
