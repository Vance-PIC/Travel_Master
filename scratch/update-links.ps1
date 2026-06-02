# scratch/update-links.ps1
$srcDir = "C:\Home\熊本旅遊實作\日本東西行軍路線\src"

$map = @(
    @("\./13_Day12_羽田機場最後血拼與返台\.md", "./14_Day12_羽田機場最後血拼與返台.md"),
    @("\./12_Day11_廣島飛羽田與狂熱演唱會\.md", "./13_Day11_廣島飛羽田與狂熱演唱會.md"),
    @("\./11_Day10_聖地宮島SA皮克敏冒險\.md", "./12_Day10_聖地宮島SA皮克敏冒險.md"),
    @("\./10_Day9_宮島嚴島神社海上鳥居\.md", "./11_Day9_宮島嚴島神社海上鳥居.md"),
    @("\./09_Day8_清晨移防廣島市區遊\.md", "./10_Day8_清晨移防廣島市區遊.md"),
    @("\./08_Day7_名古屋城與久屋大通\.md", "./09_Day7_名古屋城與久屋大通.md"),
    @("\./07_Day6_直飛名古屋與大須逛街\.md", "./08_Day6_直飛名古屋與大須逛街.md"),
    @("\./06_Day5_特急津輕秋田朝聖\.md", "./07_Day5_特急津輕秋田朝聖.md"),
    @("\./05_Day4_陸奧弘前煙火大會\.md", "./06_Day4_陸奧弘前煙火大會.md"),
    @("\./04_Day3_深入東北石卷探險\.md", "./05_Day3_深入東北石卷探險.md"),
    @("\./03_Day2_橫濱漫遊與秋葉原模型\.md", "./04_Day2_橫濱漫遊與秋葉原模型.md"),
    @("\./02_Day1_抵達羽田與橫濱弄髮\.md", "./03_Day1_抵達羽田與橫濱弄髮.md")
)

Get-ChildItem -Path "$srcDir\*.md" | ForEach-Object {
    $content = Get-Content $_.FullName -Raw -Encoding UTF8
    
    foreach ($m in $map) {
        $content = $content -replace $m[0], $m[1]
    }
    
    if ($_.Name -eq "01_Chapter1_核心戰報與財務預算.md") {
        $content = $content -replace '\[➡️ 下一頁 \(Day 1\)\]\(\./03_Day1_抵達羽田與橫濱弄髮\.md\)', '[➡️ 下一頁 (第二章：作戰守則)](./02_Chapter2_每日詳細作戰中心.md)'
    }
    
    if ($_.Name -eq "03_Day1_抵達羽田與橫濱弄髮.md") {
        $content = $content -replace '\[⬅️ 上一頁 \(出發前戰報\)\]\(\./01_Chapter1_核心戰報與財務預算\.md\)', '[⬅️ 上一頁 (第二章)](./02_Chapter2_每日詳細作戰中心.md)'
    }
    
    $content | Set-Content $_.FullName -Encoding UTF8
    Write-Host "Updated links in $($_.Name)"
}
