import numpy as np
import matplotlib.pyplot as plt

# 1. 時間軸の設定（0秒から0.02秒までを1000分割）
t = np.linspace(0, 0.02, 1000)
f = 100  # 周波数 50Hz

# 2. 3相交流電圧の計算（abc相）
v_a = np.sin(2 * np.pi * f * t)
v_b = np.sin(2 * np.pi * f * t - 2/3 * np.pi)
v_c = np.sin(2 * np.pi * f * t - 4/3 * np.pi)

# 3. グラフの描画（オシロスコープの役割）
plt.figure(figsize=(10, 5))
plt.plot(t, v_a, label='Phase A (Red)', color='red')
plt.plot(t, v_b, label='Phase B (Blue)', color='blue')
plt.plot(t, v_c, label='Phase C (Green)', color='green')

plt.title("Day 1: 3-Phase Voltage Plot Success!")
plt.xlabel("Time [s]")
plt.ylabel("Voltage [V]")
plt.grid(True)
plt.legend()
plt.show()