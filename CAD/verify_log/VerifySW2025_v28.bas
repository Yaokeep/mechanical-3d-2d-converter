Option Explicit

' VerifySW2025 v28 - GetSelectedObjectCount2(-1)始终返回0可能是根源!
' 试验: SelectionManager.SelectByID2 + GetSelectedObjectCount(无2)

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

    ' ====== 测试: Extension vs SelectionMgr 的选择方法 ======
    Debug.Print "=== 选择方法测试 ==="
    On Error Resume Next

    ' T1: Extension.SelectByID2 + Extension.GetSelectedObjectCount
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "T1a-Ext.SelectByID2: Err=" & Err.Number
    Err.Clear
    Debug.Print "T1b-Ext.GetSelectedCount: " & swModel.Extension.GetSelectedObjectCount
    Debug.Print "T1c-SelMgr.GetCount2(-1): " & swSelMgr.GetSelectedObjectCount2(-1)

    ' T2: SelectionMgr.SelectByID2 + SelectionMgr.GetSelectedObjectCount
    swModel.ClearSelection2 True
    Err.Clear
    swSelMgr.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "T2a-SelMgr.SelectByID2: Err=" & Err.Number
    Err.Clear
    Debug.Print "T2b-SelMgr.GetSelCount: " & swSelMgr.GetSelectedObjectCount

    ' T3: Extension.SelectByID2 无最后一个参数
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing
    Debug.Print "T3-SelectByID2(10参): Err=" & Err.Number

    ' T4: Extension.SelectByID + SelectionMgr.GetSelectedObjectCount
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID "Front Plane", "PLANE", 0, 0, 0
    Debug.Print "T4-SelectByID(无2): Err=" & Err.Number

    ' ====== 旋转体 ======
    Debug.Print vbCrLf & "=== 旋转体 ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
    swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
    swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
    swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0
    Set swFeat = Nothing
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, _
        0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  旋转体: " & IIf(swFeat Is Nothing, "FAIL", "PASS")

    ' ====== 用不同的选择方式 + InsertRefPlane ======
    Debug.Print vbCrLf & "=== InsertRefPlane ==="
    Dim featBefore As Long

    ' P1: SelectionMgr.SelectByID2 选择 + InsertRefPlane
    featBefore = swModel.GetFeatureCount
    swModel.ClearSelection2 True
    swSelMgr.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "P1-SelMgr选Top: Err=" & Err.Number
    Err.Clear: Set swFeat = Nothing
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, False, False, False, False)
    Debug.Print "P1-RefPlane: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    Debug.Print "P1-特征数: " & featBefore & "→" & swModel.GetFeatureCount

    ' P2: 用 swSelMgr.EnableContourSelection 之后
    If featBefore = swModel.GetFeatureCount Then
        featBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        swSelMgr.EnableContourSelection = False
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, True, 1, Nothing, 0
        Err.Clear: Set swFeat = Nothing
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, False, False, False, False)
        Debug.Print "P2-EnableContour: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        Debug.Print "P2-特征数: " & featBefore & "→" & swModel.GetFeatureCount
    End If

    ' P3: 用 ISelectionMgr::AddSelectionListObjects
    If featBefore = swModel.GetFeatureCount Then
        featBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        Dim objs(0) As Object
        Set objs(0) = swModel.FeatureByName("Top Plane")
        If Not objs(0) Is Nothing Then
            swSelMgr.AddSelectionListObjects objs, Nothing, 0
            Debug.Print "P3-AddSelectionList: 选Top=" & swSelMgr.GetSelectedObjectCount2(-1)
            Err.Clear: Set swFeat = Nothing
            Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, False, False, False, False)
            Debug.Print "P3-RefPlane: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
            Debug.Print "P3-特征数: " & featBefore & "→" & swModel.GetFeatureCount
        Else
            Debug.Print "P3: FeatureByName(Top Plane) = Nothing"
        End If
    End If

    ' P4: 通过 IModelDoc2 调用 (不是 FeatureManager)
    If featBefore = swModel.GetFeatureCount Then
        featBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Err.Clear: Set swFeat = Nothing
        Set swFeat = swModel.InsertRefPlane(8, 0.01, False, False, False, False, False)
        Debug.Print "P4-Model.InsertRefPlane(7): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        Debug.Print "P4-特征数: " & featBefore & "→" & swModel.GetFeatureCount
    End If

    ' P5: 检查 swRefPlaneFeatureData
    If featBefore = swModel.GetFeatureCount Then
        Debug.Print "P5-所有方法均失败, 跳过"
    End If

    On Error GoTo ErrHandler
    Debug.Print "最终特征数: " & swModel.GetFeatureCount

    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
