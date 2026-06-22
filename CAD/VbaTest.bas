Option Explicit
Sub main()
    Dim swApp As Object, swModel As Object
    Dim swFeatMgr As Object, swSketchMgr As Object
    Dim swFeat As Object, fso As Object, f As Object
    Dim result As String
    
    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        Set fso = CreateObject("Scripting.FileSystemObject")
        Set f = fso.CreateTextFile("C:\Users\yaoshuo\AppData\Local\Temp\sw_vba_test_result.txt", True)
        f.WriteLine "ERR:NoActiveDoc"
        f.Close
        Exit Sub
    End If
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    
    ' Test 1: SelectEdge
    On Error Resume Next
    Err.Clear
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "Edge", -0.233, 0.016, 0.001, True, 0, Nothing, 0
    If Err.Number <> 0 Then : result = result & "1.SelectEdge: ERR " & Err.Description & vbCrLf : Else : result = result & "1.SelectEdge: OK (" & swModel.SelectionManager.GetSelectedObjectCount2(-1) & " edges)" & vbCrLf : End If
    On Error GoTo 0
    
    ' Test 2: Chamfer
    On Error Resume Next
    Err.Clear
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.0012, 0, 0, 0, False)
    If Err.Number <> 0 Then
        result = result & "2.Chamfer: ERR " & Err.Description & vbCrLf
    ElseIf swFeat Is Nothing Then
        result = result & "2.Chamfer: Nothing" & vbCrLf
    Else
        result = result & "2.Chamfer: OK" & vbCrLf
    End If
    On Error GoTo 0
    
    ' Test 3: Fillet3
    On Error Resume Next
    Err.Clear
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "Edge", -0.158, 0.0185, 0.001, True, 0, Nothing, 0
    swModel.Extension.SelectByID2 "", "Edge", -0.108, 0.02, 0.001, True, 1, Nothing, 0
    Set swFeat = swFeatMgr.FeatureFillet3(195, 0.0012, 0, 0, False, 0, False, False)
    If Err.Number <> 0 Then
        result = result & "3.Fillet3: ERR " & Err.Description & vbCrLf
    ElseIf swFeat Is Nothing Then
        result = result & "3.Fillet3: Nothing" & vbCrLf
    Else
        result = result & "3.Fillet3: OK" & vbCrLf
    End If
    On Error GoTo 0
    
    ' Test 4: InsertRefPlane
    swModel.ClearSelection2 True
    On Error Resume Next : Err.Clear
    swModel.Extension.SelectByID2 ChrW(19978)&ChrW(35270)&ChrW(22522)&ChrW(20934)&ChrW(38754), "PLANE", 0, 0, 0, True, 0, Nothing, 0
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.016, 0, 0, 0, 0)
    If Err.Number <> 0 Then
        result = result & "4.RefPlane: ERR " & Err.Description & vbCrLf
    ElseIf swFeat Is Nothing Then
        result = result & "4.RefPlane: Nothing" & vbCrLf
    Else
        swFeat.Name = "Test-Plane"
        result = result & "4.RefPlane: OK" & vbCrLf
    End If
    On Error GoTo 0
    
    ' Test 5: Sketch on ref plane
    swModel.ClearSelection2 True
    On Error Resume Next : Err.Clear
    swModel.Extension.SelectByID2 "Test-Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    swModel.InsertSketch2 True
    If Err.Number <> 0 Then
        result = result & "5.SketchSelect: ERR " & Err.Description & vbCrLf
    End If
    swSketchMgr.CreateLine -0.216, 0.016, -0.005, -0.176, 0.016, -0.005
    If Err.Number <> 0 Then
        result = result & "5.CreateLine: ERR " & Err.Description & vbCrLf
    Else
        result = result & "5.CreateLine: OK" & vbCrLf
    End If
    On Error GoTo 0
    
    ' Test 6: FeatureCut3
    On Error Resume Next
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3( True, True, False, False, 0, 0.005, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True )
    If Err.Number <> 0 Then
        result = result & "6.FeatureCut3: ERR " & Err.Description & vbCrLf
    ElseIf swFeat Is Nothing Then
        result = result & "6.FeatureCut3: Nothing" & vbCrLf
    Else
        result = result & "6.FeatureCut3: OK" & vbCrLf
    End If
    On Error GoTo 0
    
    ' Test 7: FeatureCut4
    On Error Resume Next
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut4( 0, True, True, False, False, 0, 0.005, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True )
    If Err.Number <> 0 Then
        result = result & "7.FeatureCut4: ERR " & Err.Description & vbCrLf
    ElseIf swFeat Is Nothing Then
        result = result & "7.FeatureCut4: Nothing" & vbCrLf
    Else
        result = result & "7.FeatureCut4: OK" & vbCrLf
    End If
    On Error GoTo 0
    
    ' Test 8: FeatureCut5
    On Error Resume Next
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut5( 0, True, True, False, False, 0, 0.005, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True, False, False )
    If Err.Number <> 0 Then
        result = result & "8.FeatureCut5: ERR " & Err.Description & vbCrLf
    ElseIf swFeat Is Nothing Then
        result = result & "8.FeatureCut5: Nothing" & vbCrLf
    Else
        result = result & "8.FeatureCut5: OK" & vbCrLf
    End If
    On Error GoTo 0
    
    ' Test 9: Extrusion2
    On Error Resume Next
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2( True, False, False, 0, 0, 0.005, 0.005, False, False, False, False, 0.005, 0.005, True, True, 0, 0, False, False, 0, True, True, True )
    If Err.Number <> 0 Then
        result = result & "9.Extrusion2: ERR " & Err.Description & vbCrLf
    ElseIf swFeat Is Nothing Then
        result = result & "9.Extrusion2: Nothing" & vbCrLf
    Else
        result = result & "9.Extrusion2: OK" & vbCrLf
    End If
    On Error GoTo 0
    
    ' Write results to temp file
    Set fso = CreateObject("Scripting.FileSystemObject")
    Set f = fso.CreateTextFile("C:\Users\yaoshuo\AppData\Local\Temp\sw_vba_test_result.txt", True)
    f.WriteLine result
    f.Close
    swModel.SetStatusBarText "VBA Test done: " & result
End Sub