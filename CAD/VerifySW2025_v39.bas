Option Explicit

' ============================================================
' v39 核心假设: 特征创建方法(Extrusion2/Cut3/Extrusion3)
' 必须在草图打开状态下调用，与 FeatureRevolve2 相同!
'
' v37 已确认参数个数: Extrusion2=23参, Cut3=26参
' 但 v37/v38 在调用前关闭了草图 → 静默失败
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
    ' 0. 圆柱体基体 (已验证可用)
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
    ' 草图打开状态调用 FeatureRevolve2 → 已验证可用
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  Revolve2=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If swFeat Is Nothing Then MsgBox "圆柱体失败!", vbCritical: Exit Sub
    swFeat.Name = "Cylinder"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 1. Extrusion2(23参) — 草图打开!
    ' ============================================================
    Debug.Print vbCrLf & "=== 1.Extrusion2(23参) 草图打开 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "右视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True        ' 打开草图
    swSketchMgr.CreateLine 0.05, 0, -0.005, 0.05, 0, 0.005
    swSketchMgr.CreateLine 0.05, 0, 0.005, 0.05, 0.012, 0.005
    swSketchMgr.CreateLine 0.05, 0.012, 0.005, 0.05, 0.012, -0.005
    swSketchMgr.CreateLine 0.05, 0.012, -0.005, 0.05, 0, -0.005
    ' ★ 不关闭草图! 直接调用特征方法
    ' Extrusion2(23参): Sd,Flip,D1, D1End,D2End, D1Depth,D2Depth, D1Draft,D2Draft,
    '   D1DraftRev,D2DraftRev, D1DraftAng,D2DraftAng, D1DraftOut,D2DraftOut,
    '   D1OffDist,D2OffDist, D1OffRev, Merge, FeatScope, StartOff, OffDist, FlipStartOff
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False)
    Debug.Print "  Ext2(23)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss-Ext2"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 2. Extrusion2(23参) — 用更简单的形状 (矩形在圆柱面上)
    ' ============================================================
    Debug.Print vbCrLf & "=== 2.Extrusion2(23参) 圆柱面草图 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    ' 选一个圆柱体的切平面 (上视基准面, Y=0.01)
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.015, 0.01, -0.004, 0.035, 0.01, -0.004
    swSketchMgr.CreateLine 0.035, 0.01, -0.004, 0.035, 0.01, 0.004
    swSketchMgr.CreateLine 0.035, 0.01, 0.004, 0.015, 0.01, 0.004
    swSketchMgr.CreateLine 0.015, 0.01, 0.004, 0.015, 0.01, -0.004
    ' ★ 草图打开
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2( _
        True, False, False, _
        0, 0, _
        0.02, 0.02, _
        False, False, _
        False, False, _
        0#, 0#, _
        False, False, _
        0#, 0#, _
        True, True, True, _
        False, 0#, False)
    Debug.Print "  Ext2-Top(23)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss-Top"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 3. Cut3(26参) — 草图打开!
    ' ============================================================
    Debug.Print vbCrLf & "=== 3.Cut3(26参) 草图打开 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True        ' 打开草图
    swSketchMgr.CreateLine 0.005, 0.01, -0.003, 0.02, 0.01, -0.003
    swSketchMgr.CreateLine 0.02, 0.01, -0.003, 0.02, 0.01, 0.003
    swSketchMgr.CreateLine 0.02, 0.01, 0.003, 0.005, 0.01, 0.003
    swSketchMgr.CreateLine 0.005, 0.01, 0.003, 0.005, 0.01, -0.003
    ' ★ 草图打开状态
    ' Cut3(26参): Sd,Flip,D1, D2, D1End,D1Depth, D1Draft, D2End,D2Depth,
    '   D2Draft,D2DraftRev, D1DraftAng,D1OffDist, D1DraftOut,D1OffRev,
    '   D2OffDist,D2OffRev, D2DraftOut, Merge,FeatScope, AutoSelect,
    '   StartOff,OffDist, FlipStartOff, p24, p25
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, 0#, False, False, False)
    Debug.Print "  Cut3(26)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Cut3-26"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 4. FeatureExtrusion3(26参) — 草图打开!
    ' ============================================================
    Debug.Print vbCrLf & "=== 4.Extrusion3(26参) 草图打开 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "右视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.07, 0, -0.005, 0.07, 0, 0.005
    swSketchMgr.CreateLine 0.07, 0, 0.005, 0.07, 0.012, 0.005
    swSketchMgr.CreateLine 0.07, 0.012, 0.005, 0.07, 0.012, -0.005
    swSketchMgr.CreateLine 0.07, 0.012, -0.005, 0.07, 0, -0.005
    ' ★ 草图打开
    ' Extrusion3(26参): Sd,Flip,D1, D1End,D2End, D1Depth,D2Depth, D1Draft,D2Draft,
    '   D1DraftRev,D2DraftRev, D1DraftAng,D2DraftAng, D1DraftOut,D2DraftOut,
    '   D1OffDist,D2OffDist, D1OffRev,D2OffRev, D1OffOut,D2OffOut, OffRev,
    '   TranslateSurf, Merge,FeatScope,AutoSelect
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False, False, False, True, True, True)
    Debug.Print "  Ext3(26)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss-Ext3"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 5. RevolveCut — 确保几何相交 + 草图打开
    ' ============================================================
    Debug.Print vbCrLf & "=== 5.RevolveCut 相交测试 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True        ' 打开草图
    ' 矩形在圆柱体内部 (圆柱体 Y=0~0.01, 半径=0.05)
    ' 切除区域: X=0.02~0.04, Y=0.002~0.008 (完全在圆柱体内部)
    swSketchMgr.CreateLine 0.02, 0.002, 0, 0.04, 0.002, 0
    swSketchMgr.CreateLine 0.04, 0.002, 0, 0.04, 0.008, 0
    swSketchMgr.CreateLine 0.04, 0.008, 0, 0.02, 0.008, 0
    swSketchMgr.CreateLine 0.02, 0.008, 0, 0.02, 0.002, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0
    ' ★ 草图打开状态
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, True, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  RevolveCut(20)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "RevolveCut"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 6. RevolveCut 备选: 不同切除方向
    ' ============================================================
    Debug.Print vbCrLf & "=== 6.RevolveCut ReverseDir ==="
    ' 即使上面失败了(因为用了InsertSketch2 True退出草图状态), 这个测试正确打开草图
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.02, 0.003, 0, 0.03, 0.003, 0
    swSketchMgr.CreateLine 0.03, 0.003, 0, 0.03, 0.007, 0
    swSketchMgr.CreateLine 0.03, 0.007, 0, 0.02, 0.007, 0
    swSketchMgr.CreateLine 0.02, 0.007, 0, 0.02, 0.003, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0
    ' ★ 草图打开
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, True, True, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  RevCut-Rev(20)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "RevCut-Rev"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 7. 最终: Extrusion2 作为凸台 — 再试一次确保没有累积状态问题
    ' 草图打开 + 正确参数 + 不同平面
    ' ============================================================
    Debug.Print vbCrLf & "=== 7.Extrusion2 最终尝试 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.04, 0.002, -0.003, 0.04, 0.002, 0.003
    swSketchMgr.CreateLine 0.04, 0.002, 0.003, 0.04, 0.008, 0.003
    swSketchMgr.CreateLine 0.04, 0.008, 0.003, 0.04, 0.008, -0.003
    swSketchMgr.CreateLine 0.04, 0.008, -0.003, 0.04, 0.002, -0.003
    ' ★ 草图打开
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2( _
        True, False, False, _
        0, 0, _
        0.02, 0.02, _
        False, False, _
        False, False, _
        0#, 0#, _
        False, False, _
        0#, 0#, _
        True, True, True, _
        False, 0#, False)
    Debug.Print "  Ext2-Final(23)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss-Final"

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
    MsgBox "v39 完成！Ctrl+G 看结果", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! Err #" & Err.Number & ": " & Err.Description
    On Error Resume Next
    swModel.InsertSketch2 True
    Resume Next
End Sub
