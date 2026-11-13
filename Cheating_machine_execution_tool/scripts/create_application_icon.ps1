param(
    [string]$SourcePng = "",
    [string]$OutputIco = ""
)

# Windows-only asset export; uses System.Drawing, not the application environment.
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $SourcePng) { $SourcePng = Join-Path $projectRoot "assets\icons\line_check_assistant_network_topology_v1.png" }
if (-not $OutputIco) { $OutputIco = Join-Path $projectRoot "assets\icons\line_check_assistant_network_topology_v1.ico" }
Add-Type -AssemblyName System.Drawing
$source = [System.Drawing.Image]::FromFile($SourcePng)
$sizes = @(16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
$frames = [System.Collections.Generic.List[byte[]]]::new()
try {
    if ($source.Width -ne $source.Height -or $source.Width -lt 256) {
        throw "Source must be square and at least 256 pixels."
    }
    foreach ($size in $sizes) {
        $bitmap = [System.Drawing.Bitmap]::new($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $stream = [System.IO.MemoryStream]::new()
        try {
            $graphics.Clear([System.Drawing.Color]::Transparent)
            $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $graphics.DrawImage($source, [System.Drawing.Rectangle]::new(0, 0, $size, $size))
            if ($size -eq 256) {
                $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
            } else {
                # Native 32-bit DIB frames avoid Tk 8.6's PNG-ICO shell fallback.
                $writer = [System.IO.BinaryWriter]::new($stream)
                $stride = $size * 4
                $maskStride = [int]([Math]::Ceiling($size / 32.0) * 4)
                $writer.Write([int]40)
                $writer.Write([int]$size)
                $writer.Write([int]($size * 2))
                $writer.Write([uint16]1)
                $writer.Write([uint16]32)
                $writer.Write([int]0)
                $writer.Write([int](($stride + $maskStride) * $size))
                foreach ($unused in 1..4) { $writer.Write([int]0) }
                $rectangle = [System.Drawing.Rectangle]::new(0, 0, $size, $size)
                $locked = $bitmap.LockBits($rectangle, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
                try {
                    $row = [byte[]]::new($stride)
                    $masks = [System.IO.MemoryStream]::new()
                    try {
                        for ($y = $size - 1; $y -ge 0; $y--) {
                            [System.Runtime.InteropServices.Marshal]::Copy([IntPtr]::Add($locked.Scan0, $y * $locked.Stride), $row, 0, $stride)
                            $writer.Write($row)
                            $mask = [byte[]]::new($maskStride)
                            for ($x = 0; $x -lt $size; $x++) {
                                if ($row[$x * 4 + 3] -eq 0) {
                                    $mask[[int][Math]::Floor($x / 8.0)] = $mask[[int][Math]::Floor($x / 8.0)] -bor (0x80 -shr ($x % 8))
                                }
                            }
                            $masks.Write($mask, 0, $mask.Length)
                        }
                        $writer.Write($masks.ToArray())
                    } finally { $masks.Dispose() }
                } finally { $bitmap.UnlockBits($locked) }
                $writer.Flush()
            }
            $frames.Add($stream.ToArray())
        } finally {
            $stream.Dispose()
            $graphics.Dispose()
            $bitmap.Dispose()
        }
    }
    $output = [System.IO.MemoryStream]::new()
    $header = [System.IO.BinaryWriter]::new($output)
    try {
        $header.Write([uint16]0)
        $header.Write([uint16]1)
        $header.Write([uint16]$sizes.Count)
        $offset = 6 + 16 * $sizes.Count
        for ($index = 0; $index -lt $sizes.Count; $index++) {
            $dimension = if ($sizes[$index] -eq 256) { 0 } else { $sizes[$index] }
            $header.Write([byte]$dimension)
            $header.Write([byte]$dimension)
            $header.Write([uint16]0)
            $header.Write([uint16]1)
            $header.Write([uint16]32)
            $header.Write([uint32]$frames[$index].Length)
            $header.Write([uint32]$offset)
            $offset += $frames[$index].Length
        }
        foreach ($frame in $frames) { $header.Write($frame) }
        $header.Flush()
        [System.IO.File]::WriteAllBytes([System.IO.Path]::GetFullPath($OutputIco), $output.ToArray())
    } finally {
        $header.Dispose()
        $output.Dispose()
    }
    Write-Output "APPLICATION_ICON_OK sizes=$($sizes -join ',') output=$OutputIco"
} finally { $source.Dispose() }
