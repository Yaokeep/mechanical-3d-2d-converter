Option Explicit
Sub main()
    Dim swApp As Object
    Set swApp = Application.SldWorks
    swApp.SendMsgToUser2 "VBA test OK!", 0, 0
End Sub
