$mapping = @{
    "./03_Day1_抵達羽田與橫濱弄髮.md" = "./02.01_Day1_抵達羽田與橫濱弄髮.md"
    "./04_Day2_橫濱漫遊與秋葉原模型.md" = "./02.02_Day2_橫濱漫遊與秋葉原模型.md"
    "./05_Day3_深入東北石卷探險.md" = "./02.03_Day3_深入東北石卷探險.md"
    "./06_Day4_陸奧弘前煙火大會.md" = "./02.04_Day4_陸奧弘前煙火大會.md"
    "./07_Day5_特急津輕秋田朝聖.md" = "./02.05_Day5_特急津輕秋田朝聖.md"
    "./08_Day6_直飛名古屋與大須逛街.md" = "./02.06_Day6_直飛名古屋與大須逛街.md"
    "./09_Day7_名古屋城與久屋大通.md" = "./02.07_Day7_名古屋城與久屋大通.md"
    "./10_Day8_清晨移防廣島市區遊.md" = "./02.08_Day8_清晨移防廣島市區遊.md"
    "./11_Day9_宮島嚴島神社海上鳥居.md" = "./02.09_Day9_宮島嚴島神社海上鳥居.md"
    "./12_Day10_聖地宮島SA皮克敏冒險.md" = "./02.10_Day10_聖地宮島SA皮克敏冒險.md"
    "./13_Day11_廣島飛羽田與狂熱演唱會.md" = "./02.11_Day11_廣島飛羽田與狂熱演唱會.md"
    "./14_Day12_羽田機場最後血拼與返台.md" = "./02.12_Day12_羽田機場最後血拼與返台.md"
}

# 修正對照表中的檔名（去除首尾的 ./）
$rawMapping = @{}
foreach ($key in $mapping.Keys) {
    $rawKey = $key.Replace("./", "")
    $rawValue = $mapping[$key].Replace("./", "")
    $rawMapping[$rawKey] = $rawValue
}

$srcDir = "C:\Home\旅遊大師\specs\japan-march\src"
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
Write-Host "All links updated!"
