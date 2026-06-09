Option Explicit

' VerifySW2025 v19 - FeatureCut 参数个数精确排查 + 确保草图退出
' v18: Cut3(26参) OK+Err=13 但切除未执行(草图还开着)

Dim swApp As Object, swModel As Object
Dim swFeatMgr As Object, swSketchMgr As Object
Dim swFeat As Object, swSelMgr As Object

Sub makeSketchAndTryCut(methodName As String, paramCount As Long)
    ' 退出之前可能残留的草图
    On Error Resume Next
    swModel.InsertSketch2 True
    swModel.ClearSelection2 True

    ' 选择 Top Plane 并插入新草图
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 15, 0, -5, 35, 0, -5
    swSketchMgr.CreateLine 35, 0, -5, 35, 0, 5
    swSketchMgr.CreateLine 35, 0, 5, 15, 0, 5
    swSketchMgr.CreateLine 15, 0, 5, 15, 0, -5

    Err.Clear

    ' 根据方法名和参数个数调用
    Select Case methodName
        Case "FeatureCut"
            Select Case paramCount
                Case 18:
                    Set swFeat = swFeatMgr.FeatureCut(True, False, False, False, 0, 0.005, 0.005, _
                        False, False, False, False, 0#, 0#, False, False, False, False)
                Case 20:
                    Set swFeat = swFeatMgr.FeatureCut(True, False, False, False, 0, 0.005, 0.005, _
                        False, False, False, False, 0#, 0#, False, False, False, False, False, False)
                Case 22:
                    Set swFeat = swFeatMgr.FeatureCut(True, False, False, False, 0, 0.005, 0.005, _
                        False, False, False, False, 0#, 0#, False, False, False, False, _
                        False, False, False, False)
            End Select
        Case "FeatureCut3"
            Select Case paramCount
                Case 28:
                    Set swFeat = swFeatMgr.FeatureCut3( _
                        True, False, False, _
                        False, 0, 0.005, _
                        False, 0, 0.005, _
                        False, False, 0#, _
                        False, False, 0#, _
                        False, 0#, _
                        False, 0#, _
                        False, 0#, _
                        False, 0#, _
                        False, False, Nothing, False, False, False)
                Case 30:
                    Set swFeat = swFeatMgr.FeatureCut3( _
                        True, False, False, _
                        False, 0, 0.005, _
                        False, 0, 0.005, _
                        False, False, 0#, _
                        False, False, 0#, _
                        False, 0#, _
                        False, 0#, _
                        False, 0#, _
                        False, 0#, _
                        False, False, Nothing, False, False, False, False, False)
            End Select
    End Select

    Debug.Print methodName & "(" & paramCount & "): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' 确保退出草图
    If Err.Number <> 0 Or swFeat Is Nothing Then
        swModel.InsertSketch2 True
    End If
End Sub

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks: swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    Set swSelMgr = swModel.SelectionManager

    ' 创建旋转体
    Debug.Print "=== 创建旋转体 ==="
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
    swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
    swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
    swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, _
        0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "旋转体: " & IIf(swFeat Is Nothing, "FAIL", "PASS")
    If swFeat Is Nothing Then MsgBox "旋转失败", vbCritical: Exit Sub

    ' 先退出旋转体的草图
    swModel.InsertSketch2 True

    ' ====== Test7: FeatureCut 参数个数排查 ======
    Debug.Print vbCrLf & "=== Test7: FeatureCut 参数排查 ==="

    On Error Resume Next

    makeSketchAndTryCut "FeatureCut", 18
    makeSketchAndTryCut "FeatureCut", 20
    makeSketchAndTryCut "FeatureCut", 22
    makeSketchAndTryCut "FeatureCut3", 28
    makeSketchAndTryCut "FeatureCut3", 30

    On Error GoTo ErrHandler

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    swModel.InsertSketch2 True
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
