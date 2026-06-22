Option Explicit

' KeywayCut.bas — 键槽切除宏
' 使用相切参考面 + 拉伸切除的正确 CAD 建模方式
' 由 ShaftBuilder 自动生成

Sub main()
    Dim swApp As Object
    Dim swModel As Object
    Dim swFeatMgr As Object
    Dim swSketchMgr As Object
    Dim swFeat As Object
    Dim x1 As Double, x2 As Double, y As Double
    Dim hw As Double, zNeg As Double, zPos As Double
    Dim depthM As Double

    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        MsgBox "No active document!", vbCritical
        Exit Sub
    End If
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager

    ' ============================================
    ' Keyway 1: Xc=-196.27, L=40, W=10, D=5, R=16
    ' ============================================

    ' --- Step 1: 创建相切参考面（从上视基准面偏移 shaft_radius）---
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.016#, 0, 0, 0, 0)
    If swFeat Is Nothing Then
        MsgBox "Failed to create reference plane for Keyway 1!", vbCritical
        Exit Sub
    End If
    swFeat.Name = "KeywayPlane-1"

    ' --- Step 2: 在参考面上绘制键槽轮廓 ---
    ' 参考面位于 Y=shaft_r，平行于 XZ 平面
    ' 键槽轮廓：矩形 （x1~x2）×（zNeg~zPos）
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "KeywayPlane-1", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    swModel.InsertSketch2 True

    x1 = -216.266#
    x2 = -176.266#
    y = 16.0#
    hw = 5.0#
    zNeg = -hw
    zPos = hw

    ' 矩形轮廓（逆时针闭合）
    swSketchMgr.CreateLine x1, y, zNeg, x2, y, zNeg  ' P1→P2 底边
    swSketchMgr.CreateLine x2, y, zNeg, x2, y, zPos  ' P2→P3 右边
    swSketchMgr.CreateLine x2, y, zPos, x1, y, zPos  ' P3→P4 顶边
    swSketchMgr.CreateLine x1, y, zPos, x1, y, zNeg  ' P4→P1 左边

    ' --- Step 3: 拉伸切除（向轴心方向 -Y，Flip=True）---
    depthM = 0.005#
    ' FeatureCut3(Sd=True,Flip=True 翻转向-Y切除,Dir=False,T1Both=False,T1=0=Blind,D1=depth,...)
    Set swFeat = swFeatMgr.FeatureCut3( True, True, False, False, 0, depthM, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True )
    If swFeat Is Nothing Then
        MsgBox "FeatureCut3 failed for Keyway 1!", vbCritical
        Exit Sub
    End If
    swFeat.Name = "Keyway-1"

    ' ============================================
    ' Keyway 2: Xc=129.73, L=38, W=12, D=6, R=22
    ' ============================================

    ' --- Step 1: 创建相切参考面（从上视基准面偏移 shaft_radius）---
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.0215#, 0, 0, 0, 0)
    If swFeat Is Nothing Then
        MsgBox "Failed to create reference plane for Keyway 2!", vbCritical
        Exit Sub
    End If
    swFeat.Name = "KeywayPlane-2"

    ' --- Step 2: 在参考面上绘制键槽轮廓 ---
    ' 参考面位于 Y=shaft_r，平行于 XZ 平面
    ' 键槽轮廓：矩形 （x1~x2）×（zNeg~zPos）
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "KeywayPlane-2", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    swModel.InsertSketch2 True

    x1 = 110.734#
    x2 = 148.734#
    y = 21.5#
    hw = 6.0#
    zNeg = -hw
    zPos = hw

    ' 矩形轮廓（逆时针闭合）
    swSketchMgr.CreateLine x1, y, zNeg, x2, y, zNeg  ' P1→P2 底边
    swSketchMgr.CreateLine x2, y, zNeg, x2, y, zPos  ' P2→P3 右边
    swSketchMgr.CreateLine x2, y, zPos, x1, y, zPos  ' P3→P4 顶边
    swSketchMgr.CreateLine x1, y, zPos, x1, y, zNeg  ' P4→P1 左边

    ' --- Step 3: 拉伸切除（向轴心方向 -Y，Flip=True）---
    depthM = 0.006#
    ' FeatureCut3(Sd=True,Flip=True 翻转向-Y切除,Dir=False,T1Both=False,T1=0=Blind,D1=depth,...)
    Set swFeat = swFeatMgr.FeatureCut3( True, True, False, False, 0, depthM, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True )
    If swFeat Is Nothing Then
        MsgBox "FeatureCut3 failed for Keyway 2!", vbCritical
        Exit Sub
    End If
    swFeat.Name = "Keyway-2"

    ' --- 完成（成功时不弹窗，避免阻塞自动化）---
    swModel.ForceRebuild3 False
    swModel.ViewZoomtofit2
    swModel.SetStatusBarText "KeywayCut: 2 keyway(s) created"
End Sub
