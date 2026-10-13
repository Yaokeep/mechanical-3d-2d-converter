# -*- coding: utf-8 -*-
"""YZYX 齿箱上盖定量验收总入口（无 3D 基准靶子三件套，验证制度化）。

无基准件没法量"体积差"——用三件套定量（ASSESSMENT_20261006.md §D2）：
  1. yz_probe_mat.run_probe  27 点材料分类（IN/OUT 期望，v13~v15a 四轮修复定案）
  2. yz_hlr.run_hlr          五视图 HLR 可见轮廓 → _yz_hlr.json
  3. yz_match.run_match      图纸对比缺/多评分（THRESH=2.0mm）

判红线（**基线 = v15a 当前最佳，不是零缺陷**）：
  * 材料探针任一点 !! ⇒ 红（27 点全是用户四轮读法修复的直接判据，破坏即倒退）
  * TL/BL/TR 缺 > 0 ⇒ 红（v15a 基线缺全 0；图纸有的轮廓模型必须有）
  * 多 > 基线+10 ⇒ 红（基线 TL 49 / BL 50 / TR 38——多出 10 以上视为改坏；
    少算不进判红：消影/剖切制备差异会让"多"波动，"缺"才是硬信号）
  判红项打印 [RED]；全过退出码 0，否则 1。

用法: PYTHONIOENCODING=utf-8 $PY yz_accept.py [stepfile] [thresh_mm] [--frame auto|part|fw]

坐标系：三件套常量全在 v15a 零件系；新框架 src/rebuild 发射的模型在图纸
坐标系（平移差 x−2650.80 / y−3462.94 / z−1541.25）——'auto'（默认）按 bbox
自动识别并平移进零件系（yz_frame.py），'--frame' 可显式指定。

两段式：本脚本用 $PY 跑（材料探针 + HLR 都要 OCC）；图纸对比评分部分
ezdxf/numpy 在**默认 python** 子进程里跑——numpy linalg 与 OCC 同进程会
0xc06d007f 崩溃（与 _dump_sections($PY) → _draw_sections(python) 同例）。
⚠️ 子进程必须 **shell=True**（经 cmd 中转）：从 cad-occt python 直接
CreateProcess 的子 python 继承其 DLL 搜索路径，numpy 加载 OpenBLAS 同样
0xc06d007f（实测最小 env 也崩）；cmd 作中间层隔断继承即正常。
"""
import json
import subprocess
import sys

BASELINE_MORE = {"TL": 49, "BL": 50, "TR": 38}   # v15a 2026-10-06 实测
MORE_SLACK = 10


def main(argv: list[str]) -> int:
    from yz_frame import pop_frame_argv

    argv = argv[1:]
    frame = pop_frame_argv(argv)
    src = argv[0] if argv else "CAD/temp_output/_yz_3d.step"
    thresh = float(argv[1]) if len(argv) > 1 else 2.0

    bad = 0
    print("=" * 80)
    print("YZYX 无基准靶子定量验收（材料探针 + 五视图投影评分）")
    print("=" * 80)

    # 1. 材料探针（OCC，本进程）
    from yz_probe_mat import run_probe
    print("[1/3] 材料探针 27 点")
    fails, total = run_probe(src, frame)
    if fails:
        print(f"  [RED] {fails} 点与期望不符")
        bad += 1

    # 2. HLR 投影（OCC，本进程）
    from yz_hlr import run_hlr
    print("[2/3] 五视图 HLR")
    run_hlr(src, "CAD/temp_output/_yz_hlr.json", frame=frame)

    # 3. 图纸对比评分（默认 python 子进程，两段式 + shell=True——见 docstring）
    print("[3/3] 图纸对比评分")
    score_json = "CAD/temp_output/_yz_score.json"
    subprocess.run(f'python yz_match.py {thresh} --json "{score_json}"',
                   check=True, shell=True)
    scores = json.load(open(score_json, encoding="utf-8"))

    for name in ("TL", "BL", "TR"):
        nm, ne = scores.get(name, [0, 0])
        base = BASELINE_MORE.get(name, 0)
        miss_bad = nm > 0
        more_bad = ne > base + MORE_SLACK
        mark = "[RED]" if (miss_bad or more_bad) else "[OK ]"
        print(f"  {mark} {name}  缺 {nm}（判红 >0）  多 {ne}（基线 {base}，"
              f"判红 >{base + MORE_SLACK}）")
        if miss_bad or more_bad:
            bad += 1

    print("-" * 80)
    if bad:
        print(f"[FAIL] {bad} 项未过——YZYX 模型比 v15a 基线更差，查建模改动")
        return 1
    print("[完成] YZYX 三件套全过：27 点材料分布与五视图投影均不低于 v15a 基线")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
