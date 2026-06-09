$mapping = @{
    "./03_Day1_抵達熊本與櫻町放電.md" = "./02.01_Day1_抵達熊本與櫻町放電.md"
    "./04_Day2_熊本城巡禮與領車任務.md" = "./02.02_Day2_熊本城巡禮與領車任務.md"
    "./05_Day3_Greenland全日遊.md" = "./02.03_Day3_Greenland全日遊.md"
    "./06_Day4_挺進阿蘇與農場探險.md" = "./02.04_Day4_挺進阿蘇與農場探險.md"
    "./07_Day5_農場深度玩與和牛烤肉.md" = "./02.05_Day5_農場深度玩與和牛烤肉.md"
    "./08_Day6_阿蘇神社與採果大慶功.md" = "./02.06_Day6_阿蘇神社與採果大慶功.md"
    "./09_Day7_機場最後衝刺.md" = "./02.07_Day7_機場最後衝刺.md"
}

# 修正對照表中的檔名（去除首尾的 ./）
$rawMapping = @{}
foreach ($key in $mapping.Keys) {
    $rawKey = $key.Replace("./", "")
    $rawValue = $mapping[$key].Replace("./", "")
    $rawMapping[$rawKey] = $rawValue
}

$srcDir = "C:\Home\旅遊大師\specs\kumamoto\src"
$files = Get-ChildItem -Path $srcDir -Filter "*.md"

foreach ($file in $files) {
    Write-Host "Processing $($file.Name)..."
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    
    # 替換對照表中的所有檔案名稱
    foreach ($oldName in $rawMapping.Keys) {
        $newName = $rawMapping[$oldName]
        if ($content.Contains($oldName)) {
            Write-Host "  Replacing $oldName -> $newName"
            $content = $content.Replace($oldName, $newName)
        }
    }
    
    # 確保存回時使用 UTF8 編碼
    [System.IO.File]::WriteAllText($file.FullName, $content, [System.Text.Encoding]::UTF8)
}
Write-Host "Kumamoto links updated!"
