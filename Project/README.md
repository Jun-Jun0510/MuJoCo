# Project/ ディレクトリ構成

BLDC モータ制御 × MuJoCo × 強化学習プロジェクトの実装コード置き場。

## ディレクトリの役割

```
Project/
├── src/          # ← コアライブラリ (他から import されるモジュール)
├── experiments/  # ← 実験・可視化スクリプト (python で直接実行するもの)
├── figures/      # ← 実験スクリプトが出力した PNG 画像
├── c_src/        # ← マイコン移植用 C 実装
└── README.md     # このファイル
```

| フォルダ | 役割 | 中身 |
|---|---|---|
| **`src/`** | Python のコアライブラリ。モータモデル・制御器・設定など、他のスクリプトから `import` して使う再利用可能な部品を置く。単体実行 (`python src/motor_model.py`) で簡易確認もできる。 | `config.py`, `transforms.py`, `motor_model.py`, `discrete_model.py`, `pi_controller.py` |
| **`experiments/`** | 検証・可視化スクリプト置き場。`src/` のライブラリを使って数値実験を行い、結果を `figures/` に保存する。1 ファイル = 1 実験の独立スクリプト。 | `plot_motor_response.py`, `plot_current_loop.py`, `plot_speed_loop.py`, `plot_prefilter_compare.py`, `plot_nt_curve.py`, `plot_mtpa_compare.py`, `three_phase_wave.py` |
| **`figures/`** | 実験スクリプトの出力画像。Git で追跡するかは運用次第 (大きくなる場合は `.gitignore` に追加)。 | `*.png` |
| **`c_src/`** | マイコン (STM32H7 想定) 移植用 C コード。Python 実装と数値一致することを確認するテストベンチ用。 | `transforms.c` |

## 実行方法

すべて Project ルートから `.venv` の python で実行する。

```bash
cd /Users/ohatajun/Desktop/MuJoCo
./.venv/bin/python Project/experiments/plot_mtpa_compare.py
```

各実験スクリプトは冒頭で `src/` を `sys.path` に追加しているため、ディレクトリ構成を意識せずに `from pi_controller import ...` のようなフラットな import が使える。

## `src/` モジュール一覧

| ファイル | 内容 |
|---|---|
| `config.py` | `MotorConfig` dataclass (Rs, Ld, Lq, Ke, J, Pn, Vdc, I_max, W_acr, W_asr など全パラメータ) と `motor_params` シングルトン。 |
| `transforms.py` | Clarke / Park 変換 + 逆変換 (振幅不変形, 2/3 係数)。スカラー/ベクトル両対応。 |
| `motor_model.py` | `BLDCMotor` — 連続時間 d-q 軸モデル (RK4)。真値参照用。 |
| `discrete_model.py` | `EulerDiscreteMotor`, `TustinDiscreteMotor` — 離散化モデル。マイコン実装相当。 |
| `pi_controller.py` | `PIController` (汎用), `CurrentPIController` (ACR), `SpeedPIController` (ASR), `SpeedPIControllerTe` (Te* 出力版), `MTPATable` (MTPA LUT), および `_simulate_*_loop` 系のシミュレーションユーティリティ。 |

## `experiments/` 実験一覧

| スクリプト | 検証内容 | 出力 (`figures/`) |
|---|---|---|
| `plot_motor_response.py` | 開ループ vd=0, vq=30V ステップ応答 (RK4 真値) | `motor_open_loop_response.png` |
| `plot_current_loop.py` | W4-1: ACR (電流ループ) 閉ループ応答 | `current_loop_response.png` |
| `plot_speed_loop.py` | W4-3: ASR+ACR カスケード、速度ステップ & 外乱応答 | `speed_loop_step.png`, `speed_loop_disturbance.png` |
| `plot_prefilter_compare.py` | ASR プリフィルタ有無の比較 (零点相殺) | `prefilter_compare.png` |
| `plot_nt_curve.py` | N-T 包絡線 (id=0 vs MTPA+FW, scipy SLSQP) | `nt_curve.png` |
| `plot_mtpa_compare.py` | MTPA LUT vs id=0 クローズドループ比較 (無負荷 / 重負荷) | `mtpa_compare_A.png`, `mtpa_compare_B.png` |
| `three_phase_wave.py` | Day1 学習用 3 相電圧波形プロット | (画面表示のみ) |
