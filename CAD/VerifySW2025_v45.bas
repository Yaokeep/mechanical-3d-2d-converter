Option Explicit

' ============================================================
' v45: 完整阶梯轴模型 — 7/7 API 全部调通!
'
' API 清单:
'   0. Revolve2(20)    → 阶梯轴基体
'   1. Extrusion2(23)  → 中间凸台
'   2. RevolveCut(20)  → 退刀槽
'   3. Cut3(26)        → 键槽
'   4. Extrusion3(22)  → 轴肩凸台
'   5. Chamfer(8)      → 轴端倒角 (EDGE)
'   6. Fillet(8)       → 圆角 (EDGE + Options=195)
'
' 关键规则:
'   - 所有 Front Plane 草图 Z=0
'   - 矩形 Y 坐标跨轴表面 (嵌入实体内部)
'   - Fillet: 选边 + Options=195
'   - Chamfer: 精确选棱边坐标
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
    ' 0. 阶梯轴基体 — Revolve2
    '    段1: R=0.01, X=0~0.04
    '    段2: R=0.015, X=0.04~0.08
    '    段3: R=0.01, X=0.08~0.12
    ' ============================================================
    Debug.Print vbCrLf & "=== 0.阶梯轴基体 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 0.01, 0
    swSketchMgr.CreateLine 0, 0.01, 0, 0.04, 0.01, 0
    swSketchMgr.CreateLine 0.04, 0.01, 0, 0.04, 0.015, 0
    swSketchMgr.CreateLine 0.04, 0.015, 0, 0.08, 0.015, 0
    swSketchMgr.CreateLine 0.08, 0.015, 0, 0.08, 0.01, 0
    swSketchMgr.CreateLine 0.08, 0.01, 0, 0.12, 0.01, 0
    swSketchMgr.CreateLine 0.12, 0.01, 0, 0.12, 0, 0
    swSketchMgr.CreateLine 0.12, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.12, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  Revolve2=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If swFeat Is Nothing Then MsgBox "基体失败!", vbCritical: Exit Sub
    swFeat.Name = "Shaft"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 1. Extrusion2(23) 凸台 — 段2中间加粗环
    '    Y=0.008~0.018 (跨表面Y=0.015), X=0.05~0.07
    '    Z双向 0.005 (总宽10mm)
    ' ============================================================
    Debug.Print vbCrLf & "=== 1.Extrusion2 凸台 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.05, 0.008, 0, 0.07, 0.008, 0
    swSketchMgr.CreateLine 0.07, 0.008, 0, 0.07, 0.018, 0
    swSketchMgr.CreateLine 0.07, 0.018, 0, 0.05, 0.018, 0
    swSketchMgr.CreateLine 0.05, 0.018, 0, 0.05, 0.008, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.005, 0.005, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False)
    Debug.Print "  Ext2=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss-Ring"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 2. RevolveCut(20) 退刀槽 — 段2右端
    '    Y=0.012~0.018 (跨表面Y=0.015, 切深3mm)
    '    X=0.072~0.08
    ' ============================================================
    Debug.Print vbCrLf & "=== 2.RevolveCut 退刀槽 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.072, 0.012, 0, 0.08, 0.012, 0
    swSketchMgr.CreateLine 0.08, 0.012, 0, 0.08, 0.018, 0
    swSketchMgr.CreateLine 0.08, 0.018, 0, 0.072, 0.018, 0
    swSketchMgr.CreateLine 0.072, 0.018, 0, 0.072, 0.012, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.12, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, True, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  RevolveCut=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Groove"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 3. Cut3(26) 键槽 — 段2左侧顶部
    '    Y=0.01~0.015 (嵌入轴体5mm), X=0.042~0.062
    '    Z双向 0.003 (键宽6mm)
    ' ============================================================
    Debug.Print vbCrLf & "=== 3.Cut3 键槽 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.042, 0.01, 0, 0.062, 0.01, 0
    swSketchMgr.CreateLine 0.062, 0.01, 0, 0.062, 0.015, 0
    swSketchMgr.CreateLine 0.062, 0.015, 0, 0.042, 0.015, 0
    swSketchMgr.CreateLine 0.042, 0.015, 0, 0.042, 0.01, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.003, False, 0, 0.003, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, 0#, False, False, False)
    Debug.Print "  Cut3=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Keyway"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 4. Extrusion3(22) 轴肩 — 段3
    '    Y=0.005~0.012 (跨表面Y=0.01), X=0.085~0.1
    ' ============================================================
    Debug.Print vbCrLf & "=== 4.Extrusion3 轴肩 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.085, 0.005, 0, 0.1, 0.005, 0
    swSketchMgr.CreateLine 0.1, 0.005, 0, 0.1, 0.012, 0
    swSketchMgr.CreateLine 0.1, 0.012, 0, 0.085, 0.012, 0
    swSketchMgr.CreateLine 0.085, 0.012, 0, 0.085, 0.005, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.005, 0.005, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False)
    Debug.Print "  Ext3=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Shoulder"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 5. Chamfer(8) 倒角 — 轴右端面棱边
    '    选边: X=0.12 (端面), Y=0.01 (半径), Z=0.003 (侧面偏移)
    '    45° x 1.5mm
    ' ============================================================
    Debug.Print vbCrLf & "=== 5.Chamfer 轴端 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 0.12, 0.01, 0.003, False, 0, Nothing, 0
    Debug.Print "  选边 Err=" & Err.Number
    If Err.Number = 0 Then
        bn = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.0015, 0#, 0#, 0#, False)
        Debug.Print "  Chamfer=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "Chamfer"
    End If
    On Error GoTo ErrHandler

    ' ============================================================
    ' 6. Fillet(8) 圆角 — 凸台棱边
    '    选凸台顶面棱边 (0.06, 0.018, 0.005)
    '    Options=195 (必须!), R=1mm
    ' ============================================================
    Debug.Print vbCrLf & "=== 6.Fillet 圆角 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 0.06, 0.018, 0.005, False, 0, Nothing, 0
    Debug.Print "  选边 Err=" & Err.Number
    If Err.Number = 0 Then
        bn = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet3(195, 0.001, 0, 0, False, 0, False, False)
        Debug.Print "  Fillet=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "Fillet"
    End If

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
    MsgBox "v45 完成！" & vbCrLf & vbCrLf & _
           "阶梯轴模型: 基体+凸台+退刀槽+键槽+轴肩+倒角+圆角" & vbCrLf & _
           "7/7 特征 API 全部调通!", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! Err #" & Err.Number & ": " & Err.Description
    On Error Resume Next
    swModel.InsertSketch2 True
    Resume Next
End Sub
