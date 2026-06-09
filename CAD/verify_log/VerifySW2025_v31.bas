Option Explicit

' VerifySW2025 v31 - 两阶段:
'   Phase A: 用v29的SelectByID2(无括号,Append=False)模式测试基准面创建
'   Phase B: 绕过基准面 — 在Top Plane上直接做键槽切除 (不需要新平面!)
' 设计思路: 阶梯轴键槽通常位于顶部，Top Plane切向圆柱体最高点

Dim swApp As Object, swModel As Object
Dim swFeatMgr As Object, swSketchMgr As Object
Dim swFeat As Object, swSelMgr As Object
Dim boolstatus As Boolean, featBefore As Long, featAfter As Long

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks: swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    Set swSelMgr = swModel.SelectionManager

    ' ==================================================================
    ' Phase A: 按v29成功模式测试基准面选择 + 创建
    ' v29成功: SelectByID2 "Front Plane","PLANE",0,0,0,False,0,Nothing,0
    ' v30失败: Extension.SelectByID2("Front Plane",...,True,...) → False
    ' ==================================================================
    Debug.Print "=== Phase A: 基准面选择测试(v29模式) ==="
    On Error Resume Next

    ' A1: 完全复制v29的SelectByID2语法(无括号, Append=False)
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "A1-选Front(v29语法): Err=" & Err.Number & _
                 " SelCount(-1)=" & swSelMgr.GetSelectedObjectCount2(-1)

    ' A2: 带括号版本 Append=False
    swModel.ClearSelection2 True
    Err.Clear
    boolstatus = swModel.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
    Debug.Print "A2-选Front(括号,Append=False): " & boolstatus & " Err=" & Err.Number

    ' A3: 带括号版本 Append=True
    swModel.ClearSelection2 True
    Err.Clear
    boolstatus = swModel.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0)
    Debug.Print "A3-选Front(括号,Append=True): " & boolstatus & " Err=" & Err.Number

    ' A4: SelectByID2 无最后一个Mark参数 (只有10个参数)
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing
    Debug.Print "A4-选Front(10参,无Mark): Err=" & Err.Number

    ' A5: IModelDoc2.Extension.SelectByID(不带2)
    swModel.ClearSelection2 True
    Err.Clear
    boolstatus = swModel.Extension.SelectByID("Front Plane", "PLANE", 0, 0, 0)
    Debug.Print "A5-SelectByID(不带2): " & boolstatus & " Err=" & Err.Number

    ' A6: 用FeatureByName获取Front Plane Feature
    Dim swFrontPlane As Object
    Set swFrontPlane = swModel.FeatureByName("Front Plane")
    If Not swFrontPlane Is Nothing Then
        Debug.Print "A6-FeatureByName(Front): OK 类型=" & swFrontPlane.GetTypeName
        ' 尝试选中这个特征
        swModel.ClearSelection2 True
        Err.Clear
        boolstatus = swFrontPlane.Select2(False, 0)
        Debug.Print "A6a-Front.Select2(False): " & boolstatus & " Err=" & Err.Number
        ' 或者用 Select2 True (Append)
        swModel.ClearSelection2 True
        Err.Clear
        boolstatus = swFrontPlane.Select2(True, 0)
        Debug.Print "A6b-Front.Select2(True): " & boolstatus & " Err=" & Err.Number
    Else
        Debug.Print "A6: FeatureByName(Front Plane) = Nothing!"
    End If

    ' A7: 获取Top Plane特征
    Dim swTopPlane As Object
    Set swTopPlane = swModel.FeatureByName("Top Plane")
    If Not swTopPlane Is Nothing Then
        Debug.Print "A7-FeatureByName(Top): OK 类型=" & swTopPlane.GetTypeName
    Else
        Debug.Print "A7: FeatureByName(Top Plane) = Nothing!"
    End If

    ' A8: 用FirstFeature遍历查找默认基准面
    Dim swF As Object
    Set swF = swModel.FirstFeature
    Debug.Print "A8-特征遍历:"
    Do While Not swF Is Nothing
        Dim ftype As String
        ftype = swF.GetTypeName
        If Left(ftype, 9) = "RefPlane" Or Left(swF.Name, 5) = "Plane" Then
            Debug.Print "  [" & swF.Name & "] 类型=" & ftype
        End If
        Set swF = swF.GetNextFeature
    Loop

    On Error GoTo ErrHandler

    ' ==================================================================
    ' Phase B: 完整的阶梯轴 + 键槽 (不需要新基准面!)
    ' 策略: 在Top Plane上画键槽草图 → 向下拉伸切除
    '      旋转轴=Z(水平), 圆柱最高点=Top Plane(Y+方向)
    '      键槽在圆柱顶部, X=轴向位置, Z=宽度
    ' ==================================================================
    Debug.Print vbCrLf & "=== Phase B: 完整阶梯轴 + 键槽 ==="
    featBefore = swModel.GetFeatureCount
    If featBefore <= 3 Then
        ' 空零件 — 创建完整的阶梯轴
        BuildShaft
    Else
        Debug.Print "  已有特征数: " & featBefore & ", 跳过轴创建"
        Debug.Print "  请用 Ctrl+N 新建零件后重新运行以测试完整流程"
    End If

    ' 键槽切除: 在Top Plane上
    Debug.Print vbCrLf & "--- 键槽切除(Top Plane) ---"
    featBefore = swModel.GetFeatureCount
    On Error Resume Next

    ' 选中Top Plane → 插入草图
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "选Top plane: Err=" & Err.Number

    If Err.Number = 0 Then
        swModel.InsertSketch2 True

        ' Top Plane = XZ平面(Y=0), 圆柱半径=10mm→0.01m, 圆柱顶在Y=10mm
        ' 键槽: X方向20-40mm, Z方向-4到4mm(8mm宽), 深度5mm
        ' 注意: 草图在Top Plane(Y=0), 需要在Y=0处画, 切除方向-Y(向下)
        ' 但圆柱体在Y方向从0到10mm, 顶部在Y=10mm
        ' 实际上旋转轴沿Z方向(之前v20+用的是X轴, 现在统一)

        ' 先确认: 我们之前用的是哪个旋转轴?
        ' v29: CreateCenterLine 0,0,0,50,0,0 → X轴旋转
        ' 圆柱截面在XY平面(Y=0-10, X=0-50), 绕X轴旋转→圆柱沿X
        ' Top Plane = XZ, 圆柱顶部在Y=10(相对X轴)

        ' 键槽位于圆柱顶部Y=10处
        ' Top Plane通过原点, 圆柱顶部离Top Plane = 10mm
        ' 画键槽草图: X=20-40, Z=-4-4
        swSketchMgr.CreateLine 20 / 1000#, 0, -4 / 1000#, 40 / 1000#, 0, -4 / 1000#
        swSketchMgr.CreateLine 40 / 1000#, 0, -4 / 1000#, 40 / 1000#, 0, 4 / 1000#
        swSketchMgr.CreateLine 40 / 1000#, 0, 4 / 1000#, 20 / 1000#, 0, 4 / 1000#
        swSketchMgr.CreateLine 20 / 1000#, 0, 4 / 1000#, 20 / 1000#, 0, -4 / 1000#
        Debug.Print "  键槽草图: X=20-40, Z=-4~4 (在Top Plane上)"

        ' FeatureCut3: 盲孔深度=键槽深度5mm+预留2mm=7mm
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureCut3( _
            True, False, False, _
            False, 0, 0.007, _
            False, 0, 0.007, _
            False, False, 0#, _
            False, 0#, _
            False, 0#, _
            False, 0#, _
            False, 0#, _
            False, 0#, _
            False, False, Nothing, False)
        Debug.Print "Cut3(盲孔7mm): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        featAfter = swModel.GetFeatureCount
        Debug.Print "  特征数: " & featBefore & "->" & featAfter

        ' Cut4 试试
        If swFeat Is Nothing Then
            swModel.InsertSketch2 True  ' 重新进入草图
            Set swFeat = Nothing: Err.Clear
            Set swFeat = swFeatMgr.FeatureCut4(True, False, False, _
                False, 0, 0.007, _
                False, 0, 0.007, _
                False, False, 0#, _
                False, 0#, _
                False, 0#, _
                False, 0#, _
                False, 0#, _
                False, 0#, _
                False, False)
            Debug.Print "Cut4(28参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        End If
    End If

    On Error GoTo ErrHandler
    Debug.Print "最终特征数: " & swModel.GetFeatureCount

    swModel.ViewZoomtofit2
    MsgBox "v31 测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
    On Error Resume Next: swModel.InsertSketch2 True
End Sub

' ==================================================================
' 创建完整阶梯轴 (参考 v29 成功模式)
' ==================================================================
Private Sub BuildShaft()
    On Error Resume Next
    Debug.Print "--- 创建阶梯轴 ---"

    ' 选Front Plane → 草图 → 旋转体
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    ' 轴截面 (绕X轴旋转)
    ' Y=半径, 单位: 米
    swSketchMgr.CreateLine 0, 0, 0, 0, 10 / 1000#, 0
    swSketchMgr.CreateLine 0, 10 / 1000#, 0, 20 / 1000#, 10 / 1000#, 0
    swSketchMgr.CreateLine 20 / 1000#, 10 / 1000#, 0, 20 / 1000#, 15 / 1000#, 0
    swSketchMgr.CreateLine 20 / 1000#, 15 / 1000#, 0, 40 / 1000#, 15 / 1000#, 0
    swSketchMgr.CreateLine 40 / 1000#, 15 / 1000#, 0, 40 / 1000#, 10 / 1000#, 0
    swSketchMgr.CreateLine 40 / 1000#, 10 / 1000#, 0, 50 / 1000#, 10 / 1000#, 0
    swSketchMgr.CreateLine 50 / 1000#, 10 / 1000#, 0, 50 / 1000#, 0, 0
    swSketchMgr.CreateLine 50 / 1000#, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 50 / 1000#, 0, 0

    Dim featBefore As Long
    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, _
        0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  阶梯轴: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & _
                 " 特征: " & featBefore & "→" & swModel.GetFeatureCount & " Err=" & Err.Number

    ' 倒角: 轴端倒角 (X=50, 边缘)
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 50 / 1000#, 10 / 1000#, 0, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
    Debug.Print "  倒角: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number

    ' 圆角: 台阶根部 (X=40, Y=10圆柱面, 半径1mm)
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "FACE", 40 / 1000#, 0, 10 / 1000#, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet3(195, 0.001, 0, 0, False, 0, False, False)
    Debug.Print "  圆角: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number

    On Error GoTo 0
End Sub
