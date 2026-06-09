Option Explicit

' VerifySW2025 v27 - 先建旋转体, 在有特征的零件中测试基准面
' v26关键发现: 纯空零件中SelectByID2 FrontPlane返回0!

Dim swApp As Object, swModel As Object
Dim swFeatMgr As Object, swSketchMgr As Object
Dim swFeat As Object, swSelMgr As Object

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks: swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    Set swSelMgr = swModel.SelectionManager

    ' ====== 旋转体 ======
    Debug.Print "=== 旋转体 ==="
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "  选Front: " & swSelMgr.GetSelectedObjectCount2(-1)
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
    swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
    swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
    swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, _
        0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  旋转体: " & IIf(swFeat Is Nothing, "FAIL", "PASS")

    ' 验证基准面选择是否恢复正常
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "  旋转后选Front: " & swSelMgr.GetSelectedObjectCount2(-1)
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "  旋转后选Top: " & swSelMgr.GetSelectedObjectCount2(-1)

    ' ====== 基准面测试 ======
    Debug.Print vbCrLf & "=== 基准面 ==="
    On Error Resume Next
    Dim featBefore As Long, featAfter As Long
    Dim bFalse As Boolean: bFalse = False
    Dim bTrue As Boolean: bTrue = True

    ' P1: InsertRefPlane Boolean参数 (在非空零件中)
    featBefore = swModel.GetFeatureCount
    Debug.Print "  建面前特征数: " & featBefore
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "  选Top: " & swSelMgr.GetSelectedObjectCount2(-1)
    Err.Clear: Set swFeat = Nothing
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, bFalse, bFalse, bFalse, bFalse)
    Debug.Print "P1-InsertRefPlane(Bool): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    featAfter = swModel.GetFeatureCount
    Debug.Print "  特征数: " & featBefore & "→" & featAfter

    ' P2: 尝试不同偏移值
    If featAfter = featBefore Then
        featBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Err.Clear: Set swFeat = Nothing
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.02, bFalse, bFalse, bFalse, bFalse)
        Debug.Print "P2-InsertRefPlane(0.02): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        featAfter = swModel.GetFeatureCount
    End If

    ' P3: 整数参数（原始方式）
    If featAfter = featBefore Then
        featBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Err.Clear: Set swFeat = Nothing
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
        Debug.Print "P3-InsertRefPlane(Int): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        featAfter = swModel.GetFeatureCount
    End If

    ' P4: Front Plane偏移
    If featAfter = featBefore Then
        featBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Err.Clear: Set swFeat = Nothing
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, bFalse, bFalse, bFalse, bFalse)
        Debug.Print "P4-Front+Bool: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        featAfter = swModel.GetFeatureCount
    End If

    ' P5: 用 swRefPlaneFeatureData 方式
    If featAfter = featBefore Then
        featBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Err.Clear: Set swFeat = Nothing
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, bFalse, bFalse, bFalse, bFalse, bFalse)
        Debug.Print "P5-InsertRefPlane(7参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' P6: IModelDoc2.InsertRefPlane
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear: Set swFeat = Nothing
    Set swFeat = swModel.InsertRefPlane(8, 0.01, bFalse, bFalse, bFalse, bFalse)
    Debug.Print "P6-Model.InsertRefPlane: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' P7: InsertRefPlaneRegen
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear: Set swFeat = Nothing
    Set swFeat = swFeatMgr.InsertRefPlaneRegen(8, 0.01, bFalse, bFalse, bFalse, bFalse)
    Debug.Print "P7-InsertRefPlaneRegen: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    On Error GoTo ErrHandler

    ' 最终检查
    Debug.Print "最终特征数: " & swModel.GetFeatureCount
    ' 遍历检查是否有新特征
    Dim i As Long, fName As String
    For i = 1 To swModel.GetFeatureCount
        fName = swModel.FeatureByPositionReverse(i).Name
        If Left(fName, 5) = "Plane" Then Debug.Print "  发现: " & fName
    Next i

    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
