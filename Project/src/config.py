from dataclasses import dataclass
import numpy as np

@dataclass
class MotorConfig:
    # --- 物理定数 (From Spec Sheet) ---
    Rs: float = 0.802          # [Ω] 固定子抵抗
    Ld: float = 11.7e-3        # [H] d軸インダクタンス
    Lq: float = 23.7e-3        # [H] q軸インダクタンス
    Lz: float = 1.47e-3        # [H] 零相インダクタンス
    Ke: float = 0.149          # [Wb] 磁束鎖交数 (Linkage flux)
    J:  float = 0.007          # [kgm^2] 慣性モーメント (中型サーボ相当, 旧値 0.0007 は τm<τe 逆転していたため 10倍に修正)
    Pn: int   = 2              # [-] 極対数 (Number of pole pairs)
    
    # --- 電源・インバータ制限 ---
    # Vdc: 日本標準 AC200V 3相整流後のバス電圧 (~283V) を想定し 300V に設定。
    # 旧値 96V では定格電流時 vd が ~280rpm で飽和する問題があった。
    # Yaskawa SGM7G-20 相当 (~18 Nm ピーク, 2-3kW, 2000rpm) の中型産業サーボを想定。
    Vdc: float = 300.0         # [V] DC電源電圧
    I_max: float = 40.0        # [A] 電流制限値
    
    # --- スイッチング特性 ---
    F_carrier: float = 10000.0 # [Hz] キャリア周波数
    DeadTime:  float = 2.0e-6  # [s] デッドタイム
    
    # --- 制御帯域 (Design Targets) ---
    W_acr: float = 4000.0      # [rad/s] 電流制御(ACR)帯域
    W_asr: float = 50.0        # [rad/s] 速度制御(ASR)帯域

# インスタンス生成
motor_params = MotorConfig()