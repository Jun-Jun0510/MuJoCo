"""
03_contact.py
Section 3: Contacts — 接触検出・接触力の読み出し・摩擦の影響

学ぶこと:
  1) data.ncon で接触数を取得
  2) data.contact[i] の各フィールド (pos, frame, dist, geom1, geom2)
  3) mj_contactForce(model, data, i, result) で 6D 接触力を取得
  4) 着地時の衝撃力 (法線力スパイク) の観測
  5) friction パラメータが滑り減速に与える影響 (a ≈ μg)

モデル: models/03_contact.xml
  - 3 つのブロック (低/中/高 摩擦) を高さ 0.15 m から落下 + 初速 vx=3 m/s
  - ブロック同士は接触しない (contype/conaffinity ビットマスクで分離)

期待される物理:
  - block_lo (μ=0.05): a≈0.49 m/s² → 停止 t≈6.1s → 4s 時点で vx≈1.0 m/s
  - block_mid (μ=0.3):  a≈2.94 m/s² → 停止 t≈1.0s → x≈1.5 m で停止
  - block_hi  (μ=0.8):  a≈7.85 m/s² → 停止 t≈0.4s → x≈0.6 m で停止
"""

from pathlib import Path

import mujoco
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

_HERE = Path(__file__).resolve().parent
_MODEL = _HERE / "models" / "03_contact.xml"
_FIG_DIR = _HERE.parent / "figures" / "mujoco_tutorial"
_FIG_DIR.mkdir(parents=True, exist_ok=True)

BLOCKS = [
    ("block_lo",  "low  (μ=0.05)", "tab:blue"),
    ("block_mid", "mid  (μ=0.3)",  "tab:green"),
    ("block_hi",  "high (μ=0.8)",  "tab:red"),
]


def main():
    model = mujoco.MjModel.from_xml_path(str(_MODEL))
    data = mujoco.MjData(model)

    # 初速: 全ブロックに vx = +3.0 m/s
    V0 = 3.0
    for name, _, _ in BLOCKS:
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name)
        jnt_adr = model.body_jntadr[body_id]
        dof_adr = model.jnt_dofadr[jnt_adr]
        data.qvel[dof_adr] = V0  # vx

    mujoco.mj_forward(model, data)

    # geom ID の取得
    block_geom_ids = {name: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
                      for name, _, _ in BLOCKS}

    print("=" * 60)
    print("Section 3: Contacts (3 blocks, different friction)")
    print("=" * 60)
    print(f"  timestep = {model.opt.timestep*1e3:.1f} ms")
    print(f"  initial vx = {V0:.1f} m/s, drop height = 0.15 m")
    for name, label, _ in BLOCKS:
        gid = block_geom_ids[name]
        fr = model.geom_friction[gid]
        cd = model.geom_condim[gid]
        print(f"  {label}: friction = [{fr[0]:.3f}, {fr[1]:.4f}, {fr[2]:.4f}]"
              f"  condim={cd}")

    # -----------------------------------------------------------------
    # シミュレーション + ログ + フレーム収集
    # -----------------------------------------------------------------
    T_sim = 4.0
    dt = model.opt.timestep
    N = int(T_sim / dt)

    fps = 30
    render_every = int(round(1.0 / (fps * dt)))
    frames: list[np.ndarray] = []

    t_log = np.zeros(N)
    x_log = {name: np.zeros(N) for name, _, _ in BLOCKS}
    vx_log = {name: np.zeros(N) for name, _, _ in BLOCKS}
    fn_log = {name: np.zeros(N) for name, _, _ in BLOCKS}  # 法線接触力
    ft_log = {name: np.zeros(N) for name, _, _ in BLOCKS}  # 接線接触力 (摩擦力)
    ncon_log = np.zeros(N, dtype=int)

    forcetorque = np.zeros(6)

    with mujoco.Renderer(model, height=360, width=640) as renderer:
        for k in range(N):
            mujoco.mj_step(model, data)

            t_log[k] = data.time
            ncon_log[k] = data.ncon

            for name, _, _ in BLOCKS:
                body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name)
                x_log[name][k] = data.body(name).xpos[0]
                jnt_adr = model.body_jntadr[body_id]
                dof_adr = model.jnt_dofadr[jnt_adr]
                vx_log[name][k] = data.qvel[dof_adr]

            # 接触力の集計
            for i in range(data.ncon):
                c = data.contact[i]
                mujoco.mj_contactForce(model, data, i, forcetorque)
                # forcetorque[0]: 法線力, [1],[2]: 接線力 (摩擦力)
                fn = abs(forcetorque[0])
                ft = np.sqrt(forcetorque[1]**2 + forcetorque[2]**2)

                for name, _, _ in BLOCKS:
                    gid = block_geom_ids[name]
                    if c.geom2 == gid or c.geom1 == gid:
                        fn_log[name][k] += fn
                        ft_log[name][k] += ft
                        break

            # フレーム収集
            if k % render_every == 0:
                scene_option = mujoco.MjvOption()
                scene_option.flags[mujoco.mjtVisFlag.mjVIS_CONTACTPOINT] = True
                scene_option.flags[mujoco.mjtVisFlag.mjVIS_CONTACTFORCE] = True
                renderer.update_scene(data, camera=-1, scene_option=scene_option)
                frames.append(renderer.render().copy())

    print(f"\n  steps  = {N}")
    print(f"  frames = {len(frames)}  ({fps} fps)")

    # -----------------------------------------------------------------
    # 接触情報サンプル表示
    # -----------------------------------------------------------------
    # 着地直後のスナップショットを探す (t ≈ 0.18s 付近)
    landing_idx = np.searchsorted(t_log, 0.20)
    print(f"\n  --- Contact snapshot at t={t_log[landing_idx]:.3f}s (just after landing) ---")

    # 最終時刻のスナップショットは直接表示
    print(f"\n  --- Contact snapshot at t={data.time:.3f}s (final) ---")
    print(f"  ncon = {data.ncon}")
    for i in range(data.ncon):
        c = data.contact[i]
        g1_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, c.geom1) or "?"
        g2_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, c.geom2) or "?"
        mujoco.mj_contactForce(model, data, i, forcetorque)
        print(f"    [{i}] {g1_name} ↔ {g2_name}  "
              f"pos=({c.pos[0]:+.3f},{c.pos[1]:+.3f},{c.pos[2]:+.3f})  "
              f"dist={c.dist:.6f}  "
              f"F_n={forcetorque[0]:+.3f} N  "
              f"F_t=({forcetorque[1]:+.3f},{forcetorque[2]:+.3f}) N")

    # -----------------------------------------------------------------
    # GIF 保存
    # -----------------------------------------------------------------
    gif_path = _FIG_DIR / "03_contact.gif"
    pil_frames = [Image.fromarray(f) for f in frames]
    pil_frames[0].save(
        str(gif_path),
        save_all=True,
        append_images=pil_frames[1:],
        duration=int(1000.0 / fps),
        loop=0,
        optimize=False,
    )
    print(f"\n  GIF → {gif_path}  ({len(pil_frames)} frames)")

    # -----------------------------------------------------------------
    # プロット: 5 段
    # -----------------------------------------------------------------
    fig, axes = plt.subplots(5, 1, figsize=(10, 12), sharex=True)
    mg = 0.5 * 9.81  # 重力 = mg

    # (1) X 位置
    for name, label, color in BLOCKS:
        axes[0].plot(t_log, x_log[name], color=color, label=label)
    axes[0].set_ylabel("x position [m]")
    axes[0].set_title(f"Section 3: Contact — sliding blocks (v₀={V0} m/s, drop=0.15 m)")
    axes[0].legend(loc="best", fontsize=9)
    axes[0].grid(True, alpha=0.3)

    # (2) X 速度
    for name, label, color in BLOCKS:
        axes[1].plot(t_log, vx_log[name], color=color, label=label)
    axes[1].axhline(0, color="gray", linewidth=0.5)
    axes[1].set_ylabel("vx [m/s]")
    axes[1].legend(loc="best", fontsize=9)
    axes[1].grid(True, alpha=0.3)

    # (3) 法線接触力 (着地スパイク + 定常 mg)
    for name, label, color in BLOCKS:
        axes[2].plot(t_log, fn_log[name], color=color, label=label, alpha=0.8)
    axes[2].axhline(mg, color="gray", linestyle="--", linewidth=0.8,
                     label=f"mg = {mg:.2f} N")
    axes[2].set_ylabel("Normal force [N]")
    axes[2].set_ylim(-0.5, min(fn_log[BLOCKS[0][0]].max() * 1.2, 80))
    axes[2].legend(loc="best", fontsize=9)
    axes[2].grid(True, alpha=0.3)

    # (4) 接線接触力 (摩擦力)
    for name, label, color in BLOCKS:
        axes[3].plot(t_log, ft_log[name], color=color, label=label, alpha=0.8)
    axes[3].set_ylabel("Friction force [N]")
    axes[3].legend(loc="best", fontsize=9)
    axes[3].grid(True, alpha=0.3)

    # (5) 接触数
    axes[4].plot(t_log, ncon_log, color="black", linewidth=0.8)
    axes[4].set_ylabel("ncon (# contacts)")
    axes[4].set_xlabel("Time [s]")
    axes[4].grid(True, alpha=0.3)

    plt.tight_layout()
    out = _FIG_DIR / "03_contact_force.png"
    plt.savefig(out, dpi=120)
    print(f"  plot → {out}")

    # 最終状態サマリー + 理論値比較
    print(f"\n  --- Final state vs theory (a = μg on flat) ---")
    for name, label, _ in BLOCKS:
        gid = block_geom_ids[name]
        mu = model.geom_friction[gid, 0]
        # 理論: a = μg, t_stop = V0/(μg), x_stop = V0²/(2μg)
        a_th = mu * 9.81
        t_stop = V0 / a_th
        x_stop = V0**2 / (2 * a_th)
        # 実際の停止 x (vx ≈ 0 になった時点)
        idx_stop = np.argmax(vx_log[name] <= 0.01) if np.any(vx_log[name] <= 0.01) else -1
        x_actual = x_log[name][idx_stop] if idx_stop > 0 else x_log[name][-1]
        v_final = vx_log[name][-1]
        print(f"    {label}:  μg={a_th:.2f} m/s²  "
              f"t_stop(th)={t_stop:.2f}s  x_stop(th)={x_stop:.2f}m  "
              f"x_actual={x_actual:.2f}m  vx_final={v_final:+.3f} m/s")


if __name__ == "__main__":
    main()
