Option Explicit

' VerifySW2025 v32 - 按官方文档确切模式 + 多Cut API测试
' 关键修复:
'   1. SelectByID2 不用括号 (v31证实A1语法成功)
'   2. SelectByID2 Append=True (官方文档要求)
'   3. InsertRefPlane 后4参数用整数0, 非Boolean False
'   4. Cut API: 测试FeatureCut/FeatureCut3/FeatureCut4/FeatureCut5/FeatureExtrusion3

Dim swApp As Object, swModel As Object
Dim swFeatMgr As Object, swSketchMgr As Object
Dim swFeat As Object, swSelMgr As Object
Dim boolstatus As Boolean, featBefore As Long

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks: swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    Set swSelMgr = swModel.SelectionManager

    featBefore = swModel.GetFeatureCount
    Debug.Print "初始特征数: " & featBefore

    ' ==================================================================
    ' Phase A: 按官方文档模式创建基准面
    ' SelectByID2 不用括号 + Append=True + InsertRefPlane(8,dist,0,0,0,0)
    ' ==================================================================
    Debug.Print vbCrLf & "=== Phase A: 官方文档模式基准面 ==="
    On Error Resume Next

    ' A1: SelectByID2 不用括号, Append=True
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    Debug.Print "A1-选Front(Append=True): Err=" & Err.Number

    If Err.Number = 0 Then
        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        ' 8=Offset, 0.01=10mm, 后4参=整数0(非Boolean)
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
        Debug.Print "A1-InsertRefPlane(8,0.01,0,0,0,0): " & _
                     IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then
            Debug.Print "  ★ 基准面创建成功! 名称: " & swFeat.Name
        End If
    End If

    ' A2: 试试用Top Plane
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    Debug.Print "A2-选Top(Append=True): Err=" & Err.Number

    If Err.Number = 0 Then
        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.02, 0, 0, 0, 0)
        Debug.Print "A2-InsertRefPlane(Top,0.02): " & _
                     IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount
    End If

    ' A3: 中文名测试 - v31发现特征遍历中名称是"前视基准面"
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    Debug.Print "A3-选前视基准面(中文): Err=" & Err.Number

    ' A4: 再试FeatureRefPlane (另一种创建方式)
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    If Err.Number = 0 Then
        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureRefPlane(8, 0.01, 0, 0, 0, 0)
        Debug.Print "A4-FeatureRefPlane(8,0.01,0,0,0,0): " & _
                     IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' A5: 用IModelDoc2.CreatePlaneAtOffset3
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    If Err.Number = 0 Then
        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swModel.CreatePlaneAtOffset3(0.01, False, True)
        Debug.Print "A5-CreatePlaneAtOffset3(0.01,False,True): " & _
                     IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount
    End If

    On Error GoTo ErrHandler

    ' ==================================================================
    ' Phase B: 完整的阶梯轴 (如果零件是空的)
    ' ==================================================================
    If swModel.GetFeatureCount <= 3 Then
        BuildShaft
    Else
        Debug.Print vbCrLf & "=== 已有 " & swModel.GetFeatureCount & " 个特征，跳过轴创建 ==="
    End If

    ' ==================================================================
    ' Phase C: Cut API 系统性测试 (在Top Plane上画矩形)
    ' ==================================================================
    Debug.Print vbCrLf & "=== Phase C: Cut API 测试 ==="
    On Error Resume Next

    ' 先在Top Plane上创建草图
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "选Top Plane: Err=" & Err.Number
    swModel.InsertSketch2 True

    ' 画小矩形 (X=20-30mm, Z=-3-3mm)
    swSketchMgr.CreateLine 0.02, 0, -0.003, 0.03, 0, -0.003
    swSketchMgr.CreateLine 0.03, 0, -0.003, 0.03, 0, 0.003
    swSketchMgr.CreateLine 0.03, 0, 0.003, 0.02, 0, 0.003
    swSketchMgr.CreateLine 0.02, 0, 0.003, 0.02, 0, -0.003
    Debug.Print "矩形草图: X=20-30, Z=±3 (Top Plane)"

    ' C1: FeatureCut (基本版本, 可能需要20参数)
    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureCut( _
        True, False, False, _       ' ThroughAll, ThroughAllBoth, Flip
        False, 0#, 0.005, _         ' D1Reverse, D1Depth, D1EndCond
        False, 0#, 0.005, _         ' D2Reverse, D2Depth, D2EndCond
        False, False, 0#, _         ' Draft, DraftOutward, DraftAngle
        False, False, _             ' FlipStart, Propagate
        False, False, _             ' AutoSelect, ?
        False, False)               ' ?, ?
    Debug.Print "C1-FeatureCut(20参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount

    ' C2: FeatureCut(16参) 更少参数
    If swFeat Is Nothing Then
        swModel.InsertSketch2 True  ' 重新进草图
        swSketchMgr.CreateLine 0.02, 0, -0.003, 0.03, 0, -0.003
        swSketchMgr.CreateLine 0.03, 0, -0.003, 0.03, 0, 0.003
        swSketchMgr.CreateLine 0.03, 0, 0.003, 0.02, 0, 0.003
        swSketchMgr.CreateLine 0.02, 0, 0.003, 0.02, 0, -0.003

        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureCut( _
            True, False, False, _   ' 3
            False, 0#, 0.005, _     ' 6
            False, 0#, 0.005)       ' 9
        Debug.Print "C2-FeatureCut(9参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount
    End If

    ' C3: FeatureCut4(28参) 不同参数顺序
    If swFeat Is Nothing Then
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0.02, 0, -0.003, 0.03, 0, -0.003
        swSketchMgr.CreateLine 0.03, 0, -0.003, 0.03, 0, 0.003
        swSketchMgr.CreateLine 0.03, 0, 0.003, 0.02, 0, 0.003
        swSketchMgr.CreateLine 0.02, 0, 0.003, 0.02, 0, -0.003

        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureCut4( _
            True, False, False, _       ' 3
            False, 0.005, 0, _          ' D1Reverse, D1Depth, D1EndType (注意: Int EndType)
            False, 0.005, 0, _          ' D2
            False, False, 0#, _         ' Draft
            False, 0#, _                ' FlipStart
            False, 0#, _                ' Propagate
            False, 0#, _                ' AutoSelect
            False, 0#, _                '
            False, 0#, _                '
            False, False)               ' 28参数
        Debug.Print "C3-FeatureCut4(28参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount
    End If

    ' C4: FeatureCut5 (如果有)
    If swFeat Is Nothing Then
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0.02, 0, -0.003, 0.03, 0, -0.003
        swSketchMgr.CreateLine 0.03, 0, -0.003, 0.03, 0, 0.003
        swSketchMgr.CreateLine 0.03, 0, 0.003, 0.02, 0, 0.003
        swSketchMgr.CreateLine 0.02, 0, 0.003, 0.02, 0, -0.003

        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureCut5( _
            True, False, False, _       ' ThroughAll, ThroughAllBoth, Flip
            False, 0.005, 0, _          ' D1Reverse, D1Depth, D1EndType
            False, 0.005, 0, _          ' D2
            False, False, 0#, _         ' Draft
            False, 0#, _                ' FlipStart
            False, 0#, _                ' Propagate
            False, 0#, _                ' AutoSelect
            False, 0#, _                '
            False, 0#, _                '
            False, False)               '
        Debug.Print "C4-FeatureCut5: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount
    End If

    ' C5: FeatureExtrusion3 (统一拉伸API)
    If swFeat Is Nothing Then
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0.02, 0, -0.003, 0.03, 0, -0.003
        swSketchMgr.CreateLine 0.03, 0, -0.003, 0.03, 0, 0.003
        swSketchMgr.CreateLine 0.03, 0, 0.003, 0.02, 0, 0.003
        swSketchMgr.CreateLine 0.02, 0, 0.003, 0.02, 0, -0.003

        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureExtrusion3( _
            True, False, False, _       ' Sd, Flip, Dir
            0, 0, _                     ' T1, T2 (end types: 0=Blind)
            0.005, 0.005, _             ' D1, D2
            False, False, _             ' DraftCheck1, DraftCheck2
            False, False, _             ' DraftDir1, DraftDir2
            0#, 0#, _                   ' DraftAng1, DraftAng2
            False, False, _             ' OffsetCheck1, OffsetCheck2
            0#, 0#, _                   ' OffsetDist1, OffsetDist2
            False, False, _             ' Optimize, NormalCut
            0, _                        ' ThinWallType
            0#, 0#, _                   ' ThinWallT1, ThinWallT2
            False, _                    ' ReverseOffset
            True, _                     ' Merge
            False, _                    ' UseFeatScope
            False, Nothing, Nothing)    ' AutoSelect, FeatScope, ScopeBodies
        Debug.Print "C5-FeatureExtrusion3: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount
    End If

    On Error GoTo ErrHandler

    swModel.ViewZoomtofit2
    Debug.Print vbCrLf & "最终特征数: " & swModel.GetFeatureCount

    ' 列出所有特征名
    Dim swF As Object, i As Long
    For i = 1 To swModel.GetFeatureCount
        Set swF = swModel.FeatureByPositionReverse(i)
        If Not swF Is Nothing Then
            Debug.Print "  [" & i & "] " & swF.Name
        End If
    Next i

    MsgBox "v32 测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
    On Error Resume Next: swModel.InsertSketch2 True
End Sub

' ==================================================================
' 创建完整阶梯轴
' ==================================================================
Private Sub BuildShaft()
    On Error Resume Next
    Debug.Print vbCrLf & "--- 创建阶梯轴 ---"

    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    ' 轴截面 (绕X轴旋转): X=轴向, Y=半径
    swSketchMgr.CreateLine 0, 0, 0, 0, 0.01, 0
    swSketchMgr.CreateLine 0, 0.01, 0, 0.02, 0.01, 0
    swSketchMgr.CreateLine 0.02, 0.01, 0, 0.02, 0.015, 0
    swSketchMgr.CreateLine 0.02, 0.015, 0, 0.04, 0.015, 0
    swSketchMgr.CreateLine 0.04, 0.015, 0, 0.04, 0.01, 0
    swSketchMgr.CreateLine 0.04, 0.01, 0, 0.05, 0.01, 0
    swSketchMgr.CreateLine 0.05, 0.01, 0, 0.05, 0, 0
    swSketchMgr.CreateLine 0.05, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0

    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, _
        0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  阶梯轴: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & _
                 " Err=" & Err.Number & " 特征数→" & swModel.GetFeatureCount

    ' 倒角
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 0.05, 0.01, 0, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
    Debug.Print "  倒角: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number

    ' 圆角
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "FACE", 0.04, 0, 0.01, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet3(195, 0.001, 0, 0, False, 0, False, False)
    Debug.Print "  圆角: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number

    On Error GoTo 0
End Sub
