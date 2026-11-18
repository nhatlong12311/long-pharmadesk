' Mo Pharma Desk bang Python da cai (nhanh nhu Mo_phan_mem.bat) nhung KHONG hien cua so den.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "pyw -3 start_pharmadesk.py", 0, False
