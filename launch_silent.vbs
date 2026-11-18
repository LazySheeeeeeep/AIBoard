' Silent launcher for AI BOARD (supports --autostart argument & cross-machine Python/EXE lookup)
Option Explicit

Dim fso, shell, procEnv, baseDir, appScript, exeDirect, exeDist, extraArgs, argItem
Dim candidates, candRoot, pywPath, libBin, cmd, foundPyw
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = baseDir

extraArgs = ""
If WScript.Arguments.Count > 0 Then
    For Each argItem In WScript.Arguments
        extraArgs = extraArgs & " " & argItem
    Next
End If

' 1. Prefer standalone packaged EXE if built
exeDirect = fso.BuildPath(baseDir, "AIBoard.exe")
exeDist = fso.BuildPath(baseDir, "dist\AIBoard\AIBoard.exe")
If fso.FileExists(exeDirect) Then
    shell.Run """" & exeDirect & """" & extraArgs, 0, False
    WScript.Quit 0
ElseIf fso.FileExists(exeDist) Then
    shell.Run """" & exeDist & """" & extraArgs, 0, False
    WScript.Quit 0
End If

' 2. Fallback to local Python / Conda environment
appScript = fso.BuildPath(baseDir, "app.py")
Set procEnv = shell.Environment("PROCESS")

candidates = Array( _
    "C:\ProgramData\Anaconda3", _
    shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\anaconda3", _
    shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\miniconda3", _
    shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python311", _
    shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python310" _
)

foundPyw = ""
For Each candRoot In candidates
    pywPath = fso.BuildPath(candRoot, "pythonw.exe")
    If fso.FileExists(pywPath) Then
        foundPyw = pywPath
        libBin = fso.BuildPath(candRoot, "Library\bin")
        If fso.FolderExists(libBin) Then
            procEnv("PATH") = libBin & ";" & procEnv("PATH")
        End If
        Exit For
    End If
Next

If foundPyw <> "" Then
    cmd = """" & foundPyw & """ """ & appScript & """" & extraArgs
Else
    cmd = "pythonw """ & appScript & """" & extraArgs
End If

shell.Run cmd, 0, False
