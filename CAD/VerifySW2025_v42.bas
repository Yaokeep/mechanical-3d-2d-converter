Option Explicit

' ============================================================
' v42: 完整阶梯轴模型 — 验证全部 5 项特征 API
'
' 模型结构:
'   0. Revolve2     → 阶梯轴基体 (3段变径)
'   1. Extrusion2   → 中间段加粗凸台
'   2. RevolveCut   → 退刀槽 (轴颈)
'   3. Cut3         → 键槽 (在中间段顶部)
'   4. Extrusion3   → 轴肩凸台 (SW2025新版API)
'   5. Chamfer      → 轴端倒角
'   6. Fillet       → 轴肩圆角
'
' 全部草图 Front Plane Z=0, Top Plane Y=0
' ============================================================

Dim swApp As Object
Dim swModel As Object
Dim swFeatMgr As Object
Dim swSketchMgr As Object
Dim swFeat As Object
Dim bn As Long

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks
    swApp.Visible = True
    Debug.Print "SW: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        MsgBox "请先 Ctrl+N 新建零件！", vbCritical
        Exit Sub
    End If
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager

    ' ============================================================
    ' 0. 阶梯轴基体 — Revolve2 一步成型
    '    3 段变径: R=10, R=15, R=10 (mm)
    '    总长: 120mm = 0.12m
    ' ============================================================
    Debug.Print vbCrLf & "=== 0.阶梯轴基体 (Revolve2) ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    ' 半截面轮廓 (Z=0):
    ' 段1: R=0.01, X=0~0.04
    swSketchMgr.CreateLine 0, 0, 0, 0, 0.01, 0
    swSketchMgr.CreateLine 0, 0.01, 0, 0.04, 0.01, 0
    ' 台阶: R=0.01→0.015
    swSketchMgr.CreateLine 0.04, 0.01, 0, 0.04, 0.015, 0
    ' 段2: R=0.015, X=0.04~0.08
    swSketchMgr.CreateLine 0.04, 0.015, 0, 0.08, 0.015, 0
    ' 台阶: R=0.015→0.01
    swSketchMgr.CreateLine 0.08, 0.015, 0, 0.08, 0.01, 0
    ' 段3: R=0.01, X=0.08~0.12
    swSketchMgr.CreateLine 0.08, 0.01, 0, 0.12, 0.01, 0
    ' 回到底边
    swSketchMgr.CreateLine 0.12, 0.01, 0, 0.12, 0, 0
    swSketchMgr.CreateLine 0.12, 0, 0, 0, 0, 0
    ' 旋转中心线
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.12, 0, 0

    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  Revolve2(20)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If swFeat Is Nothing Then MsgBox "阶梯轴基体失败!", vbCritical: Exit Sub
    swFeat.Name = "Shaft-Base"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 1. Extrusion2 凸台 — 在段1右端加粗
    '    Front Plane, 矩形 X=0.03~0.04, Y=0.01~0.013
    '    拉伸 Z 双向 0.005m
    ' ============================================================
    Debug.Print vbCrLf & "=== 1.Extrusion2 凸台 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.03, 0.01, 0, 0.04, 0.01, 0
    swSketchMgr.CreateLine 0.04, 0.01, 0, 0.04, 0.013, 0
    swSketchMgr.CreateLine 0.04, 0.013, 0, 0.03, 0.013, 0
    swSketchMgr.CreateLine 0.03, 0.013, 0, 0.03, 0.01, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.005, 0.005, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False)
    Debug.Print "  Ext2(23)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss-Ring"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 2. RevolveCut 退刀槽 — 在段2右端切槽
    '    Front Plane, 矩形 X=0.065~0.075, Y=0.012~0.015
    '    带中心线, 切除深度 0.003m
    ' ============================================================
    Debug.Print vbCrLf & "=== 2.RevolveCut 退刀槽 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.065, 0.012, 0, 0.075, 0.012, 0
    swSketchMgr.CreateLine 0.075, 0.012, 0, 0.075, 0.015, 0
    swSketchMgr.CreateLine 0.075, 0.015, 0, 0.065, 0.015, 0
    swSketchMgr.CreateLine 0.065, 0.015, 0, 0.065, 0.012, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.12, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, True, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  RevolveCut(20)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Groove"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 3. Cut3 键槽 — 在段2顶部切键槽
    '    Front Plane, 矩形 X=0.045~0.065, Y=0.013~0.015
    '    切除 Z 双向 0.003m (键槽宽度 6mm, 深度 2mm)
    ' ============================================================
    Debug.Print vbCrLf & "=== 3.Cut3 键槽 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.045, 0.013, 0, 0.065, 0.013, 0
    swSketchMgr.CreateLine 0.065, 0.013, 0, 0.065, 0.015, 0
    swSketchMgr.CreateLine 0.065, 0.015, 0, 0.045, 0.015, 0
    swSketchMgr.CreateLine 0.045, 0.015, 0, 0.045, 0.013, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.003, False, 0, 0.003, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, 0#, False, False, False)
    Debug.Print "  Cut3(26)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Keyway"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 4. Extrusion3 轴肩 — 在段3左端加凸台 (SW2025新版)
    '    Front Plane, 矩形 X=0.08~0.09, Y=0.01~0.012
    ' ============================================================
    Debug.Print vbCrLf & "=== 4.Extrusion3 轴肩 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.08, 0.01, 0, 0.09, 0.01, 0
    swSketchMgr.CreateLine 0.09, 0.01, 0, 0.09, 0.012, 0
    swSketchMgr.CreateLine 0.09, 0.012, 0, 0.08, 0.012, 0
    swSketchMgr.CreateLine 0.08, 0.012, 0, 0.08, 0.01, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.004, 0.004, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False)
    Debug.Print "  Ext3(22)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Shoulder"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 5. Chamfer 倒角 — 轴端棱边 (段3右端)
    ' ============================================================
    Debug.Print vbCrLf & "=== 5.Chamfer 轴端 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    ' 选择段3右端面外圆边: 在 X=0.12, Y≈0.01, Z≈0 处选边
    swModel.Extension.SelectByID2 "", "EDGE", 0.12, 0.01, 0, False, 0, Nothing, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
    Debug.Print "  Chamfer(8)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Chamfer-End"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 6. Fillet 圆角 — 轴肩根部 (段2与段3交界)
    ' ============================================================
    Debug.Print vbCrLf & "=== 6.Fillet 轴肩 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    ' 选择段2圆柱面: 在 X=0.06, Y=0.015, Z=0 处选面
    swModel.Extension.SelectByID2 "", "FACE", 0.06, 0.015, 0, False, 0, Nothing, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet3(195, 0.001, 0, 0, False, 0, False, False)
    Debug.Print "  Fillet(8)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Fillet-Shoulder"

    ' ============================================================
    ' 报告
    ' ============================================================
    On Error GoTo 0
    Debug.Print vbCrLf & "========== 报告 =========="
    Debug.Print "特征总数: " & swModel.GetFeatureCount
    Dim f As Object
    Dim j As Long
    For j = 1 To swModel.GetFeatureCount
        Set f = swModel.FeatureByPositionReverse(j)
        If Not f Is Nothing Then
            Debug.Print "  [" & j & "] " & f.Name
        End If
    Next
    swModel.ViewZoomtofit2
    MsgBox "v42 完成！阶梯轴模型已创建。" & vbCrLf & _
           "包含: 基体 + 凸台 + 退刀槽 + 键槽 + 轴肩 + 倒角 + 圆角", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! Err #" & Err.Number & ": " & Err.Description
    On Error Resume Next
    swModel.InsertSketch2 True
    Resume Next
End Sub
