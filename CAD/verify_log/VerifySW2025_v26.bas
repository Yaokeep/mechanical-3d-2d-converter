Option Explicit

' VerifySW2025 v26 - Boolean替代Integer, IModelDoc2方法, 纯平面创建测试
' InsertRefPlane 全部Err=0但不创建 → 试试用Boolean参数 + 不同方法名

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
    Set swSelMgr = swModel.SelectionManager
    Set swSketchMgr = swModel.SketchManager

    ' 不做旋转体 — 在空零件上纯测试平面创建
    Debug.Print "=== 纯平面创建测试 ==="
    Debug.Print "  初始特征数: " & swModel.GetFeatureCount

    ' ----- 测试1: InsertRefPlane with Boolean -----
    On Error Resume Next
    Dim bFalse As Boolean: bFalse = False
    Dim bTrue As Boolean: bTrue = True

    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "  选Front: " & swSelMgr.GetSelectedObjectCount2(-1)

    Err.Clear: Set swFeat = Nothing
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, bFalse, bFalse, bFalse, bFalse)
    Debug.Print "T1-InsertRefPlane(8,0.01,False*4): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    Debug.Print "  特征数: " & swModel.GetFeatureCount

    ' ----- 测试2: InsertRefPlane2 (如果存在) -----
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear: Set swFeat = Nothing
    Set swFeat = swFeatMgr.InsertRefPlane2(8, 0.01, bFalse, bFalse, bFalse, bFalse)
    Debug.Print "T2-InsertRefPlane2: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    Debug.Print "  特征数: " & swModel.GetFeatureCount

    ' ----- 测试3: swModel.InsertRefPlane (IModelDoc2方法) -----
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear: Set swFeat = Nothing
    Set swFeat = swModel.InsertRefPlane(8, 0.01, bFalse, bFalse, bFalse, bFalse)
    Debug.Print "T3-Model.InsertRefPlane: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    Debug.Print "  特征数: " & swModel.GetFeatureCount

    ' ----- 测试4: 用 AddPlane 或类似的 -----
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear: Set swFeat = Nothing
    Set swFeat = swModel.CreatePlaneAtOffset3(0.01, bFalse, bTrue)
    Debug.Print "T4-CreatePlaneAtOffset3: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    Debug.Print "  特征数: " & swModel.GetFeatureCount

    ' ----- 测试5: RefPlaneMidSurface? -----
    Err.Clear: Set swFeat = Nothing
    Set swFeat = swFeatMgr.InsertRefPlane2(2, 0#, 0#, 0#, 0#, 0#)
    Debug.Print "T5-InsertRefPlane2(6,平行于屏幕): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' ----- 测试6: InsertRefPlane3 (更多参数) -----
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear: Set swFeat = Nothing
    Set swFeat = swFeatMgr.InsertRefPlane3(8, 0.01, bFalse, bFalse, bFalse, bFalse, bFalse)
    Debug.Print "T6-InsertRefPlane3(7): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' ----- 测试7: FeatureRefPlane Boolean -----
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear: Set swFeat = Nothing
    Set swFeat = swFeatMgr.FeatureRefPlane(8, 0.01, bFalse, bFalse, bFalse, bFalse)
    Debug.Print "T7-FeatureRefPlane(Bool): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' ----- 测试8: swModel.RefPlane -----
    Err.Clear: Set swFeat = Nothing
    Set swFeat = swModel.RefPlane(8, 0.01, bFalse, bFalse, bFalse, bFalse)
    Debug.Print "T8-Model.RefPlane: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    On Error GoTo ErrHandler
    Debug.Print "最终特征数: " & swModel.GetFeatureCount

    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
