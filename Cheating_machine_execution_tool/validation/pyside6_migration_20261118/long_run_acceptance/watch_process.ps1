param(
    [Parameter(Mandatory)][ValidateRange(1,2147483647)][int]$TargetProcessId,
    [Parameter(Mandatory)][string]$OutputPath,
    [Parameter(Mandatory)][ValidateRange(1,31536000)][int]$DurationSeconds,
    [ValidateRange(1,3600)][int]$IntervalSeconds = 60
)

$ErrorActionPreference = 'Stop'
$target = $null
$stream = $null
$writer = $null
$exitCode = 0

function Write-Record([hashtable]$Fields) {
    $Fields['utc'] = [DateTime]::UtcNow.ToString('o')
    $Fields['pid'] = $TargetProcessId
    $Fields['start_utc'] = $startUtc
    $writer.WriteLine(($Fields | ConvertTo-Json -Depth 3 -Compress))
    $writer.Flush()
}

try {
    $path = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
    $stopFile = "$path.stop"
    if ([IO.File]::Exists($stopFile)) { throw "A stop marker already exists: $stopFile" }
    $target = [Diagnostics.Process]::GetProcessById($TargetProcessId)
    # Keep this process object's OS handle open to distinguish a later PID reuse.
    $null = $target.Handle
    $startUtc = $target.StartTime.ToUniversalTime().ToString('o')
    $name = $target.ProcessName
    $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
    Write-Record @{event='start'; process_name=$name; interval_s=$IntervalSeconds; requested_s=$DurationSeconds}
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $previousTime = $null
    $previousCpu = $null
    $next = 0.0
    while ($true) {
        if ($target.HasExited) { $reason = 'target_exited'; $exitCode = 2; break }
        if ([IO.File]::Exists($stopFile)) { $reason = 'operator_stop'; break }
        $remaining = $next - $clock.Elapsed.TotalSeconds
        if ($remaining -gt 0) {
            $null = $target.WaitForExit([int][Math]::Ceiling([Math]::Min(1, $remaining) * 1000))
            continue
        }
        $target.Refresh()
        $now = $clock.Elapsed.TotalSeconds
        $cpu = $target.TotalProcessorTime.TotalSeconds
        $row = @{
            event='sample'; elapsed_s=$now; cpu_total_s=$cpu; cpu_pct_one_core=$null
            working_set_bytes=$target.WorkingSet64; private_bytes=$target.PrivateMemorySize64
            threads=$target.Threads.Count; interval_actual_s=$null; gap=$false
        }
        if ($target.HasExited) { $reason = 'target_exited'; $exitCode = 2; break }
        if ($null -ne $previousTime) {
            $dt = $now - $previousTime
            $row.interval_actual_s = $dt
            $row.gap = $dt -gt 1.5 * $IntervalSeconds
            if (!$row.gap -and $dt -gt 0) {
                $row.cpu_pct_one_core = [Math]::Round(100 * ($cpu - $previousCpu) / $dt, 2)
            }
        }
        Write-Record $row
        if ($now -ge $DurationSeconds) { $reason = 'observation_window_ended'; break }
        $previousTime = $now
        $previousCpu = $cpu
        $next = [Math]::Min($DurationSeconds, $now + $IntervalSeconds)
    }
    Write-Record @{event='end'; reason=$reason; elapsed_s=$clock.Elapsed.TotalSeconds}
}
catch {
    $problem = $_.Exception
    if ($null -ne $writer) {
        $reason = 'sample_error'
        if ($target.HasExited) { $reason = 'target_exited' }
        Write-Record @{event='end'; reason=$reason; error_type=$problem.GetType().Name}
    }
    [Console]::Error.WriteLine($problem.Message)
    $exitCode = 2
}
finally {
    if ($null -ne $writer) { $writer.Dispose() }
    if ($null -ne $stream) { $stream.Dispose() }
    if ($null -ne $target) { $target.Dispose() }
}
exit $exitCode
