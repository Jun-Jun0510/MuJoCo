# ゴールA 週単位学習ロードマップ
## MuJoCoでBLDCモータ制御シミュレーション → RLでPIDを超える（3ヶ月）

**ゴール**: 「MuJoCoでBLDCモータの制御シミュレーションを作り、RLでPID制御を超える」をGitHubに公開

**前提**: PLECS経験あり、Python/MuJoCo/RL未経験

---

## 全体構成

```
Month 1 [W1-W4]:  Python基礎 + MuJoCoモータモデリング
Month 2 [W5-W8]:  MuJoCo統合 + FOC制御 + RL理論基礎
Month 3 [W9-W12]: RL実装 + PID vs RL比較 + GitHub公開
```

**最終成果物**: `bldc-mujoco-rl` GitHubリポジトリ（英語README付き）

---

## Month 1: Python基礎 + モータモデリング

### Week 1: 開発環境構築 + Python入門

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1 | 環境構築 | Python 3.11+, VS Code, venv仮想環境, Git初期化 |
| Day 2 | Python基礎 | 変数, リスト, forループ, 関数, クラスの基本 |
| Day 3 | NumPy入門 | 配列生成, 演算, ブロードキャスト（PLECSのベクトル計算との対比） |
| Day 4-5 | Matplotlib | 波形プロット, サブプロット（PLECSのスコープの代替） |
| Day 6-7 | Git + GitHub | add/commit/push, GitHubリポジトリ作成, 初コミット |

**成果物**: GitHubリポジトリ初コミット
**チェックポイント**: NumPyで正弦波3相電圧を生成しMatplotlibでプロットできる

---

### Week 2: Clarke/Park変換 + モータ方程式のPython実装

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1-2 | Clarke/Park変換 | PLECSの座標変換ブロックをPython関数に移植。3相→αβ→dq変換の可視化 |
| Day 3-4 | BLDCモータ電気モデル | `BLDCMotorElectricalModel`クラス作成。d-q軸方程式の前進オイラー離散化 |
| Day 5 | オープンループテスト | 一定電圧印加→電流応答をシミュレーション。PLECSの結果と比較 |
| Day 6-7 | SciPy入門 | `solve_ivp`でモータモデルの精度向上（RK4ソルバ） |

**成果物**: `motor_model.py` + Clarke/Park変換のプロット + PLECSとの比較グラフ
**チェックポイント**: Pythonのd-q軸電流応答がPLECSと5%以内で一致

**PLECS→Python 思考の転換**:
```
PLECSでブロックを配置して線を繋ぐ → Pythonでクラスを定義して関数を呼ぶ
PLECSのパラメータダイアログ       → __init__の引数/dict
PLECSのRun ボタン               → for step in range(n_steps):
PLECSのスコープ                 → data_log[step] = value → plt.plot()
```

---

### Week 3: PIDコントローラ実装

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1-2 | PIDControllerクラス | PLECSのPIDブロックをPythonクラスに移植。後退差分離散化 |
| Day 3 | アンチワインドアップ | clamping方式 + back-calculation方式の実装 |
| Day 4-5 | 速度制御テスト | 電気モデル + PID速度制御。ステップ応答の確認 |
| Day 6-7 | チューニング | PIDゲインの手動調整。整定時間・オーバーシュートの計測 |

**成果物**: `pid_controller.py` + ステップ応答プロット
**チェックポイント**: PID速度制御でステップ応答がきれいに収束する

---

### Week 4: MuJoCo入門 + Level 1モデル

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1 | MuJoCoインストール | `pip install mujoco` + 動作確認 |
| Day 2-3 | 公式チュートリアル | Google Colab Tutorial完走。MJCF XMLの基本構造理解 |
| Day 4-5 | Level 1モデル作成 | 単軸回転体 + トルク入力のMJCF XML作成。Pythonから制御入力テスト |
| Day 6-7 | PID制御統合 | Level 1モデルにW3のPIDコントローラを接続。速度制御動作確認 |

**成果物**: `level1_simple_rotor.xml` + MuJoCo PID制御デモ
**チェックポイント**: MuJoCoのモータモデルをPythonのPIDで速度制御できる

**核心概念**: MuJoCoでは「電流ループの内側」は抽象化。PLECSでの電流PI→トルク変換がMuJoCoでは`ctrl[0] = torque`になる。

---

## Month 2: MuJoCo統合 + FOC + RL理論基礎

### Week 5: Level 2モデル（モータ特性追加）

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1-2 | Level 2 MJCF作成 | `general`アクチュエータでトルク定数・バックEMF・電気時定数を近似 |
| Day 3-4 | パラメータマッピング | PLECSのモータパラメータ → MuJoCoのarmature/damping/frictionloss/gainprm |
| Day 5-6 | Level 2 PID制御 | Level 2モデルでの速度制御。Level 1との応答比較 |
| Day 7 | Level 3概観 | ギア付きモデルの構造を理解（余裕があれば作成） |

**成果物**: `level2_motor_characteristics.xml` + Level 1 vs Level 2比較プロット

**MuJoCoパラメータの物理的意味**:
```
gainprm = トルク定数 Kt
biasprm (速度項) = バックEMF効果（高速でトルク低下）
dynprm (filter) = 電気的時定数 L/R
armature = ロータ慣性モーメント J
damping = 粘性摩擦 B
frictionloss = クーロン摩擦
```

---

### Week 6: Python電気モデル + MuJoCo統合

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1-2 | 統合アーキテクチャ | Python側（電気+制御）とMuJoCo側（機械）の責任分担を実装 |
| Day 3-4 | サブステップ実装 | MuJoCo 0.5ms内に電気モデルを10μsで50回計算するループ |
| Day 5-6 | FOCコントローラ | `FOCController`クラス（電流PI×2 + 速度PID + 非干渉制御） |
| Day 7 | 統合テスト | FOC + MuJoCo統合シミュレーション。PLECSとの最終比較 |

**成果物**: FOC統合シミュレーション + PLECSとの比較検証

**タイムステップ階層**:
```
電気モデル:  10μs（Python内ループ）
MuJoCo内部: 0.5ms (timestep=0.0005)
RL制御周期:  2ms  (n_substeps=4) ← Month 3で使用
```

---

### Week 7: RL理論基礎 + PyTorch入門

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1-2 | RL理論 | MDP、方策、価値関数、Actor-Critticの概念理解 |
| Day 3-4 | PyTorch基礎 | テンソル操作、自動微分、nn.Module、学習ループ（公式60min Blitz） |
| Day 5-6 | Gymnasium入門 | CartPole/PendulumをPPOで動かす（SB3使用） |
| Day 7 | 概念対応の確認 | 制御工学⇔RLの対応関係を自分の言葉で整理 |

**核心的な対応関係**:
```
制御工学: J = ∫(x'Qx + u'Ru) dt   ← LQR評価関数（最小化）
    RL:   r = -(x'Qx + u'Ru)       ← 報酬関数（最大化）
→ 報酬 = -（評価関数）。LQRを知っていればRLの報酬設計の直感が効く
```

**推奨リソース**:
- PyTorch 60 Minute Blitz（公式）
- Spinning Up in Deep RL（OpenAI、無料Web）
- David Silver RL講義 Ch.1-4（YouTube）

---

### Week 8: Gymnasium環境構築 + PIDベースライン

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1-3 | BLDCMotorEnv作成 | MuJoCoモータモデルをGymnasiumカスタム環境として実装 |
| Day 4 | 環境テスト | ランダム行動で1000ステップ動作確認。NaN/Inf チェック |
| Day 5-6 | PIDベースライン | PIDコントローラで環境を制御。報酬が適切に出ることを確認 |
| Day 7 | Optunaチューニング | PIDの最適パラメータを自動探索（1000回試行） |

**成果物**: `bldc_motor_env.py` + 最適PIDパラメータ

**Gymnasium環境の設計**:
```
観測空間 (7次元): [angle, velocity, current_proxy, target_angle,
                   target_velocity, angle_error, velocity_error]
行動空間 (1次元): [-1, 1] → トルク指令にスケーリング
報酬関数: -10·e² - 0.1·ω² - 0.01·u² - 0.05·(Δu)² + 0.1
エピソード: 2000ステップ（= 4秒）
```

---

## Month 3: RL実装 + 比較評価 + GitHub公開

### Week 9: PPOで基礎体験 + 環境デバッグ

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1-2 | PPOで学習開始 | SB3のPPOでBLDCMotorEnvを学習（100Kステップ） |
| Day 3-4 | 環境デバッグ | 学習結果を見て環境のバグを修正。報酬スケール調整 |
| Day 5-6 | 報酬関数の改善 | 各報酬成分をTensorBoardでモニタリング。バランス調整 |
| Day 7 | PPO結果の確認 | PPO vs PIDの初回比較。改善点の洗い出し |

**成果物**: デバッグ済み環境 + PPO初回学習曲線

**「学習しない」ときのデバッグ順序**:
```
1. ランダム行動でstep()が正常に動くか？ → 環境のバグ
2. PIDで良い報酬が出るか？ → 報酬関数の問題
3. 観測値にNaN/Infは？ → MuJoCoモデルの問題
4. PPOのlrを10倍/0.1倍に → ハイパラの問題
5. Pendulum-v1で動くか？ → コード全体の問題
```

---

### Week 10: SAC本格学習 + ハイパーパラメータ探索

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1-2 | SACに切替 | SB3のSACで学習（500Kステップ）。PPOとの性能差を確認 |
| Day 3-4 | Optuna探索 | SAC ハイパーパラメータの自動探索（50試行） |
| Day 5-7 | 複数シナリオ評価 | シナリオA(ステップ), B(軌道追従), C(外乱+追従)でPID vs SAC比較 |

**成果物**: 学習済みSACモデル + シナリオ別比較データ

**SAC推奨ハイパーパラメータ（初期値）**:
```python
SAC('MlpPolicy', env,
    learning_rate=3e-4, buffer_size=100000,
    batch_size=256, tau=0.005, gamma=0.99,
    learning_starts=1000)
```

---

### Week 11: 比較評価 + 可視化

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1-2 | 定量比較 | 5軸評価（RMSE, 整定時間, オーバーシュート, 外乱抑制, エネルギー効率） |
| Day 3-4 | 可視化 | 時系列比較プロット、5軸レーダーチャート、メトリクステーブル |
| Day 5-6 | 外乱ロバスト性 | ドメインランダマイゼーション（パラメータ変動下での比較） |
| Day 7 | GIFアニメーション | MuJoCoのレンダリングでPID vs RLのデモ動画作成 |

**成果物**: 比較結果一式（グラフ、テーブル、動画）

**「PIDを超えた」の基準（5軸）**:
| 指標 | 測定方法 |
|:---|:---|
| RMSE | 目標値と実値のRMSE |
| 整定時間 | ±2%収束時間 |
| オーバーシュート | 最大偏差の割合 |
| 外乱抑制 | 外乱後の回復時間 |
| エネルギー効率 | ∫u²dt（制御入力コスト） |

---

### Week 12: コード整理 + README + GitHub公開

| 日 | 内容 | 詳細 |
|:---|:---|:---|
| Day 1-2 | コード整理 | ディレクトリ構造の統一、不要コード削除、型ヒント追加 |
| Day 3-4 | README作成 | 英語README（動機、手法、結果サマリー、使い方） |
| Day 5 | requirements.txt | 再現可能な環境定義。seed固定の確認 |
| Day 6-7 | **GitHub公開** | 最終コミット + 公開。Qiita/Zennで日本語記事ドラフト |

**最終リポジトリ構成**:
```
bldc-mujoco-rl/
├── README.md                    # 概要、結果、使い方（英語）
├── requirements.txt
├── models/                      # MJCF XMLモデル群（Level 1-4）
├── envs/                        # Gymnasium環境（BLDCMotorEnv）
├── controllers/                 # PIDベースライン + Optunaチューニング
├── training/                    # PPO/SAC学習スクリプト
├── evaluation/                  # PID vs RL比較評価
├── notebooks/                   # 段階的解説Jupyter Notebook
├── results/                     # 学習済みモデル、グラフ、動画
└── docs/                        # モータモデリングガイド
```

---

## 必達ライン vs 理想ライン

| | 必達（最小成果物） | 理想（到達できれば） |
|:---|:---|:---|
| モデル | Level 2（モータ特性付き） | Level 4（2軸アーム） |
| 制御 | PID速度制御 | FOC + 位置/速度制御 |
| RL | SAC速度追従 | SAC + 外乱ロバスト性 |
| 比較 | ステップ応答のPID vs RL | 3シナリオ + レーダーチャート |
| 可視化 | Matplotlibグラフ | GIFアニメーション + 動画 |

---

## 関連ドキュメント（詳細はこちら）

| ファイル | 内容 |
|:---|:---|
| `mujoco_motor_modeling_strategy.md` | MuJoCoモデリング詳細（MJCF XML例、パラメータ対応表） |
| `plecs_to_python_migration_guide.md` | PLECS→Python移行ガイド（コード例、概念対応表） |
| `rl_strategy_design.md` | RL戦略詳細（報酬設計、Gymnasium環境テンプレート、デバッグガイド） |

---

*3名の専門家（MuJoCoシミュレーション、モータ制御/PLECS移行、強化学習）の分析を統合して作成*
*作成日: 2026年3月20日*
