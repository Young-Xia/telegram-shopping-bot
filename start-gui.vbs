Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("Wscript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
splashPs1 = root & "\gui-splash.ps1"
logDir = root & "\logs"
loadingFile = logDir & "\.gui-loading"
readyFile = logDir & "\.gui-ready"

shell.CurrentDirectory = root

If Not fso.FileExists(pythonw) Then
  MsgBox "Please run bootstrap-gui.cmd first to install dependencies.", vbExclamation, "Telegram Shopping Bot"
  WScript.Quit 1
End If

If Not fso.FolderExists(logDir) Then
  fso.CreateFolder(logDir)
End If

If fso.FileExists(readyFile) Then
  fso.DeleteFile readyFile, True
End If

Set marker = fso.CreateTextFile(loadingFile, True)
marker.Write "1"
marker.Close

If fso.FileExists(splashPs1) Then
  shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & splashPs1 & """ """ & root & """", 0, False
End If

shell.Environment("Process")("PYTHONPATH") = root & "\src"
shell.Environment("Process")("PYTHONDONTWRITEBYTECODE") = "1"
shell.Run """" & pythonw & """ -m shopping_bot.gui", 0, False
