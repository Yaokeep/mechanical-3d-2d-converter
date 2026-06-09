Option Explicit

' VerifySW2025 v30 - 完全按官方文档模式: SelectByID2(...,True,...) + 检查返回值
' 关键: 用 Append=True, 检查SelectByID2返回值

Dim swApp As Object, swModel As Object
Dim swFeatMgr As Object, swRefPlane As Object
Dim boolstatus As Boolean, featCountBefore As Long

Sub main()
    On Error GoTo ErrHandler

    Set swApp = Application.SldWorks: swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
    Set swFeatMgr = swModel.FeatureManager

    Debug.Print "=== 官方文档模式 InsertRefPlane ==="
    featCountBefore = swModel.GetFeatureCount
    Debug.Print "创建前特征数: " & featCountBefore

    ' ====== 方式1: 完全按官方文档 (Append=True) ======
    swModel.ClearSelection2 True
    boolstatus = swModel.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0)
    Debug.Print "P1-选Front: " & boolstatus

    If boolstatus = False Then
        Debug.Print "  P1失败: SelectByID2返回False"
    Else
        On Error Resume Next
        Set swRefPlane = Nothing
        Set swRefPlane = swFeatMgr.InsertRefPlane(8, 0.05, 0, 0, 0, 0)
        Debug.Print "P1-InsertRefPlane(8,0.05,0,0,0,0): " & IIf(swRefPlane Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        Debug.Print "  特征数: " & featCountBefore & "->" & swModel.GetFeatureCount
        On Error GoTo ErrHandler
    End If

    ' ====== 方式2: Top Plane + Flip=1 ======
    If swRefPlane Is Nothing Then
        featCountBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        boolstatus = swModel.Extension.SelectByID2("Top Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0)
        Debug.Print "P2-选Top: " & boolstatus

        If boolstatus Then
            On Error Resume Next
            Set swRefPlane = Nothing
            Set swRefPlane = swFeatMgr.InsertRefPlane(8, 0.05, 0, 1, 0, 0)
            Debug.Print "P2-InsertRefPlane(Flip=1): " & IIf(swRefPlane Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
            Debug.Print "  特征数: " & featCountBefore & "->" & swModel.GetFeatureCount
            On Error GoTo ErrHandler
        End If
    End If

    ' ====== 方式3: Angle plane (验证InsertRefPlane是否能工作) ======
    If swRefPlane Is Nothing Then
        featCountBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        ' 选Front Plane
        boolstatus = swModel.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0)
        Debug.Print "P3-选Front(第1选): " & boolstatus
        ' 再选Top Plane作为参考
        If boolstatus Then
            boolstatus = swModel.Extension.SelectByID2("Top Plane", "PLANE", 0, 0, 0, True, 1, Nothing, 0)
            Debug.Print "P3-选Top(第2选): " & boolstatus
            On Error Resume Next
            Set swRefPlane = Nothing
            ' 16=Angle, 0.785=45度
            Set swRefPlane = swFeatMgr.InsertRefPlane(16, 0.785, 0, 0, 0, 0)
            Debug.Print "P3-InsertRefPlane(Angle,16): " & IIf(swRefPlane Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
            Debug.Print "  特征数: " & featCountBefore & "->" & swModel.GetFeatureCount
            On Error GoTo ErrHandler
        End If
    End If

    ' ====== 方式4: FeatureRefPlane ======
    If swRefPlane Is Nothing Then
        featCountBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        boolstatus = swModel.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0)
        Debug.Print "P4-选Front: " & boolstatus
        If boolstatus Then
            On Error Resume Next
            Set swRefPlane = Nothing
            Set swRefPlane = swFeatMgr.FeatureRefPlane(8, 0.05, 0, 0, 0, 0)
            Debug.Print "P4-FeatureRefPlane: " & IIf(swRefPlane Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
            Debug.Print "  特征数: " & featCountBefore & "->" & swModel.GetFeatureCount
            On Error GoTo ErrHandler
        End If
    End If

    ' ====== 方式5: swModel.CreatePlaneAtOffset3 + Append=True ======
    If swRefPlane Is Nothing Then
        featCountBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        boolstatus = swModel.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0)
        Debug.Print "P5-选Front: " & boolstatus
        If boolstatus Then
            On Error Resume Next
            Set swRefPlane = Nothing
            Set swRefPlane = swModel.CreatePlaneAtOffset3(0.05, False, True)
            Debug.Print "P5-CreatePlaneAtOffset3: " & IIf(swRefPlane Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
            Debug.Print "  特征数: " & featCountBefore & "->" & swModel.GetFeatureCount
            On Error GoTo ErrHandler
        End If
    End If

    Debug.Print vbCrLf & "最终特征数: " & swModel.GetFeatureCount
    If Not swRefPlane Is Nothing Then
        Debug.Print "成功! 平面名: " & swRefPlane.Name
    Else
        Debug.Print "[FAIL] 所有方式均无法创建基准面"
    End If

    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
