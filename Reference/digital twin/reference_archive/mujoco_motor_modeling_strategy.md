# MuJoCoでのモータモデリング戦略設計書

**担当**: MuJoCo / 物理シミュレーション専門家
**対象**: PLECS経験者（パワーエレクトロニクス・モータドライブ制御 修士）
**目的**: MuJoCoでBLDCモータの制御シミュレーションを構築し、RLでPID制御を超える性能を達成する

---

## 1. MuJoCoでのモータモデリング：現実的なアプローチ

### 1.1 根本的な設計判断：MuJoCoは電磁気学を扱わない

MuJoCoは**剛体力学シミュレータ**であり、電磁気学（磁束、インダクタンス、相電流）を直接モデル化する機能を持たない。BLDCモータをMuJoCoで扱うには、**電気的振る舞いを機械的等価物に抽象化する**必要がある。

**PLECSとの本質的な違い:**

| 観点 | PLECS | MuJoCo |
|:---|:---|:---|
| モデル基盤 | 回路方程式（KVL/KCL） | ニュートン・オイラー方程式 |
| モータ表現 | 3相巻線、磁束、インダクタンス | トルク入力 + 機械特性 |
| 制御対象 | 相電流 → トルク | トルク（直接） or 位置/速度（サーボ） |
| 時間スケール | μs（PWM周期） | ms（機械系の時定数） |
| シミュレーション目的 | 電気的過渡応答、THD | 機械系の動的応答、接触力学 |

**設計方針**: MuJoCoでは「電流ループの内側」は抽象化し、「トルク出力以降の機械系」を忠実にモデル化する。これは制限ではなく、**異なる抽象化レベルでの正しいアプローチ**である。

### 1.2 MJCFアクチュエータの使い分け

MuJoCoは内部的に1種類のアクチュエータ（`general`）しか持たない。`motor`, `position`, `velocity`等はショートカットであり、`general`の特定のパラメータ設定を簡略化したものである。

#### (a) `motor` — トルク/力の直接制御（最重要）
```xml
<actuator>
  <motor name="bldc_motor" joint="rotor_joint" gear="1"
         ctrllimited="true" ctrlrange="-1.0 1.0"/>
</actuator>
```
- **用途**: ctrl値 × gear = ジョイントに加わるトルク
- **BLDCモデリングでの役割**: 最も基本。PLECSでの「トルク指令」出力に相当
- **RLとの相性**: 最適。エージェントがトルクを直接制御

#### (b) `velocity` — 速度サーボ
```xml
<actuator>
  <velocity name="speed_ctrl" joint="rotor_joint" kv="10.0"
            ctrllimited="true" ctrlrange="-100 100"/>
</actuator>
```
- **用途**: 目標速度追従。内部的にkv×(ctrl - 実速度)のトルクを生成
- **BLDCモデリングでの役割**: 速度制御モードのBLDCに近い抽象化
- **注意**: 内部にフィードバック制御を含むため、RLで制御を学習する場合は不適切

#### (c) `position` — 位置サーボ
```xml
<actuator>
  <position name="pos_ctrl" joint="rotor_joint" kp="100" kv="10"
            ctrllimited="true" ctrlrange="-3.14 3.14"/>
</actuator>
```
- **用途**: 目標位置追従。PD制御を内蔵
- **BLDCモデリングでの役割**: サーボモータ的な用途（ロボットアーム関節等）
- **注意**: PD制御が既に組み込まれているため、RLでPIDを超える場合は使わない

#### (d) `general` — カスタムアクチュエータ（上級）
```xml
<actuator>
  <general name="bldc_custom" joint="rotor_joint"
           gaintype="fixed" gainprm="0.5"
           biastype="affine" biasprm="0 -0.1 -0.02"
           dyntype="filter" dynprm="0.01"
           ctrllimited="true" ctrlrange="-1 1"
           forcelimited="true" forcerange="-5 5"/>
</actuator>
```
- **用途**: トルク定数、バックEMF的減衰、1次遅れフィルタを組み込み可能
- **BLDCモデリングでの役割**: モータの電気的時定数をフィルタで近似、トルク-速度特性をバイアスで模擬
- **パラメータの意味**:
  - `gainprm="0.5"`: トルク定数 Kt に相当（ctrl × 0.5 = トルクの基本ゲイン）
  - `biasprm="0 -0.1 -0.02"`: affineバイアス = b0 + b1×位置 + b2×速度。`b2=-0.02`でバックEMF的な速度依存トルク低下を模擬
  - `dynprm="0.01"`: 1次フィルタの時定数（電気的時定数 L/R の近似）
  - `forcerange`: 最大トルク制限

### 1.3 トルク定数、バックEMF、摩擦の扱い

| 物理現象 | PLECSでの実装 | MuJoCoでの実装 |
|:---|:---|:---|
| トルク定数 Kt | 電流×Kt=トルク | `motor`の`gear`値、または`general`の`gainprm` |
| バックEMF | Ke×ω=誘起電圧 | `general`の`biasprm`（速度比例の負バイアス）、またはジョイントの`damping` |
| クーロン摩擦 | 摩擦モデルブロック | ジョイントの`frictionloss`属性 |
| 粘性摩擦 | 同上 | ジョイントの`damping`属性 |
| ロータ慣性 | 慣性パラメータ | ジョイントの`armature`属性 or ボディの`inertial` |
| 最大トルク | 電流制限 | アクチュエータの`forcerange` |
| 電気的時定数 | L, R回路 | `general`の`dyntype="filter"` + `dynprm` |

**重要**: ジョイントの`armature`属性はロータの等価慣性モーメントを表現する最適な方法である。これは一般化座標系の対角慣性に加算され、数値的にも安定する。

```xml
<joint name="rotor_joint" type="hinge" axis="0 0 1"
       damping="0.001"
       frictionloss="0.01"
       armature="0.0001"/>
```

### 1.4 段階的アプローチの設計哲学

**「シンプルに始めて、必要になったら複雑にする」**

これはMuJoCoコミュニティで広く推奨されるアプローチであり、特にRL応用では極めて重要。理由は：
1. 複雑なモデルはRLの学習を著しく遅くする
2. 問題の切り分け（モデルの問題 vs 制御の問題 vs RLの問題）が困難になる
3. PLECSのような高忠実度モデルは必ずしも制御性能の向上に寄与しない

---

## 2. PLECS経験者がつまずくポイントと対策

### 2.1 思考パラダイムの転換

**つまずきポイント1: 「電流はどこ？」**
- PLECSでは電流がモータ制御の核心。id, iq座標変換、電流PI制御が基本
- MuJoCoでは**電流の概念が存在しない**。トルクが最小単位
- **対策**: 「電流ループは理想的に動作し、トルク指令 = 実トルク」と考える。これは高帯域電流制御器が実装済みのモータドライバに相当する

**つまずきポイント2: 「PWMとスイッチングは？」**
- PLECSではインバータの6スイッチ、デッドタイム、PWM変調が主要要素
- MuJoCoではスイッチングは完全に抽象化される
- **対策**: MuJoCoの制御ループは「速度制御ループ以上の階層」で動作すると理解する

**つまずきポイント3: 「dq変換はどうする？」**
- BLDCの3相 → dq変換はPLECSの定番
- MuJoCoでは1自由度回転 = スカラートルク入力
- **対策**: dq変換の結果（q軸トルク指令）がMuJoCoの`ctrl`入力に相当すると理解する

### 2.2 制御階層の対応関係

```
PLECSでの制御階層:
┌──────────────────────────────────┐
│  位置制御ループ（外側）           │  ← MuJoCoではここを設計/学習
├──────────────────────────────────┤
│  速度制御ループ                   │  ← MuJoCoではここを設計/学習
├──────────────────────────────────┤
│  電流制御ループ（内側）           │  ← MuJoCoでは抽象化（不要）
├──────────────────────────────────┤
│  PWM変調 / インバータ            │  ← MuJoCoでは存在しない
├──────────────────────────────────┤
│  BLDCモータ電気方程式             │  ← MuJoCoではjoint属性で近似
└──────────────────────────────────┘
```

### 2.3 「電流ループなし」でのモータ制御表現

MuJoCoでモータ制御を表現する具体的方法：

**方法A: トルク直接制御（推奨・RL向け）**
```python
import mujoco
import numpy as np

# モデル読み込み
model = mujoco.MjModel.from_xml_path("motor_model.xml")
data = mujoco.MjData(model)

# PID制御器（Python側で実装）
kp, ki, kd = 10.0, 1.0, 0.5
integral_error = 0.0
prev_error = 0.0
target_velocity = 100.0  # rad/s

for step in range(10000):
    # センサ読み取り
    current_velocity = data.qvel[0]  # ジョイント速度 [rad/s]

    # PID計算
    error = target_velocity - current_velocity
    integral_error += error * model.opt.timestep
    derivative = (error - prev_error) / model.opt.timestep

    torque_command = kp * error + ki * integral_error + kd * derivative

    # トルク制限（モータ最大トルク）
    torque_command = np.clip(torque_command, -5.0, 5.0)

    # アクチュエータに入力
    data.ctrl[0] = torque_command

    # シミュレーション1ステップ
    mujoco.mj_step(model, data)
    prev_error = error
```

**方法B: general アクチュエータで電気的特性を近似**
```python
# XMLで general アクチュエータを定義した場合
# dyntype="filter" により、ctrl入力にローパスフィルタが適用される
# → 電気的時定数（L/R）を模擬
# biasprm の速度項により、バックEMFによるトルク低下を模擬
data.ctrl[0] = desired_torque  # フィルタとバイアスが自動適用される
```

---

## 3. 推奨チュートリアル・リソースの学習順序

### 3.1 最小限の学習セット（これだけやれば次に進める）

#### Week 1: MuJoCo基礎

**Step 1: インストールと動作確認（1日目）**
```bash
pip install mujoco
python -c "import mujoco; print(mujoco.__version__)"
```

**Step 2: 公式Colab Tutorial（2-3日目）**
- [MuJoCo Python Tutorial (Google Colab)](https://colab.research.google.com/github/google-deepmind/mujoco/blob/main/python/tutorial.ipynb)
- MJCFの基本構造、Python APIの使い方、ビジュアライゼーションを学ぶ

**Step 3: 公式ドキュメント精読（4-5日目）**
読む順序：
1. [Overview](https://mujoco.readthedocs.io/en/latest/overview.html) — MuJoCoの設計思想
2. [Modeling](https://mujoco.readthedocs.io/en/latest/modeling.html) — **最重要**。アクチュエータモデルの章を特に精読
3. [XML Reference](https://mujoco.readthedocs.io/en/latest/XMLreference.html) — 辞書として使用。`actuator`セクション重点

#### Week 2: 制御基礎

**Step 4: MuJoCo Bootcamp Lecture 3 (Control)（1-2日目）**
- [MuJoCo Bootcamp](https://pab47.github.io/mujoco.html) — Lecture 3
- 振り子のトルク制御、位置制御、速度制御の実装

**Step 5: 自作モータモデルの構築（3-5日目）**
- Level 1モデル（後述）を自分で作成
- Pythonで PID 制御器を実装して速度制御

### 3.2 参考リポジトリ

| リポジトリ | 内容 | 用途 |
|:---|:---|:---|
| [google-deepmind/mujoco](https://github.com/google-deepmind/mujoco) | MuJoCo本体 + サンプル | 公式リファレンス |
| [google-deepmind/mujoco_menagerie](https://github.com/google-deepmind/mujoco_menagerie) | 多数のロボットMJCFモデル | 実際のモータ付きロボットの構成例 |
| [Farama-Foundation/Gymnasium-Robotics](https://github.com/Farama-Foundation/Gymnasium-Robotics) | MuJoCo + RL環境 | RL連携の実装パターン |
| [lvjonok/mujoco-actuators-types](https://github.com/lvjonok/mujoco-actuators-types) | アクチュエータ比較 | motor/position/velocityの挙動の違い |
| [MuJoCo Bootcamp](https://pab47.github.io/mujoco.html) | 14回の体系的講義 | 基礎からの学習 |

### 3.3 読まなくてよいもの（時間節約）

- mujoco-py（旧ライブラリ、非推奨）に関する記事
- MuJoCoのCAPI解説（Pythonバインディングで十分）
- 筋骨格モデル（muscle）の詳細（モータとは無関係）

---

## 4. 段階的モデリングの具体例

### Level 1: 単軸回転体 + トルク入力（最シンプル）

**目的**: MuJoCoの基本を理解する。1つのジョイント、1つのアクチュエータ。

```xml
<!-- level1_simple_rotor.xml -->
<mujoco model="BLDC Level 1 - Simple Rotor">
  <option timestep="0.001" gravity="0 0 0"/>

  <worldbody>
    <!-- 固定ベース -->
    <body name="base" pos="0 0 0.5">
      <geom type="cylinder" size="0.05 0.02" rgba="0.5 0.5 0.5 1"/>

      <!-- ロータ（回転体） -->
      <body name="rotor" pos="0 0 0.03">
        <joint name="rotor_joint" type="hinge" axis="0 0 1"/>
        <geom type="cylinder" size="0.04 0.01" rgba="0.2 0.6 0.9 1" mass="0.1"/>
        <!-- 回転を視覚的に確認するためのマーカー -->
        <geom type="box" size="0.04 0.005 0.012" pos="0.02 0 0"
              rgba="1 0 0 1" mass="0.001"/>
      </body>
    </body>
  </worldbody>

  <actuator>
    <!-- トルク直接入力。ctrl=1 で 1 N・m のトルク -->
    <motor name="torque_input" joint="rotor_joint" gear="1"
           ctrllimited="true" ctrlrange="-1 1"/>
  </actuator>

  <sensor>
    <jointpos name="rotor_pos" joint="rotor_joint"/>
    <jointvel name="rotor_vel" joint="rotor_joint"/>
    <actuatorfrc name="motor_torque" actuator="torque_input"/>
  </sensor>
</mujoco>
```

**Pythonでの使用例:**
```python
import mujoco
import numpy as np

model = mujoco.MjModel.from_xml_path("level1_simple_rotor.xml")
data = mujoco.MjData(model)

# 一定トルクを加える
data.ctrl[0] = 0.5  # 0.5 N·m

# 1秒間シミュレーション
positions = []
velocities = []
for _ in range(1000):
    mujoco.mj_step(model, data)
    positions.append(data.qpos[0])
    velocities.append(data.qvel[0])

# 摩擦なし・重力なしなら速度は線形増加する（τ = J × α）
```

**学習ポイント**:
- MJCF XMLの基本構造（worldbody, body, joint, geom, actuator, sensor）
- `data.ctrl` → トルク → `data.qvel` の因果関係
- タイムステップの影響

---

### Level 2: モータ特性（トルク-速度特性、摩擦）の追加

**目的**: BLDCモータの機械的特性を段階的に導入する。

```xml
<!-- level2_motor_characteristics.xml -->
<mujoco model="BLDC Level 2 - Motor Characteristics">
  <option timestep="0.001" gravity="0 0 0"/>

  <default>
    <joint damping="0.001"/>  <!-- デフォルト粘性摩擦 -->
  </default>

  <worldbody>
    <body name="base" pos="0 0 0.5">
      <geom type="cylinder" size="0.05 0.02" rgba="0.5 0.5 0.5 1"/>

      <body name="rotor" pos="0 0 0.03">
        <joint name="rotor_joint" type="hinge" axis="0 0 1"
               armature="0.0005"
               damping="0.002"
               frictionloss="0.01"/>
        <geom type="cylinder" size="0.04 0.01" rgba="0.2 0.6 0.9 1" mass="0.1"/>
        <geom type="box" size="0.04 0.005 0.012" pos="0.02 0 0"
              rgba="1 0 0 1" mass="0.001"/>
      </body>
    </body>
  </worldbody>

  <actuator>
    <!-- general アクチュエータで電気的特性を近似 -->
    <general name="bldc_motor" joint="rotor_joint"
             gaintype="fixed" gainprm="0.5 0 0"
             biastype="affine" biasprm="0 0 -0.005"
             dyntype="filter" dynprm="0.005 0 0"
             ctrllimited="true" ctrlrange="-1 1"
             forcelimited="true" forcerange="-2 2"/>
  </actuator>

  <!--
    パラメータの物理的意味:
    - gainprm="0.5": トルク定数 Kt=0.5 N·m/A 相当
    - biasprm="0 0 -0.005": 速度に比例する負トルク（バックEMF効果）
      → 高速回転時にトルクが減少する特性を模擬
    - dynprm="0.005": 電気的時定数 5ms (L/R の近似)
    - armature="0.0005": ロータ慣性モーメント 5e-4 kg·m²
    - damping="0.002": 粘性摩擦係数 (ベアリング等)
    - frictionloss="0.01": クーロン摩擦 0.01 N·m
    - forcerange="-2 2": 最大トルク ±2 N·m
  -->

  <sensor>
    <jointpos name="rotor_pos" joint="rotor_joint"/>
    <jointvel name="rotor_vel" joint="rotor_joint"/>
    <actuatorfrc name="motor_torque" actuator="bldc_motor"/>
  </sensor>
</mujoco>
```

**Pythonでの速度PID制御:**
```python
import mujoco
import numpy as np

model = mujoco.MjModel.from_xml_path("level2_motor_characteristics.xml")
data = mujoco.MjData(model)

# PID制御器
class PIDController:
    def __init__(self, kp, ki, kd, output_limits=(-1, 1)):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.limits = output_limits
        self.integral = 0.0
        self.prev_error = 0.0

    def compute(self, error, dt):
        self.integral += error * dt
        derivative = (error - self.prev_error) / dt if dt > 0 else 0.0
        output = self.kp * error + self.ki * self.integral + self.kd * derivative
        output = np.clip(output, *self.limits)
        self.prev_error = error
        return output

pid = PIDController(kp=0.1, ki=0.5, kd=0.01)
target_speed = 50.0  # rad/s

times, speeds, torques = [], [], []
dt = model.opt.timestep

for step in range(5000):
    current_speed = data.qvel[0]
    error = target_speed - current_speed
    ctrl = pid.compute(error, dt)
    data.ctrl[0] = ctrl

    mujoco.mj_step(model, data)

    times.append(step * dt)
    speeds.append(current_speed)
    torques.append(data.sensordata[2])  # actuatorfrc sensor

# matplotlibで可視化（別途実装）
```

**学習ポイント**:
- `armature`, `damping`, `frictionloss` による機械的特性の表現
- `general`アクチュエータによる電気的特性の近似
- PID制御のPython実装とチューニング
- PLECSの電流ループ → MuJoCoのトルク直接制御の対応

---

### Level 3: 負荷付きモータ（ギア、イナーシャ）

**目的**: ギアトレインと負荷イナーシャを追加。ロボット関節駆動のモデルに近づける。

```xml
<!-- level3_motor_with_load.xml -->
<mujoco model="BLDC Level 3 - Motor with Gear and Load">
  <option timestep="0.001" gravity="0 0 -9.81"/>

  <worldbody>
    <!-- 固定ベース（壁面取付を想定） -->
    <body name="base" pos="0 0 1">
      <geom type="cylinder" size="0.05 0.03" rgba="0.5 0.5 0.5 1"/>

      <!-- モータ側（高速・低トルク） -->
      <body name="motor_rotor" pos="0 0 0.04">
        <joint name="motor_joint" type="hinge" axis="0 0 1"
               armature="0.0005"
               damping="0.001"
               frictionloss="0.005"/>
        <geom type="cylinder" size="0.02 0.01" rgba="0.9 0.3 0.1 1" mass="0.05"/>
      </body>

      <!-- 負荷側アーム（ギアを介して接続） -->
      <body name="arm" pos="0 0 0.06">
        <joint name="load_joint" type="hinge" axis="0 0 1"
               damping="0.01"
               frictionloss="0.02"/>
        <!-- アーム形状 -->
        <geom type="capsule" fromto="0 0 0 0.3 0 0" size="0.02"
              rgba="0.2 0.7 0.3 1" mass="0.5"/>
        <!-- 先端のペイロード -->
        <body name="payload" pos="0.3 0 0">
          <geom type="sphere" size="0.03" rgba="0.9 0.9 0.1 1" mass="0.2"/>
        </body>
      </body>
    </body>
  </worldbody>

  <!-- ギア比をequalityで実現 -->
  <equality>
    <!-- motor_joint の回転 × 50 = load_joint の回転 (減速比 50:1) -->
    <joint joint1="motor_joint" joint2="load_joint"
           polycoef="0 50 0 0 0"/>
  </equality>

  <actuator>
    <!-- モータ側ジョイントにトルク入力 -->
    <!-- gear="50": 減速比50でトルクが増幅される -->
    <motor name="bldc_motor" joint="motor_joint" gear="50"
           ctrllimited="true" ctrlrange="-1 1"
           forcelimited="true" forcerange="-3 3"/>
  </actuator>

  <!--
    注: ギアの実装方法は複数ある
    方法1 (上記): equality constraint + gear属性
    方法2: motor の gear 属性のみで簡易モデル
    方法3: tendon を使った伝達メカニズム

    ここではequalityで明示的にギア拘束を定義し、
    gear属性でトルク増幅を表現
  -->

  <sensor>
    <jointpos name="motor_pos" joint="motor_joint"/>
    <jointvel name="motor_vel" joint="motor_joint"/>
    <jointpos name="load_pos" joint="load_joint"/>
    <jointvel name="load_vel" joint="load_joint"/>
    <actuatorfrc name="motor_torque" actuator="bldc_motor"/>
  </sensor>
</mujoco>
```

**別のアプローチ（シンプルなgearのみ）:**
```xml
<!-- より簡潔な方法: ギアをアクチュエータのgear属性で表現 -->
<mujoco model="BLDC Level 3b - Simple Gear">
  <option timestep="0.001" gravity="0 0 -9.81"/>

  <worldbody>
    <body name="base" pos="0 0 1">
      <geom type="box" size="0.05 0.05 0.02" rgba="0.5 0.5 0.5 1"/>

      <!-- 負荷側アーム -->
      <body name="arm" pos="0 0 0.03">
        <joint name="arm_joint" type="hinge" axis="0 1 0"
               armature="0.0005"
               damping="0.005"
               frictionloss="0.01"/>
        <geom type="capsule" fromto="0 0 0 0.3 0 0" size="0.02"
              rgba="0.2 0.7 0.3 1" mass="0.5"/>
        <body name="payload" pos="0.3 0 0">
          <geom type="sphere" size="0.03" rgba="0.9 0.9 0.1 1" mass="0.2"/>
        </body>
      </body>
    </body>
  </worldbody>

  <actuator>
    <!-- gear="50" により、ctrl=1 で 50 N·m のトルクが関節に加わる -->
    <!-- ギア減速のイナーシャ反映はarmatureに含める -->
    <motor name="geared_bldc" joint="arm_joint" gear="50"
           ctrllimited="true" ctrlrange="-0.1 0.1"/>
  </actuator>

  <sensor>
    <jointpos name="arm_pos" joint="arm_joint"/>
    <jointvel name="arm_vel" joint="arm_joint"/>
    <actuatorfrc name="motor_torque" actuator="geared_bldc"/>
  </sensor>
</mujoco>
```

**学習ポイント**:
- ギアの2つのモデル化方法（equality制約 vs gear属性のみ）
- 重力下での制御（重力補償の必要性）
- `armature`に等価換算イナーシャを含める手法
- 負荷トルクの概念（PLECS経験者には馴染みやすい）

---

### Level 4: マルチDOFシステム（2軸ロボットアーム）

**目的**: 複数モータの協調制御。RL適用の基盤となるシステム。

```xml
<!-- level4_two_dof_arm.xml -->
<mujoco model="BLDC Level 4 - 2-DOF Robot Arm">
  <option timestep="0.001" gravity="0 0 -9.81"/>

  <default>
    <joint armature="0.001" damping="0.005" frictionloss="0.01"/>
    <geom rgba="0.7 0.7 0.7 1"/>
  </default>

  <worldbody>
    <!-- 固定ベース -->
    <body name="base" pos="0 0 0.5">
      <geom type="cylinder" size="0.06 0.03" rgba="0.3 0.3 0.3 1"/>

      <!-- Link 1: 肩関節 -->
      <body name="link1" pos="0 0 0.04">
        <joint name="shoulder" type="hinge" axis="0 1 0"
               range="-1.57 1.57" limited="true"/>
        <geom type="capsule" fromto="0 0 0 0.25 0 0" size="0.025"
              rgba="0.2 0.6 0.9 1" mass="0.8"/>

        <!-- Link 2: 肘関節 -->
        <body name="link2" pos="0.25 0 0">
          <joint name="elbow" type="hinge" axis="0 1 0"
                 range="-2.35 0" limited="true"/>
          <geom type="capsule" fromto="0 0 0 0.2 0 0" size="0.02"
                rgba="0.9 0.4 0.2 1" mass="0.5"/>

          <!-- エンドエフェクタ -->
          <body name="end_effector" pos="0.2 0 0">
            <geom type="sphere" size="0.025" rgba="0.1 0.9 0.1 1" mass="0.1"/>
            <site name="ee_site" pos="0 0 0" size="0.01"/>
          </body>
        </body>
      </body>
    </body>

    <!-- 目標位置の可視化 -->
    <body name="target" pos="0.3 0 0.5" mocap="true">
      <geom type="sphere" size="0.02" rgba="1 0 0 0.5" contype="0" conaffinity="0"/>
    </body>
  </worldbody>

  <actuator>
    <!-- 肩モータ（大トルク） -->
    <motor name="shoulder_motor" joint="shoulder" gear="80"
           ctrllimited="true" ctrlrange="-1 1"
           forcelimited="true" forcerange="-50 50"/>

    <!-- 肘モータ（小トルク） -->
    <motor name="elbow_motor" joint="elbow" gear="50"
           ctrllimited="true" ctrlrange="-1 1"
           forcelimited="true" forcerange="-30 30"/>
  </actuator>

  <sensor>
    <jointpos name="shoulder_pos" joint="shoulder"/>
    <jointvel name="shoulder_vel" joint="shoulder"/>
    <jointpos name="elbow_pos" joint="elbow"/>
    <jointvel name="elbow_vel" joint="elbow"/>
    <actuatorfrc name="shoulder_torque" actuator="shoulder_motor"/>
    <actuatorfrc name="elbow_torque" actuator="elbow_motor"/>
    <framepos name="ee_pos" objtype="site" objname="ee_site"/>
  </sensor>
</mujoco>
```

**学習ポイント**:
- マルチボディの階層構造（body内にbody）
- 関節制限 `range` と `limited`
- `site` によるエンドエフェクタ位置の取得
- `mocap` ボディによる目標位置の可視化
- RL環境（Gymnasium）への発展の基盤

---

## 5. 3ヶ月後の成果物として何をGitHubに公開すべきか

### 5.1 推奨リポジトリ構成

```
bldc-mujoco-rl/
├── README.md                    # プロジェクト概要、動機、結果サマリー
├── LICENSE                      # MIT License
├── requirements.txt             # Python依存パッケージ
├── setup.py or pyproject.toml
│
├── models/                      # MJCF XMLモデル群
│   ├── level1_simple_rotor.xml
│   ├── level2_motor_characteristics.xml
│   ├── level3_motor_with_load.xml
│   └── level4_two_dof_arm.xml
│
├── envs/                        # Gymnasium環境定義
│   ├── __init__.py
│   ├── motor_speed_env.py       # 速度追従タスク
│   └── arm_reach_env.py         # リーチングタスク
│
├── controllers/                 # 古典制御（ベースライン）
│   ├── __init__.py
│   └── pid_controller.py        # PID制御器
│
├── training/                    # RL学習スクリプト
│   ├── train_speed_control.py   # 速度制御のRL学習
│   └── train_arm_reach.py       # リーチングのRL学習
│
├── evaluation/                  # 評価・比較
│   ├── compare_pid_vs_rl.py     # PID vs RL の定量比較
│   └── plot_results.py          # 結果可視化
│
├── notebooks/                   # Jupyter Notebook
│   ├── 01_mujoco_basics.ipynb   # MuJoCo入門
│   ├── 02_motor_modeling.ipynb  # モータモデリング解説
│   ├── 03_pid_baseline.ipynb    # PID制御のベースライン
│   └── 04_rl_training.ipynb     # RL学習と結果分析
│
├── results/                     # 学習済みモデル、ログ
│   ├── models/                  # 学習済み重み
│   ├── logs/                    # TensorBoardログ
│   └── figures/                 # 結果図表
│
└── docs/                        # ドキュメント
    └── motor_modeling_guide.md  # モータモデリングの設計判断の解説
```

### 5.2 GitHubで差別化できるポイント

1. **BLDCモータに特化したMuJoCoモデリング解説**
   - 「PLECSからMuJoCoへの移行」という視点はニッチだが需要がある
   - 段階的モデリングの解説は教育的価値が高い

2. **PID vs RL の定量的比較**
   - 同一タスク・同一モデルでの公平な比較
   - 評価指標: 立ち上がり時間、オーバーシュート、定常偏差、外乱応答
   - 「RLが勝てるシナリオ」と「PIDで十分なシナリオ」の考察

3. **再現可能な実験**
   - 乱数シード固定、ハイパーパラメータ明記
   - `requirements.txt`で環境再現
   - Jupyter Notebookで結果を段階的に再現可能

### 5.3 最終ゴールの具体像

**最小成果物（必達）:**
- Level 2モデルでの速度制御: PID vs RL比較
- 定量的な結果テーブルとグラフ
- READMEに動機・手法・結果を簡潔に記載

**理想成果物（到達できれば）:**
- Level 4の2軸アームでのリーチングタスク
- Gymnasium環境として再利用可能な設計
- 外乱ロバスト性、パラメータ変動へのロバスト性の比較
- GIFアニメーションによるデモ

---

## 付録: MuJoCoパラメータとBLDCモータ仕様の対応チートシート

| BLDCモータ仕様 | 単位 | MuJoCoパラメータ | 設定場所 |
|:---|:---|:---|:---|
| トルク定数 Kt | N·m/A | `gear` or `gainprm` | actuator |
| 最大トルク | N·m | `forcerange` | actuator |
| 定格速度 | rpm → rad/s | （制御側で管理） | Python |
| ロータ慣性 J | kg·m² | `armature` | joint |
| 粘性摩擦係数 B | N·m·s/rad | `damping` | joint |
| クーロン摩擦 | N·m | `frictionloss` | joint |
| 電気的時定数 L/R | s | `dynprm`（filter） | actuator (general) |
| バックEMF Ke | V·s/rad | `biasprm`（速度項）or `damping` | actuator or joint |
| ギア比 N | - | `gear` or equality | actuator / equality |
| 電流制限 | A | `ctrlrange` (Kt換算) | actuator |

---

*本設計書は motor-control-expert および rl-expert と連携して使用されることを想定しています。*
