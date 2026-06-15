# SolidWorks 2025 自动化模块
#
# 提供 SW COM 驱动封装和参数化建模功能。
# 注意: 需要 pywin32 和已安装的 SolidWorks 2025。
#
# 使用示例::
#
#     from src.core.sw_automation import SolidWorksDriver, ShaftBuilder
#
#     driver = SolidWorksDriver(visible=True)
#     if driver.connect() and driver.new_part():
#         builder = ShaftBuilder(driver)
#         builder.build()
#         driver.save_as("shaft.sldprt")
#     driver.disconnect()

from .sw_constants import (
    swDocPART,
    swDocASSEMBLY,
    swDocDRAWING,
    swEndCondBlind,
    swEndCondThroughAll,
    swStartSketchPlane,
    swRefPlaneOffset,
    swChamferDistanceDistance,
    swFeatureFilletSimple,
    SW_FILLET_OPTIONS,
    swSelectType_EDGES,
    swSelectType_FACES,
    swSaveAsCurrentVersion,
    swSaveAsOptions_Silent,
    swMMGS,
    SW_USER_PREF_UNIT_SYSTEM,
)
from .sw_driver import (
    SolidWorksDriver,
    SwError,
    SwConnectionError,
    SwFeatureError,
    check_sw_connection,
)
from .sw_shaft_builder import (
    ShaftBuilder,
    DEFAULT_SECTIONS,
    DEFAULT_KEYWAYS,
    DEFAULT_CHAMFER_MM,
    DEFAULT_FILLET_R_MM,
)

__all__ = [
    # Driver
    "SolidWorksDriver",
    "SwError",
    "SwConnectionError",
    "SwFeatureError",
    "check_sw_connection",
    # Builder
    "ShaftBuilder",
    "DEFAULT_SECTIONS",
    "DEFAULT_KEYWAYS",
    "DEFAULT_CHAMFER_MM",
    "DEFAULT_FILLET_R_MM",
    # Constants
    "swDocPART",
    "swDocASSEMBLY",
    "swDocDRAWING",
    "swEndCondBlind",
    "swEndCondThroughAll",
    "swStartSketchPlane",
    "swRefPlaneOffset",
    "swChamferDistanceDistance",
    "swFeatureFilletSimple",
    "SW_FILLET_OPTIONS",
    "swSelectType_EDGES",
    "swSelectType_FACES",
    "swSaveAsCurrentVersion",
    "swSaveAsOptions_Silent",
    "swMMGS",
    "SW_USER_PREF_UNIT_SYSTEM",
]
