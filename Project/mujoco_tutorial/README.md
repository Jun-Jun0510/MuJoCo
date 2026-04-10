# MuJoCo Python チュートリアル 学習ノート (W5)

DeepMind 公式 Colab "MuJoCo Python Tutorial" を自走する形で、MuJoCo 3.x の Python API を一通り触るための学習ノート。

- **目的**: W6 以降で `bldc_motor.xml` を書いて Gymnasium Env にする前に、MJCF + Python API の基礎を固めておく。
- **進め方**: 各セクションごとに最小モデル (`models/NN_*.xml`) と実行スクリプト (`NN_*.py`) をセットで作り、出力は `../figures/mujoco_tutorial/` に保存。本ノート (README.md) を眺めながら図を見て進める。
- **環境**: `mujoco==3.6.0`, `mediapy==1.2.6`, Python 3.12 venv (`/Users/ohatajun/Desktop/MuJoCo/.venv`)。

```
mujoco_tutorial/
├── README.md              ← 本ノート (成果物)
├── models/
│   ├── 01_ball.xml        ← Section 1 用
│   ├── 02_pendulum.xml    ← Section 2 用
│   ├── 03_contact.xml     ← Section 3 用
│   ├── 04_actuator.xml    ← Section 4 用
│   └── 05_sensor.xml      ← Section 5 用
├── 01_load_render.py      ← Section 1 スクリプト
├── 02_basic_sim.py        ← Section 2 スクリプト
├── 03_contact.py          ← Section 3 スクリプト
├── 04_actuator.py         ← Section 4 スクリプト
├── 05_sensor.py           ← Section 5 スクリプト
└── 06_viewer.py           ← Section 6 スクリプト
```

実行方法 (プロジェクトルートから):

```bash
./.venv/bin/python Project/mujoco_tutorial/01_load_render.py
./.venv/bin/python Project/mujoco_tutorial/02_basic_sim.py
```

---

## Section 1: Loading & rendering

**ゴール**: MJCF を読み込んで可視化するまでの最短経路を覚える。

### 1.1 3 大オブジェクト

| オブジェクト | 役割 | 主な属性 |
|---|---|---|
| `mujoco.MjModel` | **静的** な物理モデル (不変) | `nq`, `nv`, `opt.timestep`, `opt.gravity`, `nbody`, `ngeom` |
| `mujoco.MjData` | **動的** な状態 (時刻 `t` の snapshot) | `qpos`, `qvel`, `qacc`, `ctrl`, `time`, `body('name').xpos` |
| `mujoco.Renderer` | オフスクリーン描画器 | `update_scene(data, camera=-1)`, `render()` |

最短コード:

```python
model = mujoco.MjModel.from_xml_path("models/01_ball.xml")
data  = mujoco.MjData(model)
mujoco.mj_forward(model, data)          # 運動学だけ更新 (積分しない)

with mujoco.Renderer(model, 480, 640) as renderer:
    renderer.update_scene(data, camera=-1)   # -1 = free camera
    pixels = renderer.render()               # np.ndarray (H, W, 3) uint8
```

> **Tip**: `Renderer` は `with` 文で使うと OpenGL コンテキストを確実に破棄してくれる。

### 1.2 `nq` と `nv` — 自由度の数え方

MuJoCo は位置ベクトル `qpos` と速度ベクトル `qvel` の **次元が一致しない** ことがある。
これはクォータニオン表現のため:

| joint type | `nq` (qpos 次元) | `nv` (qvel 次元) | 内訳 |
|---|---|---|---|
| `hinge` | 1 | 1 | 角度 / 角速度 |
| `slide` | 1 | 1 | 位置 / 速度 |
| `ball`  | 4 | 3 | quat / 角速度 |
| `free`  | 7 | 6 | pos(3) + quat(4) / linvel(3) + angvel(3) |

`01_ball.xml` は `freejoint` 1 個なので `nq=7, nv=6`。確認:

```python
print(model.nq, model.nv)   # → 7 6
print(data.qpos)            # [0 0 0.5  1 0 0 0]  (pos + unit quat)
```

### 1.3 `mj_forward` vs `mj_step`

- **`mj_forward(model, data)`**:
  現在の `qpos, qvel` から **運動学・動力学を計算するだけ** (積分しない)。
  `xpos` や `qacc` は更新されるが `time` は進まない。
  初期条件を書き換えた直後、描画する前に 1 回呼ぶ。

- **`mj_step(model, data)`**:
  1 時間刻み分だけ **積分** して `qpos, qvel, time` を進める。
  シミュレーションループの本体。

### 1.4 座標の読み方

ボディ座標の取得は 2 通り:

```python
data.body("ball").xpos     # (3,) 世界座標
data.xpos[body_id]         # 同じものを id 経由で
```

今回の結果 (1 秒落下後):

```
t=0.0s : ball.xpos = [0, 0, 0.5]     (中心が z=0.5)
t=1.0s : ball.xpos = [0, 0, 0.0996]  (床半径 0.1 に乗って静止)
```

**成果物**: `figures/mujoco_tutorial/01_load_render.png` (初期 / 1 秒後の 2 枚並び)

---

## Section 2: Basic simulation

**ゴール**: `mj_step` ループを回して時系列をロギングし、動画 + グラフに落とす。

### 2.1 単振子モデル (`02_pendulum.xml`)

```
world
 └─ pivot (box, pos=(0,0,1))  ← 可視化用の固定箱 (接触 OFF)
     └─ arm  (hinge joint, axis=(0,1,0))
         ├─ arm_shaft : capsule 0 → -0.5 (z 方向)
         └─ tip       : sphere r=0.05, mass=0.3
```

- `hinge joint` なので `nq = nv = 1`。`qpos[0]` が角度 [rad]、`qvel[0]` が角速度 [rad/s]。
- `damping="0.001"` は粘性摩擦。保存系に近づけたい時は小さく。

### 2.2 シミュレーションループの定石

```python
T_sim = 4.0
dt = model.opt.timestep          # 2 ms
N  = int(T_sim / dt)             # 2000 ステップ

t_log  = np.zeros(N); th_log = np.zeros(N); om_log = np.zeros(N)

for k in range(N):
    mujoco.mj_step(model, data)
    t_log[k]  = data.time
    th_log[k] = data.qpos[0]
    om_log[k] = data.qvel[0]
```

配列を先に確保 → インデックスで書き込む。`list.append` より速いし GC 圧力も低い。

### 2.3 動画保存: mediapy / PIL-GIF

MuJoCo 公式は `mediapy.write_video()` を使うが **内部で ffmpeg を呼ぶ**。macOS に ffmpeg が無い場合は PIL で GIF を書くのが楽:

```python
from PIL import Image
pil_frames = [Image.fromarray(f) for f in frames]
pil_frames[0].save(
    gif_path, save_all=True, append_images=pil_frames[1:],
    duration=int(1000 / fps), loop=0,
)
```

`frames` 収集はフレーム間隔を `render_every = round(1/(fps·dt))` で間引く:

```python
with mujoco.Renderer(model, 360, 480) as renderer:
    for k in range(N):
        mujoco.mj_step(model, data)
        if k % render_every == 0:
            renderer.update_scene(data, camera=-1)
            frames.append(renderer.render())   # (H, W, 3) uint8
```

**成果物**: `figures/mujoco_tutorial/02_pendulum.gif` (4 秒 × 60 fps = 240 フレーム)

### 2.4 解析解との突き合わせ

線形化単振子: `θ(t) = θ₀ cos(ωₙ t)`, `ωₙ = √(g/L)`。
MuJoCo の全非線形結果と重ねて、周期のずれを目視確認する。θ₀=45° では非線形周期 ≒ 線形周期 × 1.04 (≈ 4 % の補正) が見えるはず。

### 2.5 エネルギー保存チェック

エネルギーを計算して時間プロットすると、積分誤差と摩擦散逸が **数値的に可視化** できる:

```python
I  = 0.3 * L ** 2                         # tip mass での近似慣性モーメント
KE = 0.5 * I * om_log ** 2
PE = 0.3 * g * L * (1.0 - np.cos(th_log)) # 支点を基準
E  = KE + PE
```

今回の結果: `E(0)=0.4310 J → E(4s)=0.4189 J (-2.81 %)` ← `damping=0.001` 由来でほぼ正しい。

### 2.6 【重要な罠】エネルギーが一気に落ちる原因

**最初の試行では 4 秒で −99 % もエネルギーが消えた**。原因と対処を残しておく。

| 疑った犯人 | 結果 |
|---|---|
| `damping=0.02` が大きい? | 0.001 にしても −99 % |
| `implicitfast` の数値減衰? | `RK4` にしても −99 % |
| 運動方程式が壊れている? | `damping=0` でもダメ |
| **ピボット箱 × アーム/先端球 の自己接触** | **← 真犯人** |

振子の **pivot box (可視化用の立方体)** がアームの capsule / tip sphere と幾何的に重なっていて、MuJoCo の接触ソルバが毎ステップ接触力を発生させ、摩擦エネルギーを吸っていた。

**対処**: 振子系は接触判定が不要なので、すべての pendulum geom に:

```xml
<geom ... contype="0" conaffinity="0"/>
```

を付けて **自己接触を完全に無効化**。これで −2.81 % (減衰由来のみ) に収まった。

> **教訓**:
> 1. **保存系を作るときは真っ先に接触マスクを疑う**。
> 2. `contype=0, conaffinity=0` は「その geom は接触演算に関わらない」という意味 (描画はされる)。
> 3. 原因切り分けには `damping=0` で積分器だけの挙動を見るのが一番速い。
> 4. BLDC モータのロータ側も、接触不要な部品には同じ処理を入れるべき。

### 2.7 積分器の選び方

| integrator | 特徴 | 使いどころ |
|---|---|---|
| `Euler` (default) | 陽的オイラー。高速だが散逸的 | ロボットの剛体接触でとりあえず回す |
| `implicit` / `implicitfast` | 陰解法。大きい `timestep` で安定 | 関節が多くて硬い系 |
| `RK4` | 4 次 Runge-Kutta。保存系で高精度 | **本節の単振子, エネルギー保存を見たい時** |

本節では `integrator="RK4"` を選択した。

**成果物**: `figures/mujoco_tutorial/02_basic_sim.png` (角度 / 角速度 / エネルギーの 3 段プロット)

---

## Section 3: Contacts

**ゴール**: 接触検出 API (`data.ncon`, `data.contact`, `mj_contactForce`) を使いこなす。摩擦パラメータが物理挙動に与える影響を可視化する。

### 3.1 モデル (`03_contact.xml`)

```
world
 ├─ floor (infinite plane, condim=3, friction=0.01)
 ├─ block_lo  (box 0.04³, freejoint, μ=0.05, 青)  ← 氷上滑り
 ├─ block_mid (box 0.04³, freejoint, μ=0.3,  緑)  ← 木材程度
 └─ block_hi  (box 0.04³, freejoint, μ=0.8,  赤)  ← ゴム程度
```

- 全ブロックに初速 vx=3 m/s + 高さ 0.15 m から落下。
- ブロック同士は接触しない: `contype/conaffinity` ビットマスクで分離 (後述)。
- 箱を使う理由: 球体は転がり無滑りで摩擦差が出にくい。箱なら純粋な滑り摩擦 `a ≈ μg` が効く。

### 3.2 接触データの読み出し

```python
# 接触数
print(data.ncon)  # → e.g. 10

# 各接触の詳細
for i in range(data.ncon):
    c = data.contact[i]
    c.pos      # (3,) 接触点の世界座標 (2 geom の中間点)
    c.dist     # 符号付き距離 (負=めり込み)
    c.frame    # (9,) 接触フレーム (行優先 3x3: [法線, 接線1, 接線2])
    c.geom1    # geom ID (番号が小さい方)
    c.geom2    # geom ID (番号が大きい方)

# 6D 接触力 (接触フレーム座標系)
forcetorque = np.zeros(6)
mujoco.mj_contactForce(model, data, i, forcetorque)
# forcetorque[0] : 法線力 (N)
# forcetorque[1:3] : 接線力 = 摩擦力 (N)
# forcetorque[3:6] : トルク (N·m, condim≥4 の場合)
```

> **注意**: `mj_contactForce` は `geom2` 側に作用する力を返す。`geom1` 側は反作用 (符号反転)。

### 3.3 `friction` の 3 成分

geom レベルの `friction` は 3 つの値を持つ:

| 成分 | 意味 | 典型値 |
|---|---|---|
| **slide** (μ_tangent) | 接線方向の滑り摩擦 | 0.05〜2.0 |
| **spin** (μ_torsion) | 法線軸まわりの回転摩擦 | 0.001〜0.01 |
| **roll** (μ_rolling) | 接線軸まわりの転がり摩擦 | 0.0001〜0.005 |

接触レベルでは 5 成分に展開される: `[μ_tan1, μ_tan2, μ_torsion, μ_roll1, μ_roll2]`。
slide が 2 方向に分かれるのは、異方性摩擦を表現するため。

**摩擦の混合規則**:
- 2 つの geom の `priority` が等しい場合 → 要素ごとの **max**
- `priority` が異なる場合 → 高い方の値を使う
- → 床の friction を小さくしておけば `max(floor, block) = block` で意図通りに動く

### 3.4 `condim` (接触次元)

接触ソルバが解く制約の次元数:

| condim | 内訳 | 用途 |
|---|---|---|
| 1 | 法線のみ | 摩擦レス接触 (ビリヤード台のクッション等) |
| 3 | 法線 + 接線×2 | **標準的な摩擦接触** ← 本節で使用 |
| 4 | 3 + spin | 回転摩擦も欲しい場合 |
| 6 | 4 + roll×2 | 完全摩擦モデル (球体の転がり抵抗等) |

今回は箱の滑りを見たいので `condim=3` (法線 + 接線2方向) で十分。

### 3.5 `contype` / `conaffinity` — 接触マスク

2 つの geom が接触するかどうかは **ビット演算** で決まる:

```
contact_enabled = (geom1.contype & geom2.conaffinity) ||
                  (geom2.contype & geom1.conaffinity)
```

本モデルでの設定:

| geom | contype | conaffinity | 接触する相手 |
|---|---|---|---|
| floor | 7 (=0b111) | 7 | 全ブロック |
| block_lo | 1 (=0b001) | 1 | floor のみ |
| block_mid | 2 (=0b010) | 2 | floor のみ |
| block_hi | 4 (=0b100) | 4 | floor のみ |

ブロック同士: `1 & 2 = 0`, `1 & 4 = 0`, `2 & 4 = 0` → **接触しない**。
Section 2 で学んだ `contype=0, conaffinity=0` は「何とも接触しない」の特殊ケース。

### 3.6 `solref` / `solimp` — 接触ソルバパラメータ

接触制約を解くソルバの挙動を調整する 2 つのパラメータ:

- **`solref`** = `(timeconst, dampratio)` — 制約違反を解消する参照応答
  - デフォルト: `"0.02 1"` = 時定数 20 ms, 臨界減衰 (ζ=1.0)
  - 小さい timeconst → 硬い接触 (速く解消、振動しやすい)
  - 負の値にすると `(-stiffness, -damping)` 形式に切り替わる

- **`solimp`** = `(d₀, d_width, width, midpoint, power)` — インピーダンス曲線
  - めり込み量に応じた制約力の強さを定義
  - 大きい値 → 強い制約、小さい値 → 弱い (めり込みやすい)

> 通常はデフォルトのまま使い、接触が不安定な時だけ調整する。

### 3.7 接触力の可視化

レンダリング時に `MjvOption` で可視化フラグを ON にする:

```python
scene_option = mujoco.MjvOption()
scene_option.flags[mujoco.mjtVisFlag.mjVIS_CONTACTPOINT] = True
scene_option.flags[mujoco.mjtVisFlag.mjVIS_CONTACTFORCE] = True
renderer.update_scene(data, camera=-1, scene_option=scene_option)
```

### 3.8 結果と理論値の比較

平面上の滑り摩擦: `a = μg`, 停止時間 `t_stop = v₀/(μg)`, 停止距離 `x_stop = v₀²/(2μg)`:

| ブロック | μ | a [m/s²] | t_stop [s] | x_stop (理論) [m] | x_stop (実測) [m] |
|---|---|---|---|---|---|
| low (青) | 0.05 | 0.49 | 6.12 | 9.17 | (4s 時点 vx=1.0, 未停止) |
| mid (緑) | 0.3 | 2.94 | 1.02 | 1.53 | 1.56 |
| high (赤) | 0.8 | 7.85 | 0.38 | 0.57 | 0.66 |

- mid は理論とほぼ一致 (Δ=2%)。
- high はバウンド中に空中移動する分だけ余分に進む (Δ=16%)。
- 法線力は着地時にスパイク (最大 ~80 N) → 定常値 mg=4.91 N に収束。
- 接触点数: 箱は面接触で最大 4 点/個。低摩擦ブロックは回転して辺接触 (2 点) になることも。

### 3.9 Section 2 との対比: 「必要な接触」と「不要な接触」

| | Section 2 (振子) | Section 3 (滑りブロック) |
|---|---|---|
| 接触の役割 | **不要** (保存系を壊す邪魔者) | **必要** (物理現象の主役) |
| 対処 | `contype=0, conaffinity=0` で無効化 | `contype/conaffinity` で選択的に有効化 |
| 教訓 | デフォルトで接触が ON → 意図しない自己接触に注意 | ビットマスクで「誰と誰が触るか」を明示設計する |

> **W6 での BLDC モータ**: ロータ部品は接触不要 → Section 2 パターン。負荷との物理接触が要る場合は Section 3 パターン。

**成果物**: `figures/mujoco_tutorial/03_contact.gif` (3 秒, 30 fps), `03_contact_force.png` (5 段プロット)

---

## Section 4: Actuators

**ゴール**: MuJoCo のアクチュエータ 3 タイプ (`motor`, `position`, `velocity`) の動作原理を理解し、W6 で BLDC トルク入力を設計するための見通しを立てる。

### 4.1 共通モデル

```
world
 └─ pivot (z=0.5, fixed)
     └─ arm (hinge, Y 軸回り, damping=0.01)
         └─ tip (sphere, mass=1.0 kg, L=0.3 m)
```

重力下で水平配置 → 重力トルク `τ_g = mgL·cos(θ)` ≈ 2.94 N·m (θ=0)。
アクチュエータのタイプだけ差し替えて比較する。

### 4.2 アクチュエータの 3 タイプ

#### (A) `<motor>` — 直接トルク入力

```xml
<motor name="torque" joint="hinge" gear="1.0"
       ctrllimited="true" ctrlrange="-10 10"/>
```

- **出力**: `force = gear × ctrl`
- `ctrl` = 3.0 → アクチュエータが 3.0 N·m を直接出す
- **フィードバックなし**: 自分で制御ループを書く必要がある
- **W6 で BLDC に使うのはこれ**: Python 側で FOC → Te を計算 → `data.ctrl[0] = Te`

#### (B) `<position>` — 位置サーボ

```xml
<position name="pos_servo" joint="hinge"
          kp="20" kv="4"
          ctrllimited="true" ctrlrange="-1.57 1.57"/>
```

- **出力**: `force = kp·(ctrl - qpos) - kv·qvel`
- `ctrl` = π/4 → θ=45° を目標にバネ＋ダンパー制御
- 重力があると **定常偏差** が出る: `Δθ = τ_g / kp` ≈ 2.08/20 ≈ 6° (実測 +5.5°)
- 偏差をゼロにするには積分器が必要 → MuJoCo 組み込みではなく Python 側で実装

#### (C) `<velocity>` — 速度サーボ

```xml
<velocity name="vel_servo" joint="hinge"
          kv="10"
          ctrllimited="true" ctrlrange="-5 5"
          forcelimited="true" forcerange="-10 10"/>
```

- **出力**: `force = kv·(ctrl - qvel)`
- `ctrl` = 2.0 → ω=2 rad/s を目標に比例制御
- `forcerange` で出力トルクをクランプ → 重力補償と加速の両方に力を使う
- 定常時: `ω ≈ target` だが重力トルク変動で微小な速度リップル

### 4.3 `data.ctrl` の仕組み

```python
# アクチュエータ数
model.nu  # → XML で定義した <actuator> の子要素の数

# 制御入力を書く (mj_step の前に)
data.ctrl[0] = 3.0   # 0 番目のアクチュエータに入力

# 実際に出た力を読む (mj_step の後に)
data.actuator_force[0]  # → motor なら ctrl×gear, position なら kp(ctrl-q)-kv*v
```

処理フロー (`mj_step` 内部):
```
data.ctrl[i]
 → ctrlrange でクランプ
 → activation dynamics (dyntype, 通常は none)
 → gain function (motor: gear×ctrl, position: kp(ctrl-q)-kv·v, ...)
 → forcerange でクランプ
 → 一般化力として関節に付加
 → 加速度計算 → 積分 → qpos, qvel 更新
```

### 4.4 重要な属性まとめ

| 属性 | 意味 | motor | position | velocity |
|---|---|---|---|---|
| `gear` | 機械的ゲイン比 | ✅ 出力 = gear×ctrl | — | — |
| `kp` | 位置ゲイン (剛性) | — | ✅ | — |
| `kv` | 速度ゲイン (減衰) | — | ✅ (ダンパー) | ✅ (P 制御) |
| `ctrlrange` | 入力範囲 | トルク範囲 | 角度範囲 | 速度範囲 |
| `forcerange` | 出力トルク制限 | (gear×ctrl を制限) | (kp, kv の出力を制限) | (kv の出力を制限) |
| `damping` | 受動的粘性減衰 | ✅ (追加減衰) | — | — |
| `armature` | ロータ慣性 | ✅ (数値安定性) | — | — |
| `dyntype` | 活性化ダイナミクス | none が普通 | none | none |

### 4.5 実験結果

| 実験 | 入力 | 最終 θ | 最終 ω | 特徴 |
|---|---|---|---|---|
| A: Motor | τ=3 N·m (t≥0.5s) | +5290° (回転) | +69.7 rad/s | 重力超のトルクで加速し続ける |
| B: Position | θ*=45° | +50.5° | ≈0 | 重力偏差 +5.5° (kp 有限) |
| C: Velocity | ω*=2 rad/s | +281° | +2.05 rad/s | ほぼ追従、重力変動で微リップル |

### 4.6 W6 への設計指針: BLDC トルク入力

```xml
<actuator>
  <motor name="bldc"
         joint="rotor"
         gear="1.0"
         ctrllimited="true"
         ctrlrange="-50 50"
         forcelimited="true"
         forcerange="-50 50"
         dyntype="none"/>
</actuator>
```

- `<motor>` タイプ一択: Python 側で FOC + PI → Te を計算し、`data.ctrl[0] = Te` で入力
- `dyntype="none"`: BLDC は電子的応答が速いので遅延不要
- `armature`: MuJoCo 側でロータ慣性を追加するか、`<inertial>` でボディに持たせるか選択
- `gear="1.0"`: Te [N·m] をそのまま入力する設計

**成果物**: `figures/mujoco_tutorial/04_actuator.png` (3 タイプ × 3 行の比較プロット)

---

## Section 5: Sensors

**ゴール**: `<sensor>` 要素でセンサを定義し、`data.sensordata` から値を読む方法を覚える。Gymnasium Env の observation 設計に直結する。

### 5.1 モデル (`05_sensor.xml`)

Section 4 と同じ水平アーム + motor に 5 種類のセンサを追加:

| センサ名 | タイプ | 対象 | dim | 出力 |
|---|---|---|---|---|
| `s_angle` | `jointpos` | hinge joint | 1 | 関節角度 [rad] |
| `s_velocity` | `jointvel` | hinge joint | 1 | 関節角速度 [rad/s] |
| `s_torque` | `actuatorfrc` | motor actuator | 1 | 出力トルク [N·m] |
| `s_tip_pos` | `framepos` | tip body | 3 | 先端の世界座標 [m] |
| `s_tip_vel` | `framelinvel` | tip body | 3 | 先端の世界線速度 [m/s] |

### 5.2 `data.sensordata` の構造

```python
model.nsensor      # → 5 (センサ数)
model.nsensordata  # → 9 (全センサの出力次元の合計: 1+1+1+3+3)
data.sensordata    # shape=(9,) のフラットな 1D 配列
```

各センサのオフセット:
```python
for i in range(model.nsensor):
    adr = model.sensor_adr[i]   # sensordata 内の開始インデックス
    dim = model.sensor_dim[i]   # 出力の次元数
    # → sensordata[adr : adr+dim]
```

本モデルのレイアウト:
```
sensordata[0]   = angle     (1D)
sensordata[1]   = velocity  (1D)
sensordata[2]   = torque    (1D)
sensordata[3:6] = tip_pos   (3D: x, y, z)
sensordata[6:9] = tip_vel   (3D: vx, vy, vz)
```

### 5.3 名前指定でアクセス

```python
# 名前 → data のスライスを直接取得 (推奨)
data.sensor("s_angle").data       # → array([0.5236])
data.sensor("s_tip_pos").data     # → array([0.26, 0.0, 0.35])
```

> `data.sensor(name).data` は `sensordata[adr:adr+dim]` のビュー。コピーではない。

### 5.4 `sensordata` と `qpos/qvel` の 1 ステップラグ

`mj_step` の内部処理順:
```
mj_step1: fwdPosition → sensordata 更新 (この時点の qpos を反映)
          fwdVelocity → fwdActuation → fwdAcceleration
mj_step2: 積分 → qpos, qvel 更新
```

つまり `mj_step` 後に読むと:
- `data.qpos` = 積分 **後** の値
- `data.sensordata` = 積分 **前** に計算された値

**→ 1 ステップ分 (dt) のラグがある。** 厳密に同期させたい場合は `mj_step` 後に `mj_forward` を呼ぶ。

Gymnasium Env では通常 `mj_step` → `sensordata` 読み出しの順で問題ない (dt が小さければラグは無視可能)。

### 5.5 主要なセンサタイプ一覧

| タイプ | 対象 | dim | 意味 |
|---|---|---|---|
| `jointpos` | joint | 1 (hinge/slide) | 関節位置 |
| `jointvel` | joint | 1 | 関節速度 |
| `actuatorfrc` | actuator | 1 | アクチュエータ出力力 |
| `framepos` | body/geom/site | 3 | 世界座標位置 |
| `framequat` | body/geom/site | 4 | 世界座標姿勢 (クォータニオン) |
| `framelinvel` | body/geom/site | 3 | 世界座標線速度 |
| `frameangvel` | body/geom/site | 3 | 世界座標角速度 |
| `accelerometer` | site | 3 | 加速度 (サイトフレーム, 重力含む) |
| `gyro` | site | 3 | 角速度 (サイトフレーム) |
| `touch` | site | 1 | 接触力の法線成分合計 |

### 5.6 W7 Env の observation 設計への応用

BLDC モータ Env で必要な observation:

```xml
<sensor>
  <jointpos name="rotor_angle" joint="rotor"/>     <!-- θ_m -->
  <jointvel name="rotor_speed" joint="rotor"/>     <!-- ω_m -->
  <actuatorfrc name="applied_torque" actuator="bldc"/> <!-- Te (確認用) -->
</sensor>
```

Python 側:
```python
obs = np.array([
    data.sensor("rotor_angle").data[0],   # θ_m [rad]
    data.sensor("rotor_speed").data[0],   # ω_m [rad/s]
])
# もしくは sin/cos 表現:
# obs = [sin(θ), cos(θ), ω]
```

**成果物**: `figures/mujoco_tutorial/05_sensor.png` (5 段プロット: angle / velocity / torque / tip_pos / tip_vel)

---

## Section 6: Interactive viewer

**ゴール**: `mujoco.viewer.launch_passive` で Python ループからリアルタイム描画を行う最小パターンを押さえる。

### 6.1 passive モードの基本

```python
import mujoco
import mujoco.viewer
import time

with mujoco.viewer.launch_passive(model, data) as viewer:
    while viewer.is_running():
        data.ctrl[0] = compute_torque(data.time)
        mujoco.mj_step(model, data)
        viewer.sync()  # ← 描画フレームを更新

        # 実時間に合わせる
        time.sleep(max(0, model.opt.timestep - elapsed))
```

- `launch_passive` はウィンドウを開き、Python 側がメインループを握る
- `viewer.sync()` を呼ぶたびに画面が更新される
- `viewer.is_running()` はウィンドウが閉じられると False

### 6.2 カメラ操作

| 操作 | 効果 |
|---|---|
| 左ドラッグ | カメラ回転 |
| 右ドラッグ | カメラ平行移動 |
| スクロール | ズーム |
| ダブルクリック | クリック位置にフォーカス |

### 6.3 キーボードショートカット

| キー | 効果 |
|---|---|
| Space | 一時停止 / 再開 |
| Backspace | リセット (初期状態に戻す) |
| Esc | ウィンドウを閉じて終了 |
| Tab | 表示パネル切替 |
| F1 | ヘルプ表示 |

### 6.4 注意事項

- **macOS**: OpenGL の制約でビューワが開かない場合がある。その場合はスキップして OK。
- **ヘッドレス環境** (SSH, Docker): ビューワは使えない。Section 1-5 のオフスクリーンレンダリングで十分。
- **デバッグ用途**: 接触力の可視化 (`MjvOption` のフラグ) はビューワ側でも ON/OFF できる。
- W7 の `BLDCMotorEnv` では `gymnasium` の `render_mode="human"` でビューワを起動する設計になる。

**成果物**: スクリプト `06_viewer.py` (GUI 実行のみ、図の出力なし)

---

## 進捗

- [x] Section 1: Loading & rendering
- [x] Section 2: Basic simulation
- [x] Section 3: Contacts
- [x] Section 4: Actuators
- [x] Section 5: Sensors
- [x] Section 6: Interactive viewer (`mujoco.viewer`)

---

## 今後のリンク先 (W6 以降)

- `Project/bldc_motor.xml` … 本チュートリアルで覚えた MJCF 構文を使ってロータ + ロードを記述
- `Project/envs/bldc_motor_env.py` … Gymnasium Env (`reset`, `step`, `observation_space`, `action_space`)
- `Project/experiments/` の PI 制御 Python 実装を、まずは MuJoCo Env 側のベースラインとして移植
