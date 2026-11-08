# Helper for setup-llm.bat (ASCII only, writes UTF-8 without BOM)
#   -Action yaml   : misc\llama-swap.config.template.yaml -> llama-swap\config.yaml
#   -Action config : set base_url (and model) in user-data\config.json, keeping other keys
param(
    [string]$Action,
    [string]$Root,
    [string]$Lumimaid = "0",
    [string]$Url = "",
    [string]$Model = ""
)
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)

if ($Action -eq "yaml") {
    $tpl = [IO.File]::ReadAllText("$Root\misc\llama-swap.config.template.yaml")
    if ($Lumimaid -ne "1") {
        $tpl = [regex]::Replace($tpl, "(?s)[ \t]*# BEGIN lumimaid.*?# END lumimaid\r?\n", "")
    }
    $tpl = $tpl.Replace("__ROOT__", $Root.Replace("\", "/"))
    [IO.File]::WriteAllText("$Root\llama-swap\config.yaml", $tpl, $utf8)
    Write-Host "[OK] wrote llama-swap\config.yaml"
}
elseif ($Action -eq "config") {
    New-Item -ItemType Directory -Force -Path "$Root\user-data" | Out-Null
    $p = "$Root\user-data\config.json"
    $o = [ordered]@{}
    if (Test-Path $p) {
        $j = Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($prop in $j.PSObject.Properties) { $o[$prop.Name] = $prop.Value }
    }
    $o["base_url"] = $Url
    if ($Model -ne "") { $o["model"] = $Model }
    [IO.File]::WriteAllText($p, ($o | ConvertTo-Json -Depth 5), $utf8)
    Write-Host "[OK] updated user-data\config.json: base_url=$Url model=$Model"
}
else {
    Write-Host "[NG] unknown action: $Action"
    exit 1
}
