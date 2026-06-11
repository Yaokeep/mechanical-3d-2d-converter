Option Explicit

' ============================================================
' v43: 修复 v42 三个问题
'
' 问题1: Extrusion2/RevolveCut/Cut3 草图悬空
'   → 矩形必须部分嵌入实体内部 (Y 坐标伸入轴体内)
' 问题2: Chamfer 选面不选边
'   → 选边坐标必须精确在棱线上
' 问题3: Fillet 圆柱面全选
'   → 改用选边而非选面
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
    ' 0. 圆柱体基体 R=0.015(15mm), L=0.1(100mm)
    '    空间: X=0~0.1, 表面 Y=0.015 (world)
    ' ============================================================
    Debug.Print vbCrLf & "=== 0.圆柱体 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 0.015, 0
    swSketchMgr.CreateLine 0, 0.015, 0, 0.1, 0.015, 0
    swSketchMgr.CreateLine 0.1, 0.015, 0, 0.1, 0, 0
    swSketchMgr.CreateLine 0.1, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.1, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  Revolve2=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If swFeat Is Nothing Then MsgBox "圆柱体失败!", vbCritical: Exit Sub
    swFeat.Name = "Cylinder"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 1. Extrusion2(23) 凸台
    '    关键: Y 坐标部分嵌入实体 (Y=0.008~0.018, 轴表面Y=0.015)
    '    嵌入部分 0.008~0.015 (7mm在体内), 突出 0.015~0.018 (3mm在外)
    '    X=0.03~0.06, Z拉伸双向 0.005
    ' ============================================================
    Debug.Print vbCrLf & "=== 1.Extrusion2 凸台(嵌入实体) ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.03, 0.008, 0, 0.06, 0.008, 0
    swSketchMgr.CreateLine 0.06, 0.008, 0, 0.06, 0.018, 0
    swSketchMgr.CreateLine 0.06, 0.018, 0, 0.03, 0.018, 0
    swSketchMgr.CreateLine 0.03, 0.018, 0, 0.03, 0.008, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.005, 0.005, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False)
    Debug.Print "  Ext2=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 2. RevolveCut(20) 退刀槽
    '    矩形 Y=0.012~0.018 (跨轴表面Y=0.015), X=0.065~0.08
    '    体内部分Y=0.012~0.015 (3mm切深), 体外部分确保切透
    ' ============================================================
    Debug.Print vbCrLf & "=== 2.RevolveCut 槽 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.065, 0.012, 0, 0.08, 0.012, 0
    swSketchMgr.CreateLine 0.08, 0.012, 0, 0.08, 0.018, 0
    swSketchMgr.CreateLine 0.08, 0.018, 0, 0.065, 0.018, 0
    swSketchMgr.CreateLine 0.065, 0.018, 0, 0.065, 0.012, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.1, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, True, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  RevolveCut=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Groove"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 3. Cut3(26) 键槽
    '    矩形 Y=0.01~0.015 (伸入轴体5mm), X=0.04~0.06
    '    Z双向切 0.004 (键宽8mm)
    ' ============================================================
    Debug.Print vbCrLf & "=== 3.Cut3 键槽 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.04, 0.01, 0, 0.06, 0.01, 0
    swSketchMgr.CreateLine 0.06, 0.01, 0, 0.06, 0.015, 0
    swSketchMgr.CreateLine 0.06, 0.015, 0, 0.04, 0.015, 0
    swSketchMgr.CreateLine 0.04, 0.015, 0, 0.04, 0.01, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.004, False, 0, 0.004, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, 0#, False, False, False)
    Debug.Print "  Cut3=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Keyway"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 4. Extrusion3(22) 第二凸台
    '    矩形 Y=0.005~0.017, X=0.08~0.095 (嵌入轴体)
    ' ============================================================
    Debug.Print vbCrLf & "=== 4.Extrusion3 凸台 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.08, 0.005, 0, 0.095, 0.005, 0
    swSketchMgr.CreateLine 0.095, 0.005, 0, 0.095, 0.017, 0
    swSketchMgr.CreateLine 0.095, 0.017, 0, 0.08, 0.017, 0
    swSketchMgr.CreateLine 0.08, 0.017, 0, 0.08, 0.005, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.005, 0.005, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False)
    Debug.Print "  Ext3=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss2"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 5. Chamfer 倒角 — 精确选边
    '    选 X=0.1 处轴端面与圆柱面的交线
    '    坐标放在棱线上: X=0.1(端面), Y=0.015(半径), Z=0.005(偏一点)
    ' ============================================================
    Debug.Print vbCrLf & "=== 5.Chamfer 轴端边 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    ' 选棱边: 在轴右端面上缘, 坐标精确在边线上
    swModel.Extension.SelectByID2 "", "EDGE", 0.1, 0.015, 0.005, False, 0, Nothing, 0
    Debug.Print "  选边 Err=" & Err.Number
    If Err.Number = 0 Then
        bn = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
        Debug.Print "  Chamfer=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "Chamfer"
    Else
        Debug.Print "  Chamfer: 跳过 (选边失败)"
    End If
    On Error GoTo ErrHandler

    ' ============================================================
    ' 6. Fillet 圆角 — 选轴肩面 (非圆柱面)
    '    选 Extrusion2 凸台生成的平面或轴端面
    '    如果上面 Boss 成功了，选 Boss 侧面的棱边
    ' ============================================================
    Debug.Print vbCrLf & "=== 6.Fillet 棱边 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    ' 选轴体表面与凸台相交的棱边
    ' 选点在圆柱面上靠近凸台的位置: X=0.045, Y=0.015, Z=0.004
    swModel.Extension.SelectByID2 "", "EDGE", 0.045, 0.015, 0.004, False, 0, Nothing, 0
    Debug.Print "  选边 Err=" & Err.Number
    If Err.Number = 0 Then
        bn = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet3(195, 0.0015, 0, 0, False, 0, False, False)
        Debug.Print "  Fillet=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "Fillet"
    Else
        Debug.Print "  Fillet: 跳过 (选边失败)"
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
    MsgBox "v43 完成！Ctrl+G 看结果", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! Err #" & Err.Number & ": " & Err.Description
    On Error Resume Next
    swModel.InsertSketch2 True
    Resume Next
End Sub
