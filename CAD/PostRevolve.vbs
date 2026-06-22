On Error Resume Next
Dim swApp
Set swApp = GetObject(, "SldWorks.Application")
If Err.Number <> 0 Then
    WScript.Echo "ERR: Cannot connect to SW"
    WScript.Quit 1
End If
swApp.RunMacro "E:\项目\机械三维二维图互转\CAD\PostRevolve.bas", "main", 0
If Err.Number <> 0 Then
    WScript.Echo "ERR: " & Err.Description
    WScript.Quit 1
End If
WScript.Echo "OK"
