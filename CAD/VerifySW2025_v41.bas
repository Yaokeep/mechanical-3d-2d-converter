Option Explicit

' ============================================================
' v41: 严格草图几何 — Front Plane 全部 Z=0
'
' 关键教训:
'   v39 RevolveCut 成功: 所有 CreateLine Z=0
'   v39 Ext2 成功但 v40 失败: Z≠0 → 可能是偶然成功
'
' 假设: Z≠0 在 Front Plane 草图中导致线段退化(投影后成点)
' 这产生无效闭合轮廓 → 特征静默失败
'
' v41 策略: 所有 CreateLine Z=0, 矩形在圆柱体表面范围内
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
    ' 0. 圆柱体基体 (R=0.01m=10mm, L=0.05m=50mm, 绕X轴)
    '    空间范围: X=0~0.05, Y=0~0.01(R方向), 绕X旋转
    ' ============================================================
    Debug.Print vbCrLf & "=== 0.圆柱体 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 0.01, 0
    swSketchMgr.CreateLine 0, 0.01, 0, 0.05, 0.01, 0
    swSketchMgr.CreateLine 0.05, 0.01, 0, 0.05, 0, 0
    swSketchMgr.CreateLine 0.05, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  Revolve2=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If swFeat Is Nothing Then MsgBox "圆柱体失败!", vbCritical: Exit Sub
    swFeat.Name = "Cylinder"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 1. Extrusion2(23) Front Plane — 全部 Z=0
    '    矩形 X=0.025~0.045, Y=0.002~0.008 (在圆柱体表面上)
    '    拉伸方向: Z (双向 0.02m)
    ' ============================================================
    Debug.Print vbCrLf & "=== 1.Ext2 Front Z=0 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    ' 闭合矩形 — 全部 Z=0!
    swSketchMgr.CreateLine 0.025, 0.002, 0, 0.045, 0.002, 0
    swSketchMgr.CreateLine 0.045, 0.002, 0, 0.045, 0.008, 0
    swSketchMgr.CreateLine 0.045, 0.008, 0, 0.025, 0.008, 0
    swSketchMgr.CreateLine 0.025, 0.008, 0, 0.025, 0.002, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False)
    Debug.Print "  Ext2(Z=0)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss-Z0"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 2. Extrusion2(23) — 替代参数: 单方向 + Merge
    '    试试 D1Depth=0.01(仅Z正方向) + Merge=True
    '    矩形: 不同位置 X=0.01~0.03, Y=0.002~0.008
    ' ============================================================
    Debug.Print vbCrLf & "=== 2.Ext2 Front 单方向 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.01, 0.002, 0, 0.03, 0.002, 0
    swSketchMgr.CreateLine 0.03, 0.002, 0, 0.03, 0.008, 0
    swSketchMgr.CreateLine 0.03, 0.008, 0, 0.01, 0.008, 0
    swSketchMgr.CreateLine 0.01, 0.008, 0, 0.01, 0.002, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    ' 单方向拉伸: D1Depth=0.01, D2Depth=0, Sd=True
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.01, 0#, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False)
    Debug.Print "  Ext2-Single=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss-Single"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 3. RevolveCut(20) Front Plane — Z=0 矩形 + 中心线
    '    矩形 X=0.02~0.04, Y=0.003~0.007
    ' ============================================================
    Debug.Print vbCrLf & "=== 3.RevolveCut Z=0 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.02, 0.003, 0, 0.04, 0.003, 0
    swSketchMgr.CreateLine 0.04, 0.003, 0, 0.04, 0.007, 0
    swSketchMgr.CreateLine 0.04, 0.007, 0, 0.02, 0.007, 0
    swSketchMgr.CreateLine 0.02, 0.007, 0, 0.02, 0.003, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, True, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  RevolveCut=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Groove"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 4. FeatureExtrusion3(22) — v40 确认参数个数=22 (Err=0)
    '    测试不同的参数值组合 (Z=0 矩形)
    ' ============================================================
    Debug.Print vbCrLf & "=== 4.Ext3(22) 变体 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.035, 0.002, 0, 0.048, 0.002, 0
    swSketchMgr.CreateLine 0.048, 0.002, 0, 0.048, 0.008, 0
    swSketchMgr.CreateLine 0.048, 0.008, 0, 0.035, 0.008, 0
    swSketchMgr.CreateLine 0.035, 0.008, 0, 0.035, 0.002, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    ' Ext3(22): 前21个=标准, 最后可能是TranslateSurface
    Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False)
    Debug.Print "  Ext3-22a=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Ext3-22a"
    On Error GoTo ErrHandler

    ' Ext3(22) 变体B: 最后3个 = Merge,Scope,Auto (类似Ext2)
    Debug.Print "  --- Ext3 22b (最后=Merge/Scope/Auto) ---"
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.005, 0.002, 0, 0.018, 0.002, 0
    swSketchMgr.CreateLine 0.018, 0.002, 0, 0.018, 0.008, 0
    swSketchMgr.CreateLine 0.018, 0.008, 0, 0.005, 0.008, 0
    swSketchMgr.CreateLine 0.005, 0.008, 0, 0.005, 0.002, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, True, True, True)
    Debug.Print "  Ext3-22b=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Ext3-22b"

    ' ============================================================
    ' 5. Cut3(26) Front Plane — Z=0 + 在圆柱体内部
    ' ============================================================
    Debug.Print vbCrLf & "=== 5.Cut3(26) Z=0 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    ' 矩形在圆柱体内部: X=0.015~0.025, Y=0.002~0.006
    swSketchMgr.CreateLine 0.015, 0.002, 0, 0.025, 0.002, 0
    swSketchMgr.CreateLine 0.025, 0.002, 0, 0.025, 0.006, 0
    swSketchMgr.CreateLine 0.025, 0.006, 0, 0.015, 0.006, 0
    swSketchMgr.CreateLine 0.015, 0.006, 0, 0.015, 0.002, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, 0#, False, False, False)
    Debug.Print "  Cut3(26)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Cut3-Z0"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 6. Cut4 参数扫描 (22→28) — 找到正确参数个数
    ' ============================================================
    Debug.Print vbCrLf & "=== 6.Cut4 参数扫描 ==="
    TestCut4 22
    TestCut4 23
    TestCut4 24
    TestCut4 25
    TestCut4 26
    TestCut4 27
    TestCut4 28

    ' ============================================================
    ' 7. Extrusion2 最终验证 — 不同平面
    '    测试右视基准面和上视基准面
    ' ============================================================
    Debug.Print vbCrLf & "=== 7.Ext2 多平面 Z=0 ==="
    ' 7a: 上视基准面(XZ平面) — 草图点Y应=0, CreateLine坐标 (X, _, Z) 中 Y=0
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    ' 上视面: 用 X 和 Z 坐标, Y 为常量0
    swSketchMgr.CreateLine 0.02, 0, -0.004, 0.04, 0, -0.004
    swSketchMgr.CreateLine 0.04, 0, -0.004, 0.04, 0, 0.004
    swSketchMgr.CreateLine 0.04, 0, 0.004, 0.02, 0, 0.004
    swSketchMgr.CreateLine 0.02, 0, 0.004, 0.02, 0, -0.004
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False)
    Debug.Print "  Ext2-Top=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss-Top"
    On Error GoTo ErrHandler

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
    MsgBox "v41 完成！Ctrl+G 看结果", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! Err #" & Err.Number & ": " & Err.Description
    On Error Resume Next
    swModel.InsertSketch2 True
    Resume Next
End Sub

' ========== 辅助: Cut4 参数扫描 ==========
Sub TestCut4(count As Long)
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.015, 0.002, 0, 0.025, 0.002, 0
    swSketchMgr.CreateLine 0.025, 0.002, 0, 0.025, 0.006, 0
    swSketchMgr.CreateLine 0.025, 0.006, 0, 0.015, 0.006, 0
    swSketchMgr.CreateLine 0.015, 0.006, 0, 0.015, 0.002, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Select Case count
        Case 22
            Set swFeat = swFeatMgr.FeatureCut4(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False)
        Case 23
            Set swFeat = swFeatMgr.FeatureCut4(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, False)
        Case 24
            Set swFeat = swFeatMgr.FeatureCut4(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, False, False)
        Case 25
            Set swFeat = swFeatMgr.FeatureCut4(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, False, False, False)
        Case 26
            Set swFeat = swFeatMgr.FeatureCut4(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, False, False, False, False)
        Case 27
            Set swFeat = swFeatMgr.FeatureCut4(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, False, False, False, False, False)
        Case 28
            Set swFeat = swFeatMgr.FeatureCut4(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, False, False, False, False, False, False)
    End Select
    Debug.Print "  Cut4(" & count & ")=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Cut4-" & count
End Sub
