Set shell = CreateObject("WScript.Shell")
folder = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
shell.Run """" & folder & ".venv\Scripts\pythonw.exe"" """ & folder & "main.py""", 0, False
