"""
06_viewer.py
Section 6: Interactive viewer — mujoco.viewer の passive モード

学ぶこと:
  1) mujoco.viewer.launch_passive(model, data) でビューワを起動
  2) Python ループ内から data.ctrl を書き換えながらリアルタイム描画
  3) viewer.sync() でレンダリング更新
  4) ビューワのカメラ操作 (マウス) とキーボードショートカット

モデル: models/05_sensor.xml を再利用 (水平アーム + motor + sensors)
操作: サイン波トルクを 10 秒間適用しながらビューワで可視化

注意:
  - macOS では OpenGL の制約で、ビューワのウィンドウが表示されない環境もある。
  - その場合はスキップして OK (ヘッドレスレンダリングは Section 1-5 で習得済み)。
  - Ctrl+C でいつでも中断可能。
"""

from pathlib import Path
import time

import mujoco
import mujoco.viewer
import numpy as np

_HERE = Path(__file__).resolve().parent
_MODEL = _HERE / "models" / "05_sensor.xml"


def main():
    model = mujoco.MjModel.from_xml_path(str(_MODEL))
    data = mujoco.MjData(model)

    # 初期条件
    data.qpos[0] = np.pi / 6  # 30°
    data.qvel[0] = 0.0
    mujoco.mj_forward(model, data)

    print("=" * 60)
    print("Section 6: Interactive viewer (passive mode)")
    print("=" * 60)
    print("  Opening viewer window...")
    print("  Sinusoidal torque: A=4 N·m, f=0.5 Hz, duration=10 s")
    print("  Mouse: left=rotate, right=translate, scroll=zoom")
    print("  Keys: Space=pause, Backspace=reset, Esc=quit")
    print()

    T_sim = 10.0
    A_torque = 4.0
    freq = 0.5

    try:
        with mujoco.viewer.launch_passive(model, data) as viewer:
            start = time.time()

            while viewer.is_running() and data.time < T_sim:
                step_start = time.time()

                # 制御入力
                t = data.time
                data.ctrl[0] = A_torque * np.sin(2 * np.pi * freq * t)

                # 物理ステップ
                mujoco.mj_step(model, data)

                # ビューワ同期
                viewer.sync()

                # 実時間に合わせる (遅延挿入)
                elapsed = time.time() - step_start
                dt = model.opt.timestep
                sleep_time = dt - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

            wall_time = time.time() - start
            print(f"  Done. sim_time={data.time:.1f}s, wall_time={wall_time:.1f}s")
            print(f"  final θ = {np.degrees(data.qpos[0]):+.1f}°")
            print(f"  final ω = {data.qvel[0]:+.3f} rad/s")

    except Exception as e:
        print(f"\n  ⚠ Viewer failed: {e}")
        print("  → macOS OpenGL の制約の可能性あり。ヘッドレスモードは正常動作。")
        print("  → Section 1-5 のオフスクリーンレンダリングで十分。")


if __name__ == "__main__":
    main()
