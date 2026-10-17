Attribute VB_Name = "BacktestRunner"
Option Explicit

Private Function ProjectRoot() As String
    Dim candidate As String
    Dim slash As Long
    candidate = ThisWorkbook.Path
    Do While Len(candidate) > 1
        If Len(Dir$(candidate & "/shared_execution_engine/excel_runner.py")) > 0 Then
            ProjectRoot = candidate
            Exit Function
        End If
        slash = InStrRev(candidate, "/")
        If slash < 2 Then Exit Do
        candidate = Left$(candidate, slash - 1)
    Loop
    Err.Raise vbObjectError + 1002, "BacktestRunner", _
        "Keep this workbook inside the release folder with shared_execution_engine."
End Function

Public Sub Setup_Backtest_Runner()
    Dim ws As Worksheet
    Set ws = GetOrCreateSheet("Runner")

    ws.Cells.Clear
    DeleteRunnerButtons ws

    ws.Range("A1").Value = "GBP/USD Backtest Runner"
    ws.Range("A3").Value = "Selected window and sample are read from the Config sheet."
    ws.Range("A4").Value = "Dry run checks the engine without writing. Run backtest creates a timestamped output workbook."
    ws.Range("A6").Value = "Last run log"
    ws.Range("B6").Value = ""
    ws.Range("A7").Value = "Last output workbook"
    ws.Range("B7").Value = ""

    ws.Range("A1").Font.Bold = True
    ws.Range("A1").Font.Size = 16
    ws.Range("A3:A7").Font.Size = 11
    ws.Columns("A:B").ColumnWidth = 36
    ws.Range("B6:B7").ColumnWidth = 95

    AddRunnerButton ws, "Dry Run Backtest", "Dry_Run_Backtest", 20, 120
    AddRunnerButton ws, "Run Backtest", "Run_Backtest_Write", 190, 120
End Sub

Public Sub Dry_Run_Backtest()
    RunBacktest "dry-run"
End Sub

Public Sub Run_Backtest_Write()
    RunBacktest "write"
End Sub

Private Sub RunBacktest(ByVal mode As String)
    On Error GoTo Fail

    Dim root As String, engineDir As String, runnerScript As String
    Dim pythonBin As String, outputRoot As String, logRoot As String
    root = ProjectRoot()
    engineDir = root & "/shared_execution_engine"
    runnerScript = engineDir & "/excel_runner.py"
    pythonBin = root & "/.venv/bin/python3"
    outputRoot = root & "/excel_runner_runs"
    logRoot = root & "/excel_runner_logs"
    If Len(Dir$(pythonBin)) = 0 Then
        Err.Raise vbObjectError + 1003, "BacktestRunner", _
            "Python is not installed for this copy. Run excel_runner/setup_python_macos.sh first."
    End If
    ThisWorkbook.Save

    Dim stamp As String
    stamp = Format(Now, "yyyymmdd_hhnnss")

    Dim logPath As String
    logPath = logRoot & "/backtest_" & mode & "_" & stamp & ".log"

    Dim outputPath As String
    outputPath = outputRoot & "/" & RunnerOutputStem(ThisWorkbook.Name) & "_run_" & stamp & ".xlsm"

    Dim command As String
    command = "mkdir -p " & ShellQuote(logRoot) & " " & ShellQuote(outputRoot)
    command = command & " && echo " & ShellQuote("Excel shell reached runner at " & stamp) & " > " & ShellQuote(logPath)
    command = command & " && cd " & ShellQuote(engineDir)
    command = command & " && " & ShellQuote(pythonBin) & " " & ShellQuote(runnerScript)
    command = command & " --workbook " & ShellQuote(ThisWorkbook.FullName)
    command = command & " --mode " & ShellQuote(mode)
    command = command & " --project-root " & ShellQuote(root)
    command = command & " --output-root " & ShellQuote(outputRoot)
    If mode = "write" Then
        command = command & " --output-workbook " & ShellQuote(outputPath)
    End If
    command = command & " >> " & ShellQuote(logPath) & " 2>&1"
    command = command & "; status=$?; echo EXIT_CODE=$status >> " & ShellQuote(logPath)
    command = command & "; printf ""%s"" $status"

    SetLastRunCells logPath, IIf(mode = "write", outputPath, "")

    Dim exitCode As String
    exitCode = Trim(RunShell(command))

    If exitCode <> "0" Then
        OpenPath logPath
        MsgBox "Backtest failed. The log file has been opened:" & vbCrLf & logPath, vbCritical, "Backtest Runner"
        Exit Sub
    End If

    If mode = "write" Then
        If TryOpenWorkbook(outputPath) Then
            MsgBox "Backtest complete. Output workbook opened:" & vbCrLf & outputPath, vbInformation, "Backtest Runner"
        Else
            OpenPath outputPath
            MsgBox "Backtest complete, but Excel could not open the output workbook automatically:" & vbCrLf & outputPath, vbExclamation, "Backtest Runner"
        End If
    Else
        MsgBox "Dry run complete. Log file:" & vbCrLf & logPath, vbInformation, "Backtest Runner"
    End If
    Exit Sub

Fail:
    MsgBox "Backtest runner error: " & Err.Description, vbCritical, "Backtest Runner"
End Sub

Private Function RunShell(ByVal command As String) As String
#If Mac Then
    On Error GoTo LegacyMacScript
    RunShell = AppleScriptTask("BacktestRunner.scpt", "RunShell", command)
    Exit Function
LegacyMacScript:
    On Error GoTo 0
    RunShell = MacScript("do shell script " & AppleScriptQuote(command))
#Else
    Err.Raise vbObjectError + 1000, "BacktestRunner", "This runner is configured for macOS Excel."
#End If
End Function

Private Sub OpenPath(ByVal path As String)
    On Error Resume Next
#If Mac Then
    AppleScriptTask "BacktestRunner.scpt", "OpenPath", path
    If Err.Number <> 0 Then
        Err.Clear
        MacScript "do shell script " & AppleScriptQuote("open " & ShellQuote(path))
    End If
#End If
End Sub

Private Function ShellQuote(ByVal value As String) As String
    If InStr(1, value, "'", vbBinaryCompare) > 0 Then
        Err.Raise vbObjectError + 1001, "BacktestRunner", "Path contains an apostrophe and cannot be shell-quoted safely: " & value
    End If
    ShellQuote = "'" & value & "'"
End Function

Private Function AppleScriptQuote(ByVal value As String) As String
    Dim escaped As String
    escaped = Replace(value, "\", "\\")
    escaped = Replace(escaped, Chr(34), Chr(92) & Chr(34))
    AppleScriptQuote = Chr(34) & escaped & Chr(34)
End Function

Private Function WorkbookStem(ByVal fileName As String) As String
    Dim dotPos As Long
    dotPos = InStrRev(fileName, ".")
    If dotPos > 1 Then
        WorkbookStem = Left(fileName, dotPos - 1)
    Else
        WorkbookStem = fileName
    End If
End Function

Private Function RunnerOutputStem(ByVal fileName As String) As String
    Dim stem As String
    Dim runPos As Long
    stem = WorkbookStem(fileName)
    runPos = InStr(1, stem, "_run_", vbTextCompare)
    If runPos > 1 Then
        RunnerOutputStem = Left(stem, runPos - 1)
    Else
        RunnerOutputStem = stem
    End If
End Function

Private Function TryOpenWorkbook(ByVal path As String) As Boolean
    On Error Resume Next
    Err.Clear
    Application.Workbooks.Open Filename:=path
    TryOpenWorkbook = (Err.Number = 0)
    Err.Clear
    On Error GoTo 0
End Function

Private Function GetOrCreateSheet(ByVal sheetName As String) As Worksheet
    On Error Resume Next
    Set GetOrCreateSheet = ThisWorkbook.Worksheets(sheetName)
    On Error GoTo 0
    If GetOrCreateSheet Is Nothing Then
        Set GetOrCreateSheet = ThisWorkbook.Worksheets.Add(Before:=ThisWorkbook.Worksheets(1))
        GetOrCreateSheet.Name = sheetName
    End If
End Function

Private Sub DeleteRunnerButtons(ByVal ws As Worksheet)
    Dim idx As Long
    On Error Resume Next
    For idx = ws.Buttons.Count To 1 Step -1
        ws.Buttons(idx).Delete
    Next idx
    On Error GoTo 0
End Sub

Private Sub AddRunnerButton( _
    ByVal ws As Worksheet, _
    ByVal caption As String, _
    ByVal macroName As String, _
    ByVal leftPos As Double, _
    ByVal topPos As Double _
)
    Dim btn As Button
    Set btn = ws.Buttons.Add(leftPos, topPos, 150, 34)
    btn.Characters.Text = caption
    btn.OnAction = macroName
End Sub

Private Sub SetLastRunCells(ByVal logPath As String, ByVal outputPath As String)
    Dim ws As Worksheet
    Set ws = GetOrCreateSheet("Runner")
    ws.Range("B6").Value = logPath
    ws.Range("B7").Value = outputPath
End Sub
