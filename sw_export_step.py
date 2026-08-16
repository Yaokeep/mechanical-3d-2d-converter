#!/usr/bin/env python
"""SolidWorks 2025 Python COM 驱动 — SLDPRT → STEP 导出。

将真实 SolidWorks 模型转换为 STEP 文件，供 PythonOCC 管线（HLR 投影、
CSG 重建对比）使用。SaveAs3 根据扩展名推断格式（.step → STEP AP203）。

用法:
    python sw_export_step.py 三维/xxx.SLDPRT
    python sw_export_step.py 三维/xxx.SLDPRT 输出目录

环境要求:
    pip install pywin32
    SolidWorks 2025 已安装
"""

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

import pythoncom
import win32com.client

# SW 枚举常量（晚期绑定经验值，见 sw_constants.py）
swDocPART = 1
swOpenDocOptions_Silent = 1
swSaveAsCurrentVersion = 0


def export_sldprt_to_step(sldprt_path: Path, out_dir: Path) -> Path:
    """打开 SLDPRT 并另存为时间戳 STEP 文件，返回 STEP 路径。"""
    sldprt_path = sldprt_path.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = sldprt_path.stem
    step_path = out_dir / f"{stem}_{ts}.step"

    sw_app = win32com.client.Dispatch("SldWorks.Application")
    sw_app.Visible = False

    try:
        # OpenDoc6(filename, type, options, configuration, errors, warnings)
        # 晚期绑定下 errors/warnings 必须用 VT_BYREF 变体
        errs = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_I4, 0
        )
        warns = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_I4, 0
        )
        doc = sw_app.OpenDoc6(
            str(sldprt_path), swDocPART, swOpenDocOptions_Silent, "", errs, warns
        )
        if doc is None:
            raise RuntimeError(
                f"OpenDoc6 失败: errors={errs.value} warnings={warns.value}"
            )

        model = sw_app.ActiveDoc
        # 格式由 .step 扩展名推断，版本 0 = 当前版本
        result = model.SaveAs3(str(step_path), swSaveAsCurrentVersion, 0)
        if result not in (0, None):
            raise RuntimeError(f"SaveAs3 返回 {result}")

        sw_app.CloseDoc(str(sldprt_path))
        print(f"OK: {sldprt_path.name} -> {step_path}")
        return step_path
    finally:
        sw_app.ExitApp()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SLDPRT → STEP 导出（SW COM）"
    )
    parser.add_argument("sldprt", help="输入 SLDPRT 文件路径")
    parser.add_argument(
        "out_dir", nargs="?", default="CAD/temp_output",
        help="输出目录（默认 CAD/temp_output）",
    )
    args = parser.parse_args()

    try:
        export_sldprt_to_step(Path(args.sldprt), Path(args.out_dir))
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
