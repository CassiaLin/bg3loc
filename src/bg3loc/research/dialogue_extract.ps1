param([string]$Inventory, [string]$GameDir, [string]$LSLibDir, [string]$Output)
$ErrorActionPreference = 'Stop'
[Reflection.Assembly]::LoadFrom((Join-Path $LSLibDir 'Newtonsoft.Json.dll')) | Out-Null
[Reflection.Assembly]::LoadFrom((Join-Path $LSLibDir 'LSLib.dll')) | Out-Null
$rows = Get-Content -LiteralPath $Inventory -Raw | ConvertFrom-Json
$writer = [System.IO.StreamWriter]::new($Output, $false, [System.Text.UTF8Encoding]::new($false))
$count = 0
try {
    foreach ($group in ($rows | Group-Object package)) {
        $pakPath = Join-Path (Join-Path $GameDir 'Data') $group.Name
        $pkg = [LSLib.LS.PackageReader]::new().Read($pakPath, $false)
        try {
            $selected = @{}
            foreach ($row in $group.Group) { $selected[$row.resource] = $true }
            foreach ($entry in $pkg.Files) {
                $path = $entry.Name.Replace('\', '/')
                if (-not $selected.ContainsKey($path)) { continue }
                $stream = $entry.CreateContentReader()
                $mem = [System.IO.MemoryStream]::new()
                try {
                    $stream.CopyTo($mem); $mem.Position = 0
                    if ([System.IO.Path]::GetExtension($path) -eq '.lsf') {
                        $resource = [LSLib.LS.LSFReader]::new($mem).Read()
                        $converted = [System.IO.MemoryStream]::new()
                        try {
                            $jsw = [LSLib.LS.LSJWriter]::new($converted)
                            $jsw.Write($resource)
                            $text = [System.Text.Encoding]::UTF8.GetString($converted.ToArray())
                        } finally { $converted.Dispose() }
                    } else { $text = [System.Text.Encoding]::UTF8.GetString($mem.ToArray()) }
                    $record = [Newtonsoft.Json.Linq.JObject]::new()
                    $record.Add('package', [Newtonsoft.Json.Linq.JValue]::new([string]$group.Name))
                    $record.Add('resource', [Newtonsoft.Json.Linq.JValue]::new([string]$path))
                    $record.Add('data', [Newtonsoft.Json.Linq.JObject]::Parse($text.TrimStart([char]0xfeff)))
                    $writer.WriteLine($record.ToString([Newtonsoft.Json.Formatting]::None))
                    $selected.Remove($path)
                    $count++
                    if ($count % 1000 -eq 0) { Write-Output "Extracted dialogue resources: $count" }
                } finally { $stream.Dispose(); $mem.Dispose() }
            }
            if ($selected.Count -ne 0) { throw 'Selected dialogue resources were not extracted' }
        } finally { $pkg.Dispose() }
    }
} finally { $writer.Dispose() }
Write-Output "Extracted dialogue resources: $count"
