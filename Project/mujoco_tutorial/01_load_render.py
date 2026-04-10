"""
01_load_render.py
Section 1: Loading & rendering

MuJoCo Python API の 3 大オブジェクト (MjModel / MjData / Renderer) を触る。

ステップ:
  1) XML ファイルをロードして `MjModel` を得る
  2) `MjData` を作る (状態ベクトル・派生量の入れ物)
  3) `mj_forward` で運動学だけ更新 (積分はしない)
  4) `Renderer` でオフスクリーン描画 → PNG に保存
  5) `mj_step` で 1 ステップだけ積分し、ボールが重力で動いたことを確認

W5 学習ノート: ../mujoco_tutorial/README.md
"""

from pathlib import Path

import mujoco
import numpy as np
import matplotlib.pyplot as plt

_HERE = Path(__file__).resolve().parent
_MODEL = _HERE / "models" / "01_ball.xml"
_FIG_DIR = _HERE.parent / "figures" / "mujoco_tutorial"
_FIG_DIR.mkdir(parents=True, exist_ok=True)


def main():
    # -------------------------------------------------------------
    # 1) ロード
    # -------------------------------------------------------------
    model = mujoco.MjModel.from_xml_path(str(_MODEL))
    data = mujoco.MjData(model)

    print("=" * 60)
    print("Section 1: Loading & rendering")
    print("=" * 60)
    print(f"  model: {_MODEL.name}")
    print(f"  timestep  = {model.opt.timestep*1e3:.1f} ms")
    print(f"  gravity   = {model.opt.gravity}")
    print(f"  nq (一般化座標数) = {model.nq}")
    print(f"  nv (一般化速度数) = {model.nv}")
    print(f"  nbody     = {model.nbody}  (world + ball)")
    print(f"  ngeom     = {model.ngeom}  (floor + ball)")

    # 自由関節は nq=7 (position 3 + quaternion 4), nv=6 (linvel 3 + angvel 3)
    print(f"  qpos (init) = {data.qpos}")
    print(f"  qvel (init) = {data.qvel}")

    # -------------------------------------------------------------
    # 2) 運動学だけ更新 (積分しない)
    # -------------------------------------------------------------
    mujoco.mj_forward(model, data)
    print(f"\n  [after mj_forward]")
    print(f"  ball com_pos = {data.body('ball').xpos}")

    # -------------------------------------------------------------
    # 3) オフスクリーン描画
    # -------------------------------------------------------------
    with mujoco.Renderer(model, height=480, width=640) as renderer:
        # 初期フレーム
        renderer.update_scene(data, camera=-1)  # -1 = フリーカメラ
        pixels_init = renderer.render()

        # -----------------------------------------------------------
        # 4) 1 ステップ積分して再描画 (重力で少し落ちる)
        # -----------------------------------------------------------
        # dt=2ms を 500 回 = 1 秒進める
        for _ in range(500):
            mujoco.mj_step(model, data)

        print(f"\n  [after 500 steps (1 s)]")
        print(f"  ball com_pos = {data.body('ball').xpos}  (should be on floor, z≈0.1)")
        print(f"  ball lin_vel = {data.qvel[0:3]}")

        renderer.update_scene(data, camera=-1)
        pixels_final = renderer.render()

    # -------------------------------------------------------------
    # 5) 2 枚を並べて保存
    # -------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].imshow(pixels_init)
    axes[0].set_title("t = 0.0 s (ball at z=0.5)")
    axes[0].axis("off")
    axes[1].imshow(pixels_final)
    axes[1].set_title("t = 1.0 s (after 500 mj_step)")
    axes[1].axis("off")
    fig.suptitle("Section 1: Load & Render (ball on plane)")
    plt.tight_layout()

    out = _FIG_DIR / "01_load_render.png"
    plt.savefig(out, dpi=120)
    print(f"\n  Saved: {out}")


if __name__ == "__main__":
    main()
