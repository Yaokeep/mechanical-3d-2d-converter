Option Explicit

' ============================================================
' v40: 基于 v39 突破深化验证
'
' v39 突破:
'   ✅ Extrusion2(23参) 前视基准面首次成功!
'   ✅ RevolveCut(20参) 首次成功!
'   ✅ 确认: 草图必须打开状态调用特征方法
'
' v40 目标:
'   1. 验证 Extrusion2 在不同平面的可靠性 (前视/右视/上视)
'   2. 验证 RevolveCut 的可重复性
'   3. FeatureExtrusion3 参数扫描 (v39 报 Err=450)
'   4. Cut3 深入测试 (Err=0但失败 — 不是参数个数问题)
'   5. 尝试建造一个简单阶梯轴 (多段拉伸)
' ============================================================

Dim swApp As Object
Dim swModel As Object
Dim swFeatMgr As Object
Dim swSketchMgr As Object
Dim swFeat As Object
Dim bn As Long

' ========== 辅助: Extrusion2 参数扫描 ==========
Sub TestExtrusion2Scan(count As Long, planeName As String, cx As Double, cy As Double, cz As Double)
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 planeName, "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    ' 在指定中心画小矩形
    swSketchMgr.CreateLine cx - 0.005, cy, cz - 0.003, cx + 0.005, cy, cz - 0.003
    swSketchMgr.CreateLine cx + 0.005, cy, cz - 0.003, cx + 0.005, cy, cz + 0.003
    swSketchMgr.CreateLine cx + 0.005, cy, cz + 0.003, cx - 0.005, cy, cz + 0.003
    swSketchMgr.CreateLine cx - 0.005, cy, cz + 0.003, cx - 0.005, cy, cz - 0.003
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Select Case count
        Case 21
            Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False)
        Case 22
            Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False)
        Case 23
            Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False)
        Case 24
            Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False, False)
        Case 25
            Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False, False, False)
    End Select
    Debug.Print "  Ext2(" & count & "," & planeName & ")=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Ext2-" & count & "-" & planeName
End Sub

' ========== 辅助: FeatureExtrusion3 参数扫描 ==========
Sub TestExtrusion3Scan(count As Long)
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.035, 0.002, -0.003, 0.045, 0.002, -0.003
    swSketchMgr.CreateLine 0.045, 0.002, -0.003, 0.045, 0.002, 0.003
    swSketchMgr.CreateLine 0.045, 0.002, 0.003, 0.035, 0.002, 0.003
    swSketchMgr.CreateLine 0.035, 0.002, 0.003, 0.035, 0.002, -0.003
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Select Case count
        Case 22
            Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False)
        Case 23
            Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False, False)
        Case 24
            Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False, False, False)
        Case 25
            Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False, False, False, False)
        Case 26
            Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False, False, False, False, False)
        Case 27
            Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False, False, False, False, False, False)
        Case 28
            Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False, False, False, False, False, False, False)
    End Select
    Debug.Print "  Ext3(" & count & ")=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Ext3-" & count
End Sub

' ========== 辅助: Cut3 参数扫描 (在已知 26 参附近扩大) ==========
Sub TestCut3Scan(count As Long)
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    ' 矩形在圆柱体内部, 确保切除区域与实体相交
    swSketchMgr.CreateLine 0.015, 0.002, -0.003, 0.025, 0.002, -0.003
    swSketchMgr.CreateLine 0.025, 0.002, -0.003, 0.025, 0.002, 0.003
    swSketchMgr.CreateLine 0.025, 0.002, 0.003, 0.015, 0.002, 0.003
    swSketchMgr.CreateLine 0.015, 0.002, 0.003, 0.015, 0.002, -0.003
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Select Case count
        Case 24
            Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, 0#, False)
        Case 25
            Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, 0#, False, False)
        Case 26
            Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, 0#, False, False, False)
        Case 27
            Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, 0#, False, False, False, False)
        Case 28
            Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, 0#, False, False, False, False, False)
    End Select
    Debug.Print "  Cut3(" & count & ")=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Cut3-" & count
End Sub


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
    ' 0. 圆柱体基体
    ' ============================================================
    Debug.Print vbCrLf & "=== 0.圆柱体基体 ==="
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
    swFeat.Name = "BaseCylinder"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 1. Extrusion2 — 在圆柱体表面(前视)创建凸台 (v39已验证)
    ' ============================================================
    Debug.Print vbCrLf & "=== 1.Extrusion2 前视面凸台(验证v39) ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.04, 0.002, -0.003, 0.04, 0.002, 0.003
    swSketchMgr.CreateLine 0.04, 0.002, 0.003, 0.04, 0.008, 0.003
    swSketchMgr.CreateLine 0.04, 0.008, 0.003, 0.04, 0.008, -0.003
    swSketchMgr.CreateLine 0.04, 0.008, -0.003, 0.04, 0.002, -0.003
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False)
    Debug.Print "  Ext2-Front(23)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss-Front1"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 2. RevolveCut — v39 验证过的切除
    ' ============================================================
    Debug.Print vbCrLf & "=== 2.RevolveCut 验证 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.02, 0.003, 0, 0.03, 0.003, 0
    swSketchMgr.CreateLine 0.03, 0.003, 0, 0.03, 0.007, 0
    swSketchMgr.CreateLine 0.03, 0.007, 0, 0.02, 0.007, 0
    swSketchMgr.CreateLine 0.02, 0.007, 0, 0.02, 0.003, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, True, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  RevolveCut=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Groove1"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 3. Extrusion2 参数扫描 — 右视基准面
    ' 确认是否是平面位置问题导致失败
    ' ============================================================
    Debug.Print vbCrLf & "=== 3.Extrusion2 右视扫描 ==="
    TestExtrusion2Scan 21, "右视基准面", 0#, 0.005, 0#
    TestExtrusion2Scan 22, "右视基准面", 0#, 0.005, 0#
    TestExtrusion2Scan 23, "右视基准面", 0#, 0.005, 0#
    TestExtrusion2Scan 24, "右视基准面", 0#, 0.005, 0#
    TestExtrusion2Scan 25, "右视基准面", 0#, 0.005, 0#

    ' ============================================================
    ' 4. Extrusion2 参数扫描 — 前视基准面
    ' 确认前视面是否确实更稳定
    ' ============================================================
    Debug.Print vbCrLf & "=== 4.Extrusion2 前视扫描 ==="
    TestExtrusion2Scan 21, "前视基准面", 0.025, 0.005, 0#
    TestExtrusion2Scan 22, "前视基准面", 0.025, 0.005, 0#
    TestExtrusion2Scan 23, "前视基准面", 0.025, 0.005, 0#
    TestExtrusion2Scan 24, "前视基准面", 0.025, 0.005, 0#
    TestExtrusion2Scan 25, "前视基准面", 0.025, 0.005, 0#

    ' ============================================================
    ' 5. FeatureExtrusion3 参数扫描 (22→28)
    ' v39 报 Err=450 (26参不对), 找到正确参数数
    ' ============================================================
    Debug.Print vbCrLf & "=== 5.Extrusion3 扫描 ==="
    TestExtrusion3Scan 22
    TestExtrusion3Scan 23
    TestExtrusion3Scan 24
    TestExtrusion3Scan 25
    TestExtrusion3Scan 26
    TestExtrusion3Scan 27
    TestExtrusion3Scan 28

    ' ============================================================
    ' 6. Cut3 参数扫描 (24→28) — 前视基准面
    ' v39 Cut3(26) 在圆柱体内有几何但静默失败
    ' ============================================================
    Debug.Print vbCrLf & "=== 6.Cut3 前视扫描 ==="
    TestCut3Scan 24
    TestCut3Scan 25
    TestCut3Scan 26
    TestCut3Scan 27
    TestCut3Scan 28

    ' ============================================================
    ' 7. 尝试: FeatureCut4 替代 Cut3
    ' ============================================================
    Debug.Print vbCrLf & "=== 7.Cut4 测试 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.015, 0.002, -0.003, 0.025, 0.002, -0.003
    swSketchMgr.CreateLine 0.025, 0.002, -0.003, 0.025, 0.002, 0.003
    swSketchMgr.CreateLine 0.025, 0.002, 0.003, 0.015, 0.002, 0.003
    swSketchMgr.CreateLine 0.015, 0.002, 0.003, 0.015, 0.002, -0.003
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut4(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False)
    Debug.Print "  Cut4(22)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Cut4-22"
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
    MsgBox "v40 完成！Ctrl+G 看结果", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! Err #" & Err.Number & ": " & Err.Description
    On Error Resume Next
    swModel.InsertSketch2 True
    Resume Next
End Sub
