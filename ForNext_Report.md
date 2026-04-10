# ForNext_Report — BLDC × MuJoCo × RL 27 ヶ月学習プロジェクト

> **このファイルの用途**
> 次回セッションで別の Claude (または自分自身) が作業を再開する際の **ブリーフィング資料**。
> プロジェクト背景 → 現在までの成果 → 次に着手すべきタスクを、前提知識ゼロでも追えるようにまとめる。
> 作業を進めたら、このファイルも最新状態に更新すること。

---

## 0. プロジェクト概要

- **目的**: BLDC (PMSM) モータの制御を、古典制御 (PI) → 強化学習 (SAC など) へと段階的に発展させる。MuJoCo 上に機械系モデルを置き、Gymnasium 互換の Env にしてから RL を回す。
- **期間**: 27 ヶ月ロードマップ (2026/03 〜 2028 年頃)。
- **学習スタイル**: 週次でテーマを決め、毎週「Python スクリプト + 図 + ノート (.md)」を成果物として残す。コードは実行可能な状態で git に置く。
- **作業者の好み**:
  - 日本語で議論
  - コードは冗長な error handling や過剰な抽象化を避ける (必要最小限)
  - 図を見ながら `.md` で勉強するスタイル
  - ファイル分割は、動かせる粒度を優先 (1 スクリプト = 1 テーマ)
- **リポジトリ**: `Jun-Jun0510/MuJoCo` (GitHub) の `main` ブランチで作業。
- **開発環境**:
  - macOS (Darwin 23.6.0, Apple Silicon)
  - Python 3.12 venv: `/Users/ohatajun/Desktop/MuJoCo/.venv`
  - 実行時は **必ず** `./.venv/bin/python ...` で venv の Python を使う
  - 主要ライブラリ: `mujoco==3.6.0`, `mediapy==1.2.6`, `gymnasium==1.2.3`, `stable_baselines3==2.8.0`, `torch==2.11.0`, `jax==0.9.2`, `matplotlib==3.10.8`, `numpy==2.4.3`
  - ffmpeg は **未インストール** → 動画は PIL 経由の GIF で保存する方針
  - フルリストは `setup/requirements.txt`

---

## 1. リポジトリ構成 (現時点)

```
MuJoCo/
├── ForNext_Report.md              ← 本ファイル (引き継ぎ資料)
├── Reference/                     ← 書籍 PDF・資料類 (読み物)
├── setup/
│   └── requirements.txt           ← pip freeze。venv 再構築はここから
└── Project/                       ← コードと成果物の本体
    ├── README.md                  ← フォルダ構造の説明書
    ├── src/                       ← 再利用ライブラリ (import 用)
    │   ├── config.py              ← モータパラメータ・ゲイン定数
    │   ├── transforms.py          ← Clarke / Park 変換 (Python 版)
    │   ├── motor_model.py         ← PMSM 連続時間モデル (dq 軸)
    │   ├── discrete_model.py      ← 離散化 (Tustin / 前進オイラー)
    │   └── pi_controller.py       ← PI コントローラ (アンチワインドアップ付き)
    ├── experiments/               ← 実行スクリプト (図を生成する)
    │   ├── three_phase_wave.py        → 三相正弦波の可視化
    │   ├── plot_motor_response.py     → 開ループステップ応答
    │   ├── plot_current_loop.py       → 電流ループ (ACR) 応答
    │   ├── plot_speed_loop.py         → 速度ループ (ASR) 応答
    │   ├── plot_prefilter_compare.py  → プレフィルタ有無比較
    │   ├── plot_nt_curve.py           → N-T カーブ
    │   └── plot_mtpa_compare.py       → MTPA LUT vs id=0 比較
    ├── figures/                   ← 生成された PNG / GIF
    │   └── mujoco_tutorial/       ← W5 チュートリアル出力
    ├── c_src/
    │   └── transforms.c           ← Clarke/Park の C 実装 (参考実装)
    └── mujoco_tutorial/           ← W5 MuJoCo 公式チュートリアル写経 (全6セクション完了)
        ├── README.md              ← 学習ノート (Section 1-6 完了)
        ├── models/
        │   ├── 01_ball.xml
        │   ├── 02_pendulum.xml
        │   ├── 03_contact.xml
        │   ├── 04_actuator.xml
        │   └── 05_sensor.xml
        ├── 01_load_render.py
        ├── 02_basic_sim.py
        ├── 03_contact.py
        ├── 04_actuator.py
        ├── 05_sensor.py
        └── 06_viewer.py
```

### 1.1 import / 実行パターン

- `experiments/` 配下のスクリプトはプロジェクトルートから実行:
  ```bash
  ./.venv/bin/python Project/experiments/plot_mtpa_compare.py
  ```
- `src/` のライブラリを使うため、各 experiment 冒頭で **sys.path を操作** している:
  ```python
  import sys
  from pathlib import Path
  _PROJECT = Path(__file__).resolve().parent.parent
  sys.path.insert(0, str(_PROJECT / "src"))
  _FIG_DIR = _PROJECT / "figures"
  ```
- 正式なパッケージ化 (`setup.py` / `pyproject.toml`) は **していない**。flat import で十分という判断。

---

## 2. 週次ロードマップと進捗

| 週 | 日付 | テーマ | 状態 | 主な成果物 |
|---|---|---|---|---|
| W1 | 3/15 | Clarke/Park 変換 (Python + C) | ✅ 完了 | `src/transforms.py`, `c_src/transforms.c`, `three_phase_wave.py` |
| W2 | 3/22 | PMSM 連続時間モデル + 開ループ応答 | ✅ 完了 | `src/motor_model.py`, `plot_motor_response.py` |
| W3 | 3/29 | 電流ループ ACR 設計 + 離散化 | ✅ 完了 | `src/pi_controller.py`, `src/discrete_model.py`, `plot_current_loop.py` |
| W4 | 4/05 | 速度ループ ASR + プレフィルタ + N-T + MTPA LUT | ✅ 完了 | `plot_speed_loop.py`, `plot_prefilter_compare.py`, `plot_nt_curve.py`, `plot_mtpa_compare.py` |
| **W5** | **4/12** | **MuJoCo 公式 Python チュートリアル写経** | **✅ 完了 (6/6)** | `mujoco_tutorial/` (6 スクリプト + 5 モデル + README) |
| W6 | 5/12 | `bldc_motor.xml` (MJCF 記述) | ⏳ 未着手 | — |
| W7 | 5/19 | `BLDCMotorEnv` (Gymnasium 準拠) | ⏳ 未着手 | — |
| W8 | 5/26 | PI 制御ベースラインを Env に移植 | ⏳ 未着手 | — |
| 以降 | — | SAC / PPO → カリキュラム学習 → Sim2Real 想定 | ⏳ | — |

---

## 3. これまでの主要な決定事項

### 3.1 設計方針
1. **Python 実装を主軸**。C 実装は参考として残すが、制御ループは Python で回す。
2. **ライブラリ化より flat な構成**。`src/` をパスに追加する方式で十分、パッケージ化はしない。
3. **実行スクリプト = 図を 1 枚生成するもの**。テーマごとに分割する (`plot_xxx.py` 命名)。
4. **動画は PIL/GIF** を使う。ffmpeg を入れたくないため `mediapy.write_video()` は使わない。
5. **図の出力先は `Project/figures/`** に集約。スクリプトから `_FIG_DIR` で参照。

### 3.2 モータ制御関連
6. **MTPA は LUT 方式**。解析解ではなくテーブル参照 (実機で使う想定)。
7. **id=0 制御との比較を Scenario A/B の 2 ケース**で検証済み:
   - Scenario A: 低トルク動作点 → MTPA と id=0 でほぼ差なし (+4.85 %)
   - Scenario B: 高トルク動作点 → id=0 は飽和して指令に届かない、MTPA は 50.0 rad/s 到達
8. **Scenario B で初期に速度が負に振れる理由**: t=0 で負荷トルク TL=20 N·m が加わるが電磁トルク Te=0 のため、`dω/dt = -TL/J = -2857 rad/s²` の初期加速度が発生 (= 物理的に正しい)。
9. **速度ループ設計**: プレフィルタ有無で指令追従とオーバーシュートが大きく変わることを確認済み。プレフィルタ有が標準。

### 3.3 W5 MuJoCo チュートリアル関連
10. **チュートリアルは DeepMind 公式 Colab を模倣**。Section 1-6 を一通り触る。
11. **学習ノートは `Project/mujoco_tutorial/README.md` に日本語で書く**。ユーザは図を見ながら .md を読んで学習する。
12. **Section 2 で自己接触の罠を発見**:
    - 初期実装でエネルギーが 4 秒で −99 % 消失した。
    - 原因: pivot 用の可視化 box と arm capsule / tip sphere が幾何的に重なり、接触ソルバが毎ステップ摩擦を発生させていた。
    - **対処**: 振子系の全 geom に `contype="0" conaffinity="0"` を付けて自己接触を無効化。結果 −2.81 % まで改善。
    - **教訓 (W6 以降にも効く)**: 保存系や接触不要な部品は、真っ先に接触マスクを疑う。BLDC ロータにも同じ処理が必要になるはず。
13. **積分器の使い分け**:
    - `Euler` (default): 剛体接触メインのロボット
    - `implicitfast`: 硬い系 (数値減衰あり)
    - `RK4`: 保存系・エネルギー精度重視 ← **Section 2 はこれを採用**
14. **Section 3: contype/conaffinity ビットマスク** で「誰と誰が接触するか」を設計。
    - `(geom1.contype & geom2.conaffinity) || 逆` で判定。
    - 摩擦はスライド/スピン/ロールの 3 成分。混合規則は要素ごとの max (priority 等しい場合)。
    - condim=3 が標準 (法線+接線2方向)。
    - 箱の滑り実験: μ=0.05/0.3/0.8 で停止距離が大きく変化、理論 `x = v₀²/(2μg)` とほぼ一致。
15. **Section 4: BLDC には `<motor>` タイプ一択**。
    - `gear="1.0"`, `dyntype="none"` で Te [N·m] を直接入力する設計。
    - `<position>` は kp 有限で重力偏差あり、`<velocity>` は速度追従だが外乱に弱い。
16. **Section 5: sensordata は 1 ステップラグ**。
    - `mj_step` 後の `data.sensordata` は積分前の値。厳密に同期したければ `mj_forward` 追加。
    - Env の observation には `jointpos` + `jointvel` を使う。

---

## 4. 今いる場所 (最新の作業ポイント)

### 4.1 W5: MuJoCo Python チュートリアル 写経 — ✅ 全セクション完了

- [x] **Section 1: Loading & rendering** — `01_load_render.py` / `01_ball.xml`
- [x] **Section 2: Basic simulation** — `02_basic_sim.py` / `02_pendulum.xml`
- [x] **Section 3: Contacts** — `03_contact.py` / `03_contact.xml`
  - 3 ブロック (μ=0.05/0.3/0.8) の滑り摩擦比較、`mj_contactForce` で法線力・摩擦力を読み出し
  - contype/conaffinity ビットマスク、condim、solref/solimp を学習
- [x] **Section 4: Actuators** — `04_actuator.py` / `04_actuator.xml`
  - motor / position / velocity の 3 タイプを同一モデルで比較
  - BLDC には `<motor>` タイプが最適と結論
- [x] **Section 5: Sensors** — `05_sensor.py` / `05_sensor.xml`
  - jointpos, jointvel, actuatorfrc, framepos, framelinvel を定義・読み出し
  - sensordata の 1 ステップラグを確認
- [x] **Section 6: Interactive viewer** — `06_viewer.py`
  - `launch_passive` の最小パターンを実装 (GUI 実行のみ)

学習ノート: `Project/mujoco_tutorial/README.md` (全 Section 分)

### 4.2 git 状態
- 最新コミット: `eb01208 JO260410_プロジェクト構成整理・MTPA LUT 検証追加` (push 済み)
- **W5 の全成果物 (Section 1-6) が未コミット**。まとめてコミット推奨。

---

## 5. 次セッションでの着手タスク

### 5.1 最優先: W5 成果物の git コミット
- W5 の全ファイル (Section 1-6) をまとめてコミット・プッシュする
- コミットメッセージ例: `JO260410_W5 MuJoCo チュートリアル全6セクション完了`

### 5.2 W6: `bldc_motor.xml` の作成
1. **W6: `Project/bldc_motor.xml` を書く**
   - ロータ (hinge joint, 慣性 J = 1e-3 〜 1e-2 kg·m²)
   - 負荷ディスク (任意の慣性)
   - アクチュエータ: `motor` タイプ (外部トルク入力)
   - センサ: jointpos (角度), jointvel (角速度)
   - **重要**: 接触不要な部品には全部 `contype=0 conaffinity=0` を付ける (W5 Section 2 の教訓)
2. **W7: `Project/envs/bldc_motor_env.py`**
   - `gymnasium.Env` を継承
   - `reset()`: qpos/qvel 初期化 + mj_forward
   - `step(action)`: トルクを `data.ctrl[0]` に書き込み mj_step、observation / reward / terminated を返す
   - observation: `[θ, ω]` または `[sin θ, cos θ, ω]`
   - action: 連続値のトルク (N·m), `action_space = Box(-τ_max, +τ_max)`
   - reward: 速度追従 `-(ω - ω_ref)²` 等の素朴なものから始める
3. **W8: PI ベースライン** — `src/pi_controller.py` を呼び出して Env 上で速度制御、`plot_speed_loop.py` と同じ応答が再現できるか確認。

---

## 6. 既知の注意点 / 落とし穴

1. **venv の Python を必ず使う** — システムの `python3` を叩くと mujoco が無いと言われる。`./.venv/bin/python` 推奨。
2. **ffmpeg は入っていない** — `mediapy.write_video()` を呼ぶと `RuntimeError: Program 'ffmpeg' is not found`。PIL で GIF 保存に統一。
3. **保存系 (エネルギー保存したい振子など) では** `integrator="RK4"` **+** `contype=0 conaffinity=0` **の合わせ技が必須**。片方だけだとエネルギーが崩れる。
4. **MuJoCo の `nq` と `nv` は次元が違うことがある** (freejoint: 7/6, ball joint: 4/3)。qpos/qvel を直接 numpy で操作する時に注意。
5. **`mj_forward` は運動学更新のみで time は進まない**。初期条件を書いた直後、描画する前に 1 回呼ぶ。
6. **git コミットメッセージの規約**: `JOYYMMDD_内容` のフォーマット (例: `JO260410_プロジェクト構成整理・MTPA LUT 検証追加`)。
7. **destructive な git 操作 (force push, reset --hard など) は勝手にやらない**。確認してから実行。
8. **球体は転がり無滑りになるため、摩擦の差が出にくい**。摩擦の比較には箱 (box) を使うのが正解。
9. **`data.sensordata` は `mj_step` 後でも積分前の値** (1 ステップラグ)。Env の observation に使う分には問題ないが、厳密比較時は `mj_forward` を追加呼び出し。
10. **MuJoCo の摩擦混合規則**: 2 geom の priority が等しい場合、各成分の max をとる。床の friction を小さくしておけばブロック側の値が支配する。

---

## 7. このファイルの更新ルール

作業を進めたときは、少なくとも以下を更新:
- セクション 2 の進捗表のチェックマーク
- セクション 4「今いる場所」の完了リストとコミット情報
- セクション 5「次に着手」の内容を前に進める
- 新しい決定事項があればセクション 3 に追記
- 新しい落とし穴を見つけたらセクション 6 に追記

**更新しないもの**: 過去の週 (W1-W4) の決定事項は、誤りが見つからない限り書き換えない。
