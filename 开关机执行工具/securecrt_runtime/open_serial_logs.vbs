#$language = "VBScript"
#$interface = "1.0"

Option Explicit

Sub Main
    If crt.Arguments.Count < 1 Then
        crt.Dialog.MessageBox "Missing serial target manifest.", "Serial Logging"
        Exit Sub
    End If

    Dim fso, manifestFile, line, fields, sessionName, sessionConfig, tab, errors
    Set fso = CreateObject("Scripting.FileSystemObject")
    Set manifestFile = fso.OpenTextFile(crt.Arguments.GetArg(0), 1, False, -1)
    errors = ""

    Do Until manifestFile.AtEndOfStream
        line = manifestFile.ReadLine
        If Len(Trim(line)) > 0 Then
            fields = Split(line, vbTab)
            If UBound(fields) >= 6 Then
                sessionName = fields(0)

                On Error Resume Next
                Err.Clear
                Set sessionConfig = crt.OpenSessionConfiguration("Default_Serial")
                sessionConfig.SetOption "Protocol Name", "Serial"
                sessionConfig.SetOption "Com Port", fields(1)
                sessionConfig.SetOption "Baud Rate", CLng(fields(3))
                sessionConfig.SetOption "Data Bits", CInt(fields(4))
                sessionConfig.SetOption "Parity", 0
                sessionConfig.SetOption "Stop Bits", CInt(fields(6))
                sessionConfig.SetOption "CTS Flow", False
                sessionConfig.SetOption "DSR Flow", False
                sessionConfig.SetOption "XON Flow", False
                sessionConfig.SetOption "Log Filename V2", fields(2)
                sessionConfig.SetOption "Custom Log Message Each Line", "[%Y-%M-%D %h:%m:%s] "
                sessionConfig.SetOption "Log Timestamp Each Line", False
                sessionConfig.SetOption "Log Mode", 1
                sessionConfig.SetOption "Start Log Upon Connect", True
                sessionConfig.SetOption "New Log File At Midnight", True
                sessionConfig.Save sessionName

                Err.Clear
                Set tab = crt.Session.ConnectInTab("/S " & Chr(34) & sessionName & Chr(34), True, True)
                If Err.Number <> 0 Then
                    errors = errors & fields(0) & " (" & fields(1) & "): " & Err.Description & vbCrLf
                ElseIf Not tab.Session.Connected Then
                    errors = errors & fields(0) & " (" & fields(1) & "): connection failed" & vbCrLf
                Else
                    tab.Session.SetStatusText fields(0) & " / " & fields(1) & " / logging"
                End If
                On Error GoTo 0
            End If
        End If
    Loop
    manifestFile.Close

    If Len(errors) > 0 Then
        crt.Dialog.MessageBox "Some serial connections failed:" & vbCrLf & vbCrLf & errors, "Serial Logging"
    End If
End Sub
